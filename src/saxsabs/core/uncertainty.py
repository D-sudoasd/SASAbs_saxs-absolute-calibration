"""Uncertainty propagation for absolute SAXS intensities.

The functions in this module distinguish known-zero contributions from unknown
ones.  Callers must pass ``0.0`` for a source known to be inapplicable; leaving
a source as ``None`` records it as unknown and therefore keeps the combined
uncertainty unknown.  Components are combined only under the stated assumption
that they are independent standard uncertainties.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AbsoluteUncertaintyBudget:
    """Absolute standard-uncertainty components on the calibrated intensity scale."""

    statistical: np.ndarray
    k: np.ndarray
    standard: np.ndarray
    transmission: np.ndarray
    monitor: np.ndarray
    thickness: np.ndarray
    mu: np.ndarray
    alpha: np.ndarray
    combined_standard_uncertainty: np.ndarray
    expanded_uncertainty: np.ndarray
    coverage_factor: float | None
    unknown_components: tuple[str, ...]


def _broadcast_uncertainty(
    name: str,
    value: float | np.ndarray,
    shape: tuple[int, ...],
) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    try:
        out = np.broadcast_to(arr, shape).astype(np.float64, copy=True)
    except ValueError as exc:
        raise ValueError(f"{name} is not broadcastable to intensity shape {shape}") from exc
    if np.any(np.isinf(out)) or np.any(np.isfinite(out) & (out < 0)):
        raise ValueError(f"{name} must not contain infinities or negative values")
    return out


def propagate_absolute_uncertainty(
    intensity: np.ndarray,
    *,
    statistical_standard_uncertainty: float | np.ndarray | None = None,
    k_relative_standard_uncertainty: float | np.ndarray | None = None,
    standard_relative_standard_uncertainty: float | np.ndarray | None = None,
    transmission_relative_standard_uncertainty: float | np.ndarray | None = None,
    monitor_relative_standard_uncertainty: float | np.ndarray | None = None,
    thickness_relative_standard_uncertainty: float | np.ndarray | None = None,
    mu_relative_standard_uncertainty: float | np.ndarray | None = None,
    alpha_standard_uncertainty: float | np.ndarray | None = None,
    buffer_intensity: np.ndarray | None = None,
    coverage_factor: float | None = 2.0,
) -> AbsoluteUncertaintyBudget:
    """Build and combine an absolute-intensity uncertainty budget.

    Statistical uncertainty is supplied in the same absolute units as
    ``intensity``.  K, reference-standard, transmission, monitor, thickness,
    and attenuation-coefficient (μ) inputs are relative standard
    uncertainties.  The α contribution is ``|I_buffer| u(alpha)``.

    Every named source is explicit.  ``None`` means unknown and produces NaN
    for that component and the combined result.  Use ``0.0`` only when a source
    is known to be exact or not applicable.
    """
    intensity_arr = np.asarray(intensity, dtype=np.float64)
    if intensity_arr.ndim == 0:
        intensity_arr = intensity_arr.reshape(1)
    if not np.all(np.isfinite(intensity_arr)):
        raise ValueError("intensity must contain only finite values")
    shape = intensity_arr.shape
    magnitude = np.abs(intensity_arr)

    unknown: list[str] = []

    def absolute_component(
        name: str,
        value: float | np.ndarray | None,
    ) -> np.ndarray:
        if value is None:
            unknown.append(name)
            return np.full(shape, np.nan, dtype=np.float64)
        component = _broadcast_uncertainty(
            f"{name}_standard_uncertainty", value, shape
        )
        if np.any(np.isnan(component)):
            unknown.append(name)
        return component

    def relative_component(
        name: str,
        value: float | np.ndarray | None,
    ) -> np.ndarray:
        if value is None:
            unknown.append(name)
            return np.full(shape, np.nan, dtype=np.float64)
        relative = _broadcast_uncertainty(
            f"{name}_relative_standard_uncertainty", value, shape
        )
        if np.any(np.isnan(relative)):
            unknown.append(name)
        return magnitude * relative

    statistical = absolute_component("statistical", statistical_standard_uncertainty)
    k_component = relative_component("k", k_relative_standard_uncertainty)
    standard = relative_component("standard", standard_relative_standard_uncertainty)
    transmission = relative_component(
        "transmission", transmission_relative_standard_uncertainty
    )
    monitor = relative_component("monitor", monitor_relative_standard_uncertainty)
    thickness = relative_component("thickness", thickness_relative_standard_uncertainty)
    mu = relative_component("mu", mu_relative_standard_uncertainty)

    if alpha_standard_uncertainty is None:
        unknown.append("alpha")
        alpha = np.full(shape, np.nan, dtype=np.float64)
    else:
        alpha_u = _broadcast_uncertainty(
            "alpha_standard_uncertainty", alpha_standard_uncertainty, shape
        )
        if np.any(np.isnan(alpha_u)):
            unknown.append("alpha")
        if np.any(alpha_u > 0):
            if buffer_intensity is None:
                raise ValueError(
                    "buffer_intensity is required when alpha_standard_uncertainty is non-zero"
                )
            buffer_arr = np.asarray(buffer_intensity, dtype=np.float64)
            try:
                buffer_arr = np.broadcast_to(buffer_arr, shape).astype(np.float64, copy=True)
            except ValueError as exc:
                raise ValueError(
                    f"buffer_intensity is not broadcastable to intensity shape {shape}"
                ) from exc
            if not np.all(np.isfinite(buffer_arr)):
                raise ValueError("buffer_intensity must contain only finite values")
            alpha = np.abs(buffer_arr) * alpha_u
        else:
            alpha = alpha_u.copy()

    components = (
        statistical,
        k_component,
        standard,
        transmission,
        monitor,
        thickness,
        mu,
        alpha,
    )
    combined = np.sqrt(np.sum([np.square(component) for component in components], axis=0))

    if coverage_factor is None:
        expanded = np.full(shape, np.nan, dtype=np.float64)
    else:
        coverage_factor = float(coverage_factor)
        if not np.isfinite(coverage_factor) or coverage_factor <= 0:
            raise ValueError("coverage_factor must be finite and > 0")
        expanded = combined * coverage_factor

    return AbsoluteUncertaintyBudget(
        statistical=statistical,
        k=k_component,
        standard=standard,
        transmission=transmission,
        monitor=monitor,
        thickness=thickness,
        mu=mu,
        alpha=alpha,
        combined_standard_uncertainty=combined,
        expanded_uncertainty=expanded,
        coverage_factor=coverage_factor,
        unknown_components=tuple(unknown),
    )
