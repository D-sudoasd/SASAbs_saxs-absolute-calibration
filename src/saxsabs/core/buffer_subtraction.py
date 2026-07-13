"""Buffer / solvent subtraction for solution SAXS.

Implements the standard BioSAXS subtraction formula with error propagation:

    I_sub(q)  = I_sample(q) − α × I_buffer(q)
    σ_sub²(q) = σ_sample²(q) + α² × σ_buffer²(q)
                + I_buffer²(q) × σ_alpha²

Reference
---------
Jacques, D.A. & Trewhella, J. (2010).  *Protein Science* **19**, 642–657.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BufferSubtractionResult:
    """Container for buffer-subtracted SAXS data.

    Attributes
    ----------
    q : np.ndarray
        Momentum-transfer values (Å⁻¹).
    i_subtracted : np.ndarray
        Subtracted intensity (cm⁻¹ or relative).
    err_subtracted : np.ndarray
        Propagated uncertainty.
    alpha : float
        Scaling factor applied to the buffer curve.
    high_q_residual_mean : float
        Mean intensity in the high-*q* diagnostic window (should be ≈0).
    high_q_check_passed : bool
        *True* if |mean| < 3 × σ in the diagnostic window.
    alpha_uncertainty : float | None
        Standard uncertainty of α, when supplied.
    """

    q: np.ndarray
    i_subtracted: np.ndarray
    err_subtracted: np.ndarray
    alpha: float
    high_q_residual_mean: float = 0.0
    high_q_check_passed: bool = True
    alpha_uncertainty: float | None = None


def _as_1d_float_array(name: str, values: np.ndarray | None, *, require_finite: bool = True) -> np.ndarray:
    if values is None:
        raise ValueError(f"{name} is required")
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a 1-D array")
    if require_finite and not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains non-finite values")
    return arr


def _prepare_source_grid(
    q_source: np.ndarray,
    y_source: np.ndarray,
    *,
    label: str,
) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(q_source)
    q_sorted = q_source[order]
    y_sorted = y_source[order]
    uq, inv = np.unique(q_sorted, return_inverse=True)
    if uq.size < 2:
        raise ValueError(f"{label} q grid must contain at least 2 unique points")
    if uq.size != q_sorted.size:
        y_sum = np.zeros_like(uq, dtype=np.float64)
        counts = np.zeros_like(uq, dtype=np.float64)
        for idx, group in enumerate(inv):
            y_sum[group] += y_sorted[idx]
            counts[group] += 1.0
        y_sorted = y_sum / np.clip(counts, 1.0, None)
        q_sorted = uq
    return q_sorted, y_sorted


def _interpolate_on_grid(
    q_target: np.ndarray,
    q_source: np.ndarray,
    y_source: np.ndarray,
    *,
    label: str,
) -> np.ndarray:
    q_src, y_src = _prepare_source_grid(q_source, y_source, label=label)
    tol = max(1e-12, 1e-9 * max(abs(q_src[0]), abs(q_src[-1]), abs(q_target).max(initial=0.0)))
    if np.min(q_target) < q_src[0] - tol or np.max(q_target) > q_src[-1] + tol:
        raise ValueError(
            f"sample q grid extends outside {label} q range "
            f"({q_src[0]:.6g} to {q_src[-1]:.6g})"
        )
    return np.interp(q_target, q_src, y_src)


def _prepare_variance_grid(
    q_source: np.ndarray,
    sigma_source: np.ndarray,
    *,
    label: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Return sorted q and variance of an averaged source profile.

    Duplicate source points are treated as independent observations of their
    mean.  Any unknown input uncertainty keeps the corresponding mean
    uncertainty unknown rather than silently contributing zero variance.
    """
    order = np.argsort(q_source)
    q_sorted = q_source[order]
    variance_sorted = np.square(sigma_source[order])
    uq, inv = np.unique(q_sorted, return_inverse=True)
    if uq.size < 2:
        raise ValueError(f"{label} q grid must contain at least 2 unique points")
    if uq.size == q_sorted.size:
        return q_sorted, variance_sorted

    variance_of_mean = np.full(uq.shape, np.nan, dtype=np.float64)
    for group in range(uq.size):
        group_variance = variance_sorted[inv == group]
        if np.all(np.isfinite(group_variance)):
            variance_of_mean[group] = float(group_variance.sum() / group_variance.size**2)
    return uq, variance_of_mean


def _interpolate_variance_on_grid(
    q_target: np.ndarray,
    q_source: np.ndarray,
    sigma_source: np.ndarray,
    *,
    label: str,
) -> np.ndarray:
    """Propagate independent endpoint variances through linear interpolation."""
    q_src, variance_src = _prepare_variance_grid(q_source, sigma_source, label=label)
    tol = max(1e-12, 1e-9 * max(abs(q_src[0]), abs(q_src[-1]), abs(q_target).max(initial=0.0)))
    if np.min(q_target) < q_src[0] - tol or np.max(q_target) > q_src[-1] + tol:
        raise ValueError(
            f"sample q grid extends outside {label} q range "
            f"({q_src[0]:.6g} to {q_src[-1]:.6g})"
        )

    upper = np.searchsorted(q_src, q_target, side="right")
    upper = np.clip(upper, 1, q_src.size - 1)
    lower = upper - 1
    span = q_src[upper] - q_src[lower]
    weight_upper = (q_target - q_src[lower]) / span
    weight_upper = np.clip(weight_upper, 0.0, 1.0)
    weight_lower = 1.0 - weight_upper

    out = np.full(q_target.shape, np.nan, dtype=np.float64)
    exact_lower = np.isclose(weight_upper, 0.0, rtol=0.0, atol=1e-14)
    exact_upper = np.isclose(weight_upper, 1.0, rtol=0.0, atol=1e-14)
    between = ~(exact_lower | exact_upper)
    out[exact_lower] = variance_src[lower[exact_lower]]
    out[exact_upper] = variance_src[upper[exact_upper]]
    known = between & np.isfinite(variance_src[lower]) & np.isfinite(variance_src[upper])
    out[known] = (
        np.square(weight_lower[known]) * variance_src[lower[known]]
        + np.square(weight_upper[known]) * variance_src[upper[known]]
    )
    return out


def validate_alpha(alpha: float) -> None:
    """Validate α and warn if it is far from 1.0."""
    if not np.isfinite(alpha) or alpha <= 0:
        raise ValueError("Buffer scaling factor alpha must be finite and > 0")
    if alpha < 0.8 or alpha > 1.2:
        logger.warning(
            "Buffer scaling factor α = %.4f is far from 1.0; "
            "this usually indicates an experimental problem "
            "(e.g. capillary mismatch, concentration error).",
            alpha,
        )


def subtract_buffer(
    q_sample: np.ndarray,
    i_sample: np.ndarray,
    err_sample: np.ndarray | None,
    q_buffer: np.ndarray,
    i_buffer: np.ndarray,
    err_buffer: np.ndarray | None,
    alpha: float = 1.0,
    alpha_uncertainty: float | None = None,
    high_q_diag: tuple[float, float] = (0.15, 0.25),
) -> BufferSubtractionResult:
    """Subtract a buffer/solvent curve from a sample curve.

    If the buffer is on a different *q*-grid it is linearly interpolated onto
    the sample grid.

    Parameters
    ----------
    q_sample, i_sample, err_sample
        Sample scattering profile.  Missing errors remain unknown (NaN).
    q_buffer, i_buffer, err_buffer
        Buffer scattering profile.
    alpha : float
        Scaling factor for the buffer (default 1.0).
    alpha_uncertainty : float | None
        Standard uncertainty of α.  ``None`` means unknown and therefore
        keeps the combined uncertainty unknown.  Pass ``0.0`` only when α is
        explicitly treated as exact.
    high_q_diag : tuple[float, float]
        *q* window for the high-*q* residual check.

    Returns
    -------
    BufferSubtractionResult
    """
    validate_alpha(alpha)
    if alpha_uncertainty is not None:
        alpha_uncertainty = float(alpha_uncertainty)
        if not np.isfinite(alpha_uncertainty) or alpha_uncertainty < 0:
            raise ValueError("alpha_uncertainty must be finite and >= 0")

    q_s = _as_1d_float_array("q_sample", q_sample)
    i_s = _as_1d_float_array("i_sample", i_sample)
    if q_s.shape != i_s.shape:
        raise ValueError("q_sample and i_sample shape mismatch")
    e_s = (
        _as_1d_float_array("err_sample", err_sample, require_finite=False)
        if err_sample is not None
        else np.full_like(i_s, np.nan)
    )
    if e_s.shape != i_s.shape:
        raise ValueError("err_sample shape mismatch")
    if np.any(np.isfinite(e_s) & (e_s < 0)):
        raise ValueError("err_sample contains negative values")
    e_s = np.where(np.isfinite(e_s), e_s, np.nan)

    q_b = _as_1d_float_array("q_buffer", q_buffer)
    i_b = _as_1d_float_array("i_buffer", i_buffer)
    if q_b.shape != i_b.shape:
        raise ValueError("q_buffer and i_buffer shape mismatch")
    e_b = (
        _as_1d_float_array("err_buffer", err_buffer, require_finite=False)
        if err_buffer is not None
        else np.full_like(i_b, np.nan)
    )
    if e_b.shape != i_b.shape:
        raise ValueError("err_buffer shape mismatch")
    if np.any(np.isfinite(e_b) & (e_b < 0)):
        raise ValueError("err_buffer contains negative values")
    e_b = np.where(np.isfinite(e_b), e_b, np.nan)

    # Interpolate buffer onto sample q-grid if grids differ
    if q_s.shape != q_b.shape or not np.allclose(q_s, q_b, rtol=0.0, atol=1e-8):
        i_b = _interpolate_on_grid(q_s, q_b, i_b, label="buffer")
        buffer_variance = _interpolate_variance_on_grid(
            q_s, q_b, e_b, label="buffer uncertainty"
        )
    else:
        buffer_variance = np.square(e_b)

    # Subtraction
    i_sub = i_s - alpha * i_b

    # Unknown input errors intentionally yield NaN, never an optimistic partial budget.
    variance_sub = np.square(e_s) + alpha**2 * buffer_variance
    if alpha_uncertainty is None:
        variance_sub = variance_sub + np.full_like(i_b, np.nan)
    else:
        variance_sub = variance_sub + np.square(i_b * alpha_uncertainty)
    err_sub = np.sqrt(variance_sub)

    # High-q diagnostic
    q_lo, q_hi = high_q_diag
    mask = (q_s >= q_lo) & (q_s <= q_hi) & np.isfinite(i_sub)
    if mask.sum() >= 3:
        residual_mean = float(np.mean(i_sub[mask]))
        residual_std = float(np.std(i_sub[mask]))
        check_ok = abs(residual_mean) < 3.0 * max(residual_std, 1e-30)
    else:
        residual_mean = 0.0
        check_ok = True  # not enough points for diagnostic

    return BufferSubtractionResult(
        q=q_s,
        i_subtracted=i_sub,
        err_subtracted=err_sub,
        alpha=alpha,
        high_q_residual_mean=residual_mean,
        high_q_check_passed=check_ok,
        alpha_uncertainty=alpha_uncertainty,
    )
