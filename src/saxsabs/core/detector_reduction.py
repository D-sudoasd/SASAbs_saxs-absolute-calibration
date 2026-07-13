"""Shared detector-space reduction primitives for absolute SAXS calibration.

The functions in this module implement the NIST SRM 3600 blank-subtraction
convention for detector frames containing integrated counts.  The electronic
dark is exposure matched before any monitor or transmission normalization.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .normalization import compute_norm_factor


@dataclass(frozen=True)
class NormalizedDetectorFrame:
    """An exposure-matched, normalized detector frame."""

    image: np.ndarray
    normalization_factor: float
    dark_scale: float


@dataclass(frozen=True)
class NetDetectorImage:
    """A NIST-convention sample-minus-blank detector image."""

    image: np.ndarray
    norm_sample: float
    norm_background: float
    dark_scale_sample: float
    dark_scale_background: float
    alpha: float


def _positive_finite(name: str, value: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a real number") from exc
    if not math.isfinite(out) or out <= 0:
        raise ValueError(f"{name} must be finite and > 0")
    return out


def validate_blank_transmission(
    transmission: float | None,
    *,
    tolerance: float = 0.02,
) -> float:
    """Require a NIST empty-beam/blank transmission consistent with unity."""
    tol = _positive_finite("blank transmission tolerance", tolerance)
    if transmission is None:
        raise ValueError("blank transmission is required and must be close to 1")
    try:
        value = float(transmission)
    except (TypeError, ValueError) as exc:
        raise ValueError("blank transmission must be finite and close to 1") from exc
    if not math.isfinite(value) or value <= 0 or abs(value - 1.0) > tol:
        raise ValueError(
            "blank transmission must be close to 1 under the NIST blank convention "
            f"(got {transmission!r}, tolerance={tol:g})"
        )
    return value


def normalize_detector_frame(
    image: np.ndarray,
    dark: np.ndarray,
    *,
    image_exposure_s: float,
    dark_exposure_s: float,
    monitor: float,
    transmission: float,
    monitor_mode: str,
) -> NormalizedDetectorFrame:
    """Exposure-match dark counts and normalize an integrated detector frame."""
    image_arr = np.asarray(image, dtype=np.float64)
    dark_arr = np.asarray(dark, dtype=np.float64)
    if image_arr.shape != dark_arr.shape:
        raise ValueError(f"dark shape mismatch: {dark_arr.shape} vs {image_arr.shape}")
    if not np.all(np.isfinite(image_arr)):
        raise ValueError("detector image contains non-finite values")
    if not np.all(np.isfinite(dark_arr)):
        raise ValueError("dark image contains non-finite values")

    image_exp = _positive_finite("image_exposure_s", image_exposure_s)
    dark_exp = _positive_finite("dark_exposure_s", dark_exposure_s)
    dark_scale = image_exp / dark_exp
    norm = compute_norm_factor(image_exp, monitor, transmission, monitor_mode)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("detector normalization factor must be finite and > 0")

    return NormalizedDetectorFrame(
        image=(image_arr - dark_arr * dark_scale) / norm,
        normalization_factor=float(norm),
        dark_scale=float(dark_scale),
    )


def build_nist_net_image(
    sample: np.ndarray,
    background: np.ndarray,
    dark: np.ndarray,
    *,
    sample_exposure_s: float,
    background_exposure_s: float,
    dark_exposure_s: float,
    sample_monitor: float,
    background_monitor: float,
    sample_transmission: float,
    monitor_mode: str,
    alpha: float = 1.0,
) -> NetDetectorImage:
    """Build ``sample/(I0*T) - alpha*blank/I0`` in detector space.

    The background is the no-sample NIST blank, so it is deliberately
    normalized with transmission equal to one rather than with a separate
    ``T_bg`` value.
    """
    alpha_value = _positive_finite("alpha", alpha)
    sample_frame = normalize_detector_frame(
        sample,
        dark,
        image_exposure_s=sample_exposure_s,
        dark_exposure_s=dark_exposure_s,
        monitor=sample_monitor,
        transmission=sample_transmission,
        monitor_mode=monitor_mode,
    )
    background_frame = normalize_detector_frame(
        background,
        dark,
        image_exposure_s=background_exposure_s,
        dark_exposure_s=dark_exposure_s,
        monitor=background_monitor,
        transmission=1.0,
        monitor_mode=monitor_mode,
    )
    return NetDetectorImage(
        image=sample_frame.image - alpha_value * background_frame.image,
        norm_sample=sample_frame.normalization_factor,
        norm_background=background_frame.normalization_factor,
        dark_scale_sample=sample_frame.dark_scale,
        dark_scale_background=background_frame.dark_scale,
        alpha=alpha_value,
    )
