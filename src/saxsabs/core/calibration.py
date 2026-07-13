"""Robust K-factor estimation for SAXS absolute intensity calibration.

The K-factor relates measured intensity to the absolute scale via a
reference standard (by default NIST SRM 3600 glassy carbon).  The
algorithm interpolates the measured profile onto the reference grid,
computes point-wise ratios, and applies median / MAD-based outlier
filtering to produce a robust estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from saxsabs.constants import (
    NIST_SRM3600_COVERAGE_FACTOR,
    NIST_SRM3600_DATA,
    NIST_SRM3600_UNCERTAINTY,
)


@dataclass(frozen=True)
class KFactorEstimationResult:
    """Container for the results of a robust K-factor estimation.

    Attributes:
        k_factor: Median K-factor (absolute-scale multiplier).
        k_std: Standard deviation of the inlier ratio distribution.  This is
            retained for compatibility and is ratio scatter, not a combined
            standard uncertainty of K.
        q_min_overlap: Lower bound of the q-overlap region (Å⁻¹).
        q_max_overlap: Upper bound of the q-overlap region (Å⁻¹).
        points_total: Total reference points in the overlap region.
        points_used: Number of inlier points after MAD filtering.
        ratios_used: 1-D array of inlier I_ref / I_meas ratios.
        k_statistical_standard_uncertainty: Standard error of the inlier ratios.
        k_standard_uncertainty: Combined standard uncertainty including the
            reference standard, or ``None`` when reference uncertainty is unknown.
        k_expanded_uncertainty: Expanded uncertainty, or ``None`` when no
            coverage factor or reference uncertainty is available.
        coverage_factor: Coverage factor used for the expanded uncertainty.
    """
    k_factor: float
    k_std: float
    q_min_overlap: float
    q_max_overlap: float
    points_total: int
    points_used: int
    ratios_used: np.ndarray
    k_statistical_standard_uncertainty: float = 0.0
    k_standard_uncertainty: float | None = None
    k_expanded_uncertainty: float | None = None
    coverage_factor: float | None = None


def _regularize_profile(q: np.ndarray, i: np.ndarray, min_points: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Validate, clean, sort, and deduplicate a 1-D scattering profile.

    Non-finite values are dropped, duplicate q-values are averaged, and
    the result is returned sorted in ascending q order.

    Args:
        q: Momentum-transfer vector (Å⁻¹).
        i: Corresponding intensity values.
        min_points: Minimum number of valid unique points required.

    Returns:
        Tuple ``(q_clean, i_clean)`` of 1-D float64 arrays.

    Raises:
        ValueError: On shape mismatch or insufficient valid data.
    """
    q_arr = np.asarray(q, dtype=np.float64)
    i_arr = np.asarray(i, dtype=np.float64)
    if q_arr.ndim != 1 or i_arr.ndim != 1:
        raise ValueError("q and intensity must be 1-D arrays")
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
    i_ref_standard_uncertainty: np.ndarray | None = None,
    coverage_factor: float | None = None,
    q_window: tuple[float, float] = (0.01, 0.2),
    positive_floor: float = 1e-9,
    min_points: int = 3,
) -> KFactorEstimationResult:
    """Estimate the absolute-intensity K-factor from measured and reference curves.

    The function interpolates *i_meas* onto the reference q-grid within the
    specified *q_window*, computes point-wise ``I_ref / I_meas`` ratios, and
    applies median ± 3×MAD outlier rejection to yield a robust K estimate.

    When *q_ref* / *i_ref* are ``None``, the built-in NIST SRM 3600 glassy
    carbon reference data are used.

    Args:
        q_meas: Momentum-transfer values of the measured profile (Å⁻¹).
        i_meas_per_cm: Measured intensity in absolute or relative units.
        q_ref: Reference q-values (optional; defaults to SRM 3600).
        i_ref: Reference intensity values (optional; defaults to SRM 3600).
        i_ref_standard_uncertainty: Point-wise combined standard uncertainty
            of *i_ref*.  The NIST certificate values are used with the built-in
            SRM 3600 reference.  Unknown uncertainty must be left as ``None``.
        coverage_factor: Factor for reporting expanded K uncertainty.  The
            certificate value is used with the built-in SRM 3600 reference.
        q_window: ``(q_min, q_max)`` bounding the comparison region.
        positive_floor: Threshold below which measured intensity is rejected.
        min_points: Minimum number of valid overlap points required.

    Returns:
        A :class:`KFactorEstimationResult` containing the K-factor and
        associated statistics.

    Raises:
        ValueError: On insufficient overlap, non-positive result, etc.
    """
    q_m, i_m = _regularize_profile(q_meas, i_meas_per_cm, min_points=min_points)

    if (q_ref is None) != (i_ref is None):
        raise ValueError("q_ref and i_ref must be supplied together")

    using_builtin_nist = q_ref is None and i_ref is None
    if using_builtin_nist:
        q_ref_all = NIST_SRM3600_DATA[:, 0]
        i_ref_all = NIST_SRM3600_DATA[:, 1]
        if i_ref_standard_uncertainty is None:
            u_ref_all: np.ndarray | None = NIST_SRM3600_UNCERTAINTY[:, 0]
            if coverage_factor is None:
                coverage_factor = NIST_SRM3600_COVERAGE_FACTOR
        else:
            u_ref_all = np.asarray(i_ref_standard_uncertainty, dtype=np.float64)
    else:
        q_ref_all = np.asarray(q_ref, dtype=np.float64)
        i_ref_all = np.asarray(i_ref, dtype=np.float64)
        u_ref_all = (
            None
            if i_ref_standard_uncertainty is None
            else np.asarray(i_ref_standard_uncertainty, dtype=np.float64)
        )

    if q_ref_all.shape != i_ref_all.shape:
        raise ValueError("reference q/intensity shape mismatch")
    if q_ref_all.ndim != 1:
        raise ValueError("reference q and intensity must be 1-D arrays")
    if not np.all(np.isfinite(q_ref_all)):
        raise ValueError("reference q must contain only finite values")
    if not np.all(np.isfinite(i_ref_all)) or np.any(i_ref_all <= 0):
        raise ValueError("reference intensity must be finite and > 0")
    if u_ref_all is not None:
        if u_ref_all.shape != i_ref_all.shape:
            raise ValueError("reference intensity/uncertainty shape mismatch")
        if not np.all(np.isfinite(u_ref_all)) or np.any(u_ref_all < 0):
            raise ValueError("reference standard uncertainty must be finite and non-negative")
    if coverage_factor is not None:
        coverage_factor = float(coverage_factor)
        if not np.isfinite(coverage_factor) or coverage_factor <= 0:
            raise ValueError("coverage_factor must be finite and > 0")

    q_lo, q_hi = q_window
    win = (q_ref_all >= q_lo) & (q_ref_all <= q_hi)
    q_ref_all = q_ref_all[win]
    i_ref_all = i_ref_all[win]
    if u_ref_all is not None:
        u_ref_all = u_ref_all[win]
    if q_ref_all.size < min_points:
        raise ValueError("reference points in q window are insufficient")

    q_min = float(max(np.nanmin(q_m), np.nanmin(q_ref_all)))
    q_max = float(min(np.nanmax(q_m), np.nanmax(q_ref_all)))
    overlap = (q_ref_all >= q_min) & (q_ref_all <= q_max)
    q_ref_used = q_ref_all[overlap]
    i_ref_used = i_ref_all[overlap]
    u_ref_used = None if u_ref_all is None else u_ref_all[overlap]
    if q_ref_used.size < min_points:
        raise ValueError("q overlap with reference is insufficient")

    i_meas_interp = np.interp(q_ref_used, q_m, i_m)
    valid = np.isfinite(i_meas_interp) & (i_meas_interp > positive_floor)
    if int(valid.sum()) < min_points:
        raise ValueError("measured signal too weak or non-positive in overlap region")

    measured_valid = i_meas_interp[valid]
    ratios = i_ref_used[valid] / measured_valid
    ratio_valid = np.isfinite(ratios) & (ratios > 0)
    ratios = ratios[ratio_valid]
    reference_ratio_uncertainty = None
    if u_ref_used is not None:
        reference_ratio_uncertainty = (
            u_ref_used[valid][ratio_valid] / measured_valid[ratio_valid]
        )
    if ratios.size < min_points:
        raise ValueError("insufficient valid ratio points for robust K estimation")

    r_med = float(np.nanmedian(ratios))
    r_mad = float(np.nanmedian(np.abs(ratios - r_med)))
    ratios_used = ratios
    if np.isfinite(r_mad):
        if r_mad > 0:
            tolerance = 3.0 * 1.4826 * r_mad
        else:
            # A majority of identical ratios gives MAD=0.  Retain the median
            # cluster instead of silently treating arbitrarily large deviations
            # as inliers.
            tolerance = 1e-12 * max(1.0, abs(r_med))
        inlier = np.abs(ratios - r_med) <= tolerance
        if int(inlier.sum()) < min_points:
            raise ValueError("insufficient inlier ratio points after MAD filtering")
        ratios_used = ratios[inlier]
        if reference_ratio_uncertainty is not None:
            reference_ratio_uncertainty = reference_ratio_uncertainty[inlier]

    k_val = float(np.nanmedian(ratios_used))
    k_std = float(np.nanstd(ratios_used))
    # The estimator is a median, whose normal-approximation standard error is
    # sqrt(pi/2) times the standard error of a mean from the same distribution.
    k_statistical_u = float(
        np.sqrt(np.pi / 2.0) * k_std / np.sqrt(ratios_used.size)
    )
    k_standard_u: float | None = None
    k_expanded_u: float | None = None
    if reference_ratio_uncertainty is not None:
        reference_u = float(np.nanmedian(reference_ratio_uncertainty))
        k_standard_u = float(np.hypot(k_statistical_u, reference_u))
        if coverage_factor is not None:
            k_expanded_u = float(coverage_factor * k_standard_u)
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
        k_statistical_standard_uncertainty=k_statistical_u,
        k_standard_uncertainty=k_standard_u,
        k_expanded_uncertainty=k_expanded_u,
        coverage_factor=coverage_factor if k_standard_u is not None else None,
    )
