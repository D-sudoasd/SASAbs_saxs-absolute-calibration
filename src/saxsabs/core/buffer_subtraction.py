"""Buffer / solvent subtraction for solution SAXS.

Implements the standard BioSAXS subtraction formula with error propagation:

    I_sub(q)  = I_sample(q) − α × I_buffer(q)
    σ_sub²(q) = σ_sample²(q) + α² × σ_buffer²(q)

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
    """

    q: np.ndarray
    i_subtracted: np.ndarray
    err_subtracted: np.ndarray
    alpha: float
    high_q_residual_mean: float = 0.0
    high_q_check_passed: bool = True


def validate_alpha(alpha: float) -> None:
    """Warn if α is far from 1.0 (usually indicates experimental issues)."""
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
    high_q_diag: tuple[float, float] = (0.15, 0.25),
) -> BufferSubtractionResult:
    """Subtract a buffer/solvent curve from a sample curve.

    If the buffer is on a different *q*-grid it is linearly interpolated onto
    the sample grid.

    Parameters
    ----------
    q_sample, i_sample, err_sample
        Sample scattering profile (err may be *None* → zeros).
    q_buffer, i_buffer, err_buffer
        Buffer scattering profile.
    alpha : float
        Scaling factor for the buffer (default 1.0).
    high_q_diag : tuple[float, float]
        *q* window for the high-*q* residual check.

    Returns
    -------
    BufferSubtractionResult
    """
    validate_alpha(alpha)

    q_s = np.asarray(q_sample, dtype=np.float64)
    i_s = np.asarray(i_sample, dtype=np.float64)
    e_s = (
        np.asarray(err_sample, dtype=np.float64)
        if err_sample is not None
        else np.zeros_like(i_s)
    )
    q_b = np.asarray(q_buffer, dtype=np.float64)
    i_b = np.asarray(i_buffer, dtype=np.float64)
    e_b = (
        np.asarray(err_buffer, dtype=np.float64)
        if err_buffer is not None
        else np.zeros_like(i_b)
    )

    # Interpolate buffer onto sample q-grid if grids differ
    if q_s.shape != q_b.shape or not np.allclose(q_s, q_b, atol=1e-8):
        i_b = np.interp(q_s, q_b, i_b)
        e_b = np.interp(q_s, q_b, e_b)

    # Subtraction
    i_sub = i_s - alpha * i_b

    # Error propagation:  σ² = σ_s² + α² × σ_b²
    err_sub = np.sqrt(e_s ** 2 + (alpha * e_b) ** 2)

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
    )
