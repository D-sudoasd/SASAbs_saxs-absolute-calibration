"""Command-line interface for headless SAXS calibration operations.

Provides four sub-commands:

* ``norm-factor``      – compute a normalization factor
* ``parse-header``     – extract exp / monitor / transmission from JSON header
* ``parse-external1d`` – parse an external 1-D profile file
* ``estimate-k``       – robust K-factor estimation against a reference curve
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import pandas as pd

from . import __version__
from .core.normalization import compute_norm_factor
from .core.calibration import estimate_k_factor_robust
from .io.parsers import parse_header_values, read_external_1d_profile


def _die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _clean_column_name(name: object) -> str:
    return "".join(ch for ch in str(name).strip().lower() if ch.isalnum())


def _column_score(name: str, role: str) -> int:
    if role == "q":
        exact = {"q", "chi", "radial", "2theta", "twotheta", "s", "x"}
        prefixes = ("q", "chi", "radial", "twotheta")
        suffixes = ("q",)
    else:
        exact = {"i", "intensity", "irel", "iabs", "signal", "count", "counts", "y"}
        prefixes = ("intensity", "signal", "count", "irel", "iabs")
        suffixes = ("intensity",)

    if name in exact:
        return 300
    if any(name.startswith(prefix) and len(name) > len(prefix) for prefix in prefixes):
        return 200
    if any(name.endswith(suffix) and len(name) > len(suffix) for suffix in suffixes):
        return 150
    return 0


def _available_columns_message(columns: list[object]) -> str:
    return "Available columns: " + ", ".join(str(col) for col in columns)


def _read_tabular_dataframe(path: Path) -> pd.DataFrame:
    errors: list[str] = []
    read_trials = [
        {"sep": None, "engine": "python", "comment": "#"},
        {"sep": r"[,\s;]+", "engine": "python", "comment": "#"},
    ]
    for kwargs in read_trials:
        try:
            df = pd.read_csv(path, **kwargs)
        except Exception as exc:
            errors.append(str(exc))
            continue
        if df is not None and not df.empty and df.shape[1] >= 2:
            return df

    detail = f" ({'; '.join(errors[:2])})" if errors else ""
    raise ValueError(f"Cannot parse tabular profile for column overrides: {path.name}{detail}")


def _resolve_column(
    columns: list[object],
    requested: str | None,
    role: str,
    profile_label: str,
) -> object:
    if requested:
        if requested in columns:
            return requested
        requested_clean = _clean_column_name(requested)
        matches = [col for col in columns if _clean_column_name(col) == requested_clean]
        if len(matches) == 1:
            return matches[0]
        raise ValueError(
            f"{profile_label} {role} column '{requested}' not found. "
            f"{_available_columns_message(columns)}"
        )

    best_col = None
    best_score = 0
    for col in columns:
        score = _column_score(_clean_column_name(col), role)
        if score > best_score:
            best_col = col
            best_score = score
    if best_col is not None:
        return best_col

    raise ValueError(
        f"Cannot identify {profile_label} {role} column. {_available_columns_message(columns)}"
    )


def _read_profile_for_estimate(
    path: Path,
    *,
    q_col: str | None,
    i_col: str | None,
    profile_label: str,
) -> tuple[object, object]:
    if q_col is None and i_col is None:
        parsed = read_external_1d_profile(path)
        return parsed["x"], parsed["i_rel"]

    df = _read_tabular_dataframe(path)
    columns = list(df.columns)
    resolved_q_col = _resolve_column(columns, q_col, "q", profile_label)
    resolved_i_col = _resolve_column(columns, i_col, "intensity", profile_label)

    q = pd.to_numeric(df[resolved_q_col], errors="coerce").to_numpy(dtype=float)
    intensity = pd.to_numeric(df[resolved_i_col], errors="coerce").to_numpy(dtype=float)
    return q, intensity


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="saxsabs", description="SAXS absolute intensity utilities")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    p_norm = sub.add_parser("norm-factor", help="Compute normalization factor")
    p_norm.add_argument("--exp", type=float, default=None)
    p_norm.add_argument("--mon", type=float, required=True)
    p_norm.add_argument("--trans", type=float, required=True)
    p_norm.add_argument("--mode", choices=["rate", "integrated"], required=True)

    p_head = sub.add_parser("parse-header", help="Parse header JSON file and extract exp/mon/trans")
    p_head.add_argument("--header-json", required=True, type=Path)

    p_profile = sub.add_parser("parse-external1d", help="Parse external 1D profile file")
    p_profile.add_argument("--input", required=True, type=Path)

    p_k = sub.add_parser("estimate-k", help="Estimate robust K-factor from measured and reference CSV")
    p_k.add_argument("--meas", required=True, type=Path, help="Measured profile CSV with columns q,i")
    p_k.add_argument("--ref", required=True, type=Path, help="Reference profile CSV with columns q,i")
    p_k.add_argument("--q-col", default=None, help="Measured q column override")
    p_k.add_argument("--i-col", default=None, help="Measured intensity column override")
    p_k.add_argument("--ref-q-col", default=None, help="Reference q column override")
    p_k.add_argument("--ref-i-col", default=None, help="Reference intensity column override")
    p_k.add_argument("--qmin", type=float, default=0.01)
    p_k.add_argument("--qmax", type=float, default=0.2)

    p_bl = sub.add_parser(
        "bl19b2-abs2d",
        help="Process BL19B2 dat001 TIFFs into absolute corrected 2D HDF5/EDF outputs",
    )
    p_bl.add_argument("--input-root", required=True, type=Path)
    geometry = p_bl.add_mutually_exclusive_group(required=True)
    geometry.add_argument("--poni", type=Path)
    geometry.add_argument("--pydidas-cali-yaml", type=Path)
    p_bl.add_argument("--mask", type=Path, default=None)
    p_bl.add_argument("--dark", type=Path, default=None, help="Explicit BL19B2 dark reference TIFF")
    p_bl.add_argument("--background", type=Path, default=None, help="Explicit BL19B2 background TIFF")
    p_bl.add_argument("--standard", type=Path, default=None, help="Explicit BL19B2 standard TIFF")
    p_bl.add_argument("--direct-beam", type=Path, default=None, help="Optional direct-beam QC TIFF")
    p_bl.add_argument("--output-root", type=Path, default=None)
    p_bl.add_argument(
        "--mu",
        type=float,
        default=20.2,
        help=(
            "mu in cm^-1 for Beer-Lambert thickness d=-ln(ABS)/mu; "
            "must match material and X-ray energy"
        ),
    )
    p_bl.add_argument("--alpha", type=float, default=1.0, help="background scaling factor")
    p_bl.add_argument("--qmin", type=float, default=0.01)
    p_bl.add_argument("--qmax", type=float, default=0.2)
    p_bl.add_argument("--npt", type=int, default=1000)
    p_bl.add_argument("--max-frames", type=int, default=None)
    p_bl.add_argument("--dry-run", action="store_true")
    p_bl.add_argument("--overwrite", action="store_true")
    p_bl.add_argument("--no-preview", action="store_true")
    p_bl.add_argument("--dtype", choices=["float32", "float64"], default="float32")
    p_bl.add_argument("--standard-thickness-cm", type=float, default=None)
    p_bl.add_argument(
        "--dark-hot-pixel-threshold",
        type=float,
        default=10.0,
        help="Dark pixels with abs(dark) greater than this detector count value are added to the mask",
    )

    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "norm-factor":
        out = compute_norm_factor(args.exp, args.mon, args.trans, args.mode)
        if not math.isfinite(out):
            _die(
                "Invalid normalization factor: non-finite result. "
                "Check that mon > 0, trans must be 0 < T <= 1, "
                "and exp > 0 for rate mode."
            )
        print(out)
        return

    if args.command == "parse-header":
        header = json.loads(args.header_json.read_text(encoding="utf-8"))
        exp, mon, trans = parse_header_values(header)
        print(json.dumps({"exp_s": exp, "i0": mon, "trans": trans}, ensure_ascii=False))
        return

    if args.command == "parse-external1d":
        result = read_external_1d_profile(args.input)
        print(
            json.dumps(
                {
                    "points": int(result["x"].size),
                    "x_col": result["x_col"],
                    "i_col": result["i_col"],
                    "err_col": result["err_col"],
                },
                ensure_ascii=False,
            )
        )
        return

    if args.command == "estimate-k":
        try:
            q_meas, i_meas = _read_profile_for_estimate(
                args.meas,
                q_col=args.q_col,
                i_col=args.i_col,
                profile_label="measured",
            )
            q_ref, i_ref = _read_profile_for_estimate(
                args.ref,
                q_col=args.ref_q_col,
                i_col=args.ref_i_col,
                profile_label="reference",
            )
            out = estimate_k_factor_robust(
                q_meas=q_meas,
                i_meas_per_cm=i_meas,
                q_ref=q_ref,
                i_ref=i_ref,
                q_window=(args.qmin, args.qmax),
            )
        except ValueError as exc:
            _die(f"estimate-k failed: {exc}")
        print(
            json.dumps(
                {
                    "k_factor": out.k_factor,
                    "k_std": out.k_std,
                    "q_min_overlap": out.q_min_overlap,
                    "q_max_overlap": out.q_max_overlap,
                    "points_used": out.points_used,
                    "points_total": out.points_total,
                },
                ensure_ascii=False,
            )
        )
        return

    if args.command == "bl19b2-abs2d":
        from .workflows.bl19b2_abs2d import BL19B2Abs2DConfig, run_bl19b2_abs2d

        out = run_bl19b2_abs2d(
            BL19B2Abs2DConfig(
                input_root=args.input_root,
                poni_path=args.poni,
                pydidas_cali_yaml=args.pydidas_cali_yaml,
                mask_path=args.mask,
                dark_path=args.dark,
                background_path=args.background,
                standard_path=args.standard,
                direct_path=args.direct_beam,
                output_root=args.output_root,
                mu_cm_inv=args.mu,
                alpha=args.alpha,
                q_window=(args.qmin, args.qmax),
                npt=args.npt,
                dtype=args.dtype,
                dry_run=args.dry_run,
                max_frames=args.max_frames,
                overwrite=args.overwrite,
                write_preview=not args.no_preview,
                standard_thickness_cm=args.standard_thickness_cm,
                dark_hot_pixel_threshold=args.dark_hot_pixel_threshold,
            )
        )
        print(json.dumps(out, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
