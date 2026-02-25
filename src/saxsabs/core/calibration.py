from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from saxsabs.constants import NIST_SRM3600_DATA


@dataclass(frozen=True)
class KFactorEstimationResult:
    k_factor: float
    k_std: float
    q_min_overlap: float
    q_max_overlap: float
    points_total: int
    points_used: int
    ratios_used: np.ndarray


def _regularize_profile(q: np.ndarray, i: np.ndarray, min_points: int = 3) -> tuple[np.ndarray, np.ndarray]:
    q_arr = np.asarray(q, dtype=np.float64)
    i_arr = np.asarray(i, dtype=np.float64)
    if q_arr.shape != i_arr.shape:
        raise ValueError("q and intensity shape mismatch")

    mask = np.isfinite(q_arr) & np.isfinite(i_arr)
    q_arr = q_arr[mask]
    i_arr = i_arr[mask]
    if q_arr.size < min_points:
        raise ValueError("insufficient valid points")

    order = np.argsort(q_arr)
    q_arr = q_arr[order]
    i_arr = i_arr[order]

    uq, inv = np.unique(q_arr, return_inverse=True)
    if uq.size != q_arr.size:
        i_sum = np.zeros_like(uq, dtype=np.float64)
        cnt = np.zeros_like(uq, dtype=np.float64)
        for idx, grp in enumerate(inv):
            i_sum[grp] += i_arr[idx]
            cnt[grp] += 1.0
        i_arr = i_sum / np.clip(cnt, 1.0, None)
        q_arr = uq

    if q_arr.size < min_points:
        raise ValueError("insufficient unique q points")
    return q_arr, i_arr


def estimate_k_factor_robust(
    q_meas: np.ndarray,
    i_meas_per_cm: np.ndarray,
    q_ref: np.ndarray | None = None,
    i_ref: np.ndarray | None = None,
    q_window: tuple[float, float] = (0.01, 0.2),
    positive_floor: float = 1e-9,
    min_points: int = 3,
) -> KFactorEstimationResult:
    q_m, i_m = _regularize_profile(q_meas, i_meas_per_cm, min_points=min_points)

    if q_ref is None or i_ref is None:
        q_ref_all = NIST_SRM3600_DATA[:, 0]
        i_ref_all = NIST_SRM3600_DATA[:, 1]
    else:
        q_ref_all = np.asarray(q_ref, dtype=np.float64)
        i_ref_all = np.asarray(i_ref, dtype=np.float64)

    if q_ref_all.shape != i_ref_all.shape:
        raise ValueError("reference q/intensity shape mismatch")

    q_lo, q_hi = q_window
    win = (q_ref_all >= q_lo) & (q_ref_all <= q_hi)
    q_ref_all = q_ref_all[win]
    i_ref_all = i_ref_all[win]
    if q_ref_all.size < min_points:
        raise ValueError("reference points in q window are insufficient")

    q_min = float(max(np.nanmin(q_m), np.nanmin(q_ref_all)))
    q_max = float(min(np.nanmax(q_m), np.nanmax(q_ref_all)))
    overlap = (q_ref_all >= q_min) & (q_ref_all <= q_max)
    q_ref_used = q_ref_all[overlap]
    i_ref_used = i_ref_all[overlap]
    if q_ref_used.size < min_points:
        raise ValueError("q overlap with reference is insufficient")

    i_meas_interp = np.interp(q_ref_used, q_m, i_m)
    valid = np.isfinite(i_meas_interp) & (i_meas_interp > positive_floor)
    if int(valid.sum()) < min_points:
        raise ValueError("measured signal too weak or non-positive in overlap region")

    ratios = i_ref_used[valid] / i_meas_interp[valid]
    ratios = ratios[np.isfinite(ratios) & (ratios > 0)]
    if ratios.size < min_points:
        raise ValueError("insufficient valid ratio points for robust K estimation")

    r_med = float(np.nanmedian(ratios))
    r_mad = float(np.nanmedian(np.abs(ratios - r_med)))
    ratios_used = ratios
    if np.isfinite(r_mad) and r_mad > 0:
        robust_sigma = 1.4826 * r_mad
        inlier = np.abs(ratios - r_med) <= 3.0 * robust_sigma
        if int(inlier.sum()) >= min_points:
            ratios_used = ratios[inlier]

    k_val = float(np.nanmedian(ratios_used))
    k_std = float(np.nanstd(ratios_used))
    if not np.isfinite(k_val) or k_val <= 0:
        raise ValueError("estimated K factor is non-positive")

    return KFactorEstimationResult(
        k_factor=k_val,
        k_std=k_std,
        q_min_overlap=q_min,
        q_max_overlap=q_max,
        points_total=int(q_ref_used.size),
        points_used=int(ratios_used.size),
        ratios_used=ratios_used,
    )
