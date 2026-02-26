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
from pathlib import Path

import pandas as pd

from . import __version__
from .core.normalization import compute_norm_factor
from .core.calibration import estimate_k_factor_robust
from .io.parsers import parse_header_values, read_external_1d_profile


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
    p_k.add_argument("--qmin", type=float, default=0.01)
    p_k.add_argument("--qmax", type=float, default=0.2)

    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "norm-factor":
        out = compute_norm_factor(args.exp, args.mon, args.trans, args.mode)
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
        meas_df = pd.read_csv(args.meas)
        ref_df = pd.read_csv(args.ref)

        out = estimate_k_factor_robust(
            q_meas=meas_df["q"].to_numpy(dtype=float),
            i_meas_per_cm=meas_df["i"].to_numpy(dtype=float),
            q_ref=ref_df["q"].to_numpy(dtype=float),
            i_ref=ref_df["i"].to_numpy(dtype=float),
            q_window=(args.qmin, args.qmax),
        )
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


if __name__ == "__main__":
    main()
