"""Independent synthetic raw-frame validation of the absolute SAXS chain.

Unlike the former circular demo, the reference is not derived from the measured
profile.  Raw dark, NIST blank, SRM 3600, and sample frames are generated from
fixed physical inputs and then passed through the production reduction API.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from saxsabs import (  # noqa: E402
    build_nist_net_image,
    estimate_k_factor_robust,
    get_reference_data,
    write_cansas1d_xml,
    write_nxcansas_h5,
)


K_TRUE = 2.0
SRM3600_THICKNESS_CM = 0.1055
SAMPLE_THICKNESS_CM = 0.08


def radial_average(
    image: np.ndarray,
    center_xy: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.indices(image.shape)
    rr = np.sqrt((xx - center_xy[0]) ** 2 + (yy - center_xy[1]) ** 2)
    rbin = rr.astype(int)
    radius = []
    intensity = []
    for rad in range(int(rbin.max()) + 1):
        selected = np.asarray(image[rbin == rad], dtype=np.float64)
        if selected.size < 3:
            continue
        radius.append(float(rad))
        intensity.append(float(np.mean(selected)))
    return np.asarray(radius), np.asarray(intensity)


def _radial_q_grid(shape: tuple[int, int], center_xy: tuple[float, float], q_per_pixel: float):
    yy, xx = np.indices(shape)
    rbin = np.sqrt((xx - center_xy[0]) ** 2 + (yy - center_xy[1]) ** 2).astype(int)
    return rbin.astype(np.float64) * float(q_per_pixel)


def _sample_absolute_profile(q: np.ndarray) -> np.ndarray:
    """Independent analytic sample truth in cm^-1."""
    return 0.75 + 8.0 / (1.0 + (q / 0.035) ** 2)


def build_synthetic_raw_frames(
    shape: tuple[int, int],
    center_xy: tuple[float, float],
    q_per_pixel: float,
) -> tuple[dict[str, np.ndarray], dict[str, float], np.ndarray]:
    q_image = _radial_q_grid(shape, center_xy, q_per_pixel)
    q_ref, i_ref = get_reference_data("SRM3600")
    standard_absolute = np.interp(q_image, q_ref, i_ref)
    sample_absolute = _sample_absolute_profile(q_image)

    meta = {
        "dark_exp": 1.0,
        "background_exp": 4.0,
        "standard_exp": 5.0,
        "sample_exp": 6.0,
        "background_monitor": 120.0,
        "standard_monitor": 100.0,
        "sample_monitor": 80.0,
        "standard_transmission": 0.72,
        "sample_transmission": 0.65,
    }
    dark_rate = 2.0
    blank_normalized = 0.4
    norm_background = meta["background_exp"] * meta["background_monitor"]
    norm_standard = (
        meta["standard_exp"] * meta["standard_monitor"] * meta["standard_transmission"]
    )
    norm_sample = meta["sample_exp"] * meta["sample_monitor"] * meta["sample_transmission"]

    dark = np.full(shape, dark_rate * meta["dark_exp"], dtype=np.float64)
    background = np.full(
        shape,
        blank_normalized * norm_background + dark_rate * meta["background_exp"],
        dtype=np.float64,
    )
    standard_net = standard_absolute * SRM3600_THICKNESS_CM / K_TRUE
    standard = (
        (standard_net + blank_normalized) * norm_standard
        + dark_rate * meta["standard_exp"]
    )
    sample_net = sample_absolute * SAMPLE_THICKNESS_CM / K_TRUE
    sample = (
        (sample_net + blank_normalized) * norm_sample + dark_rate * meta["sample_exp"]
    )
    return {
        "dark": dark,
        "background": background,
        "standard": standard,
        "sample": sample,
    }, meta, sample_absolute


def run_pipeline(output_dir: Path) -> dict[str, object]:
    base = Path(__file__).resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)
    geometry = json.loads((base / "synthetic_geometry.json").read_text(encoding="utf-8"))
    source_image = np.loadtxt(base / "synthetic_detector_image.csv", delimiter=",")
    center = tuple(geometry["beam_center_px"])
    q_per_pixel = float(geometry["q_per_pixel_Ainv"])
    frames, meta, sample_absolute_image = build_synthetic_raw_frames(
        source_image.shape,
        center,
        q_per_pixel,
    )

    standard_net = build_nist_net_image(
        frames["standard"],
        frames["background"],
        frames["dark"],
        sample_exposure_s=meta["standard_exp"],
        background_exposure_s=meta["background_exp"],
        dark_exposure_s=meta["dark_exp"],
        sample_monitor=meta["standard_monitor"],
        background_monitor=meta["background_monitor"],
        sample_transmission=meta["standard_transmission"],
        monitor_mode="rate",
    )
    sample_net = build_nist_net_image(
        frames["sample"],
        frames["background"],
        frames["dark"],
        sample_exposure_s=meta["sample_exp"],
        background_exposure_s=meta["background_exp"],
        dark_exposure_s=meta["dark_exp"],
        sample_monitor=meta["sample_monitor"],
        background_monitor=meta["background_monitor"],
        sample_transmission=meta["sample_transmission"],
        monitor_mode="rate",
    )

    radius, standard_measured = radial_average(standard_net.image, center)
    q = radius * q_per_pixel
    _, sample_measured = radial_average(sample_net.image, center)
    _, sample_expected = radial_average(sample_absolute_image, center)

    q_ref, i_ref = get_reference_data("SRM3600")
    k_result = estimate_k_factor_robust(
        q_meas=q,
        i_meas_per_cm=standard_measured / SRM3600_THICKNESS_CM,
        q_ref=q_ref,
        i_ref=i_ref,
        q_window=(max(0.01, float(q.min())), float(q.max())),
    )
    sample_absolute = sample_measured * k_result.k_factor / SAMPLE_THICKNESS_CM
    relative_error = np.abs(sample_absolute - sample_expected) / np.maximum(
        np.abs(sample_expected), 1e-12
    )

    np.savetxt(
        output_dir / "standard_measured_profile.csv",
        np.column_stack([q, standard_measured / SRM3600_THICKNESS_CM]),
        delimiter=",",
        header="q_A^-1,i_standard_measured_per_cm",
        comments="",
    )
    np.savetxt(
        output_dir / "absolute_profile.csv",
        np.column_stack([q, sample_absolute, np.full_like(q, np.nan)]),
        delimiter=",",
        header="q_A^-1,i_abs_cm^-1,uncertainty_unknown",
        comments="",
    )
    np.savetxt(
        output_dir / "absolute_profile.tsv",
        np.column_stack([q, sample_absolute, np.full_like(q, np.nan)]),
        delimiter="\t",
        header="q_A^-1\ti_abs_cm^-1\tuncertainty_unknown",
        comments="",
    )

    output_meta = {
        "title": "saxsabs independent synthetic raw-frame validation",
        "run": "minimal-2d-golden-001",
        "wavelength_A": float(geometry["wavelength_A"]),
        "sdd_m": float(geometry["distance_m"]),
        "sample_name": "synthetic-independent-golden",
        "instrument_name": "synthetic-detector",
        "detector_name": "synthetic-array",
        "process_name": "minimal_2d_pipeline",
        "uncertainty_status": "unknown_without_input_variances",
    }
    write_cansas1d_xml(
        output_dir / "absolute_profile.xml",
        q=q,
        i_abs=sample_absolute,
        err=None,
        metadata=output_meta,
    )
    h5_written = False
    try:
        write_nxcansas_h5(
            output_dir / "absolute_profile.h5",
            q=q,
            i_abs=sample_absolute,
            err=None,
            metadata=output_meta,
        )
        h5_written = True
    except ImportError:
        pass

    summary: dict[str, object] = {
        "validation_type": "independent_synthetic_raw_frames",
        "points": int(q.size),
        "q_min": float(q.min()),
        "q_max": float(q.max()),
        "expected_k_factor": K_TRUE,
        "k_factor": float(k_result.k_factor),
        "k_relative_error": float(abs(k_result.k_factor / K_TRUE - 1.0)),
        "sample_max_relative_error": float(np.max(relative_error)),
        "points_used": int(k_result.points_used),
        "xml_written": True,
        "h5_written": h5_written,
        "uncertainty_status": "unknown_without_input_variances",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    if float(summary["k_relative_error"]) >= 0.005:
        raise RuntimeError(f"K-factor validation failed: {summary}")
    if float(summary["sample_max_relative_error"]) >= 0.01:
        raise RuntimeError(f"sample absolute-intensity validation failed: {summary}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "outputs",
    )
    args = parser.parse_args()
    print(json.dumps(run_pipeline(args.output_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
