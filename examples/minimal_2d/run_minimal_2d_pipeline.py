"""Minimal anonymized 2D-to-absolute SAXS reproducibility pipeline.

This script demonstrates a reviewer-friendly deterministic workflow:
1) Load an anonymized synthetic 2D detector image
2) Perform radial averaging to obtain a 1D profile
3) Estimate robust K-factor against a synthetic reference
4) Apply absolute scaling and export CSV/TSV/canSAS/NXcanSAS
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from saxsabs import estimate_k_factor_robust, write_cansas1d_xml, write_nxcansas_h5


def radial_average(image: np.ndarray, center_xy: tuple[float, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    yy, xx = np.indices(image.shape)
    rr = np.sqrt((xx - center_xy[0]) ** 2 + (yy - center_xy[1]) ** 2)
    rbin = rr.astype(int)

    q_pix = []
    i_mean = []
    i_err = []
    for rad in range(int(rbin.max()) + 1):
        sel = image[rbin == rad]
        if sel.size < 3:
            continue
        q_pix.append(float(rad))
        i_mean.append(float(sel.mean()))
        i_err.append(float(sel.std(ddof=1) / np.sqrt(sel.size)))

    return np.asarray(q_pix), np.asarray(i_mean), np.asarray(i_err)


def main() -> None:
    base = Path(__file__).resolve().parent
    out_dir = base / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    image = np.loadtxt(base / "synthetic_detector_image.csv", delimiter=",")
    geom = json.loads((base / "synthetic_geometry.json").read_text(encoding="utf-8"))

    q_pix, i_meas, err_meas = radial_average(image, tuple(geom["beam_center_px"]))
    q = q_pix * float(geom["q_per_pixel_Ainv"])

    # Deterministic synthetic reference profile: exactly 2x measured intensity.
    i_ref = 2.0 * i_meas

    k_result = estimate_k_factor_robust(
        q_meas=q,
        i_meas_per_cm=i_meas,
        q_ref=q,
        i_ref=i_ref,
        q_window=(float(q.min()), float(q.max())),
    )

    i_abs = k_result.k_factor * i_meas
    err_abs = k_result.k_factor * err_meas

    np.savetxt(
        out_dir / "measured_profile.csv",
        np.column_stack([q, i_meas, err_meas]),
        delimiter=",",
        header="q,i,err",
        comments="",
    )
    np.savetxt(
        out_dir / "reference_profile.csv",
        np.column_stack([q, i_ref]),
        delimiter=",",
        header="q,i",
        comments="",
    )
    np.savetxt(
        out_dir / "absolute_profile.csv",
        np.column_stack([q, i_abs, err_abs]),
        delimiter=",",
        header="q,i_abs,err_abs",
        comments="",
    )
    np.savetxt(
        out_dir / "absolute_profile.tsv",
        np.column_stack([q, i_abs, err_abs]),
        delimiter="\t",
        header="q\ti_abs\terr_abs",
        comments="",
    )

    meta = {
        "title": "saxsabs minimal anonymized 2D demo",
        "run": "minimal-2d-001",
        "wavelength_A": float(geom["wavelength_A"]),
        "sdd_m": float(geom["distance_m"]),
        "sample_name": "synthetic-anonymized",
        "instrument_name": "synthetic-detector",
        "detector_name": "synthetic-array",
        "process_name": "minimal_2d_pipeline",
    }
    write_cansas1d_xml(out_dir / "absolute_profile.xml", q=q, i_abs=i_abs, err=err_abs, metadata=meta)

    h5_written = False
    try:
        write_nxcansas_h5(out_dir / "absolute_profile.h5", q=q, i_abs=i_abs, err=err_abs, metadata=meta)
        h5_written = True
    except ImportError:
        pass

    summary = {
        "points": int(q.size),
        "q_min": float(q.min()),
        "q_max": float(q.max()),
        "k_factor": float(k_result.k_factor),
        "points_used": int(k_result.points_used),
        "xml_written": True,
        "h5_written": h5_written,
        "expected_k_factor_range": [1.99, 2.01],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if not 1.99 <= k_result.k_factor <= 2.01:
        raise RuntimeError(f"Unexpected k_factor: {k_result.k_factor}")

    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
