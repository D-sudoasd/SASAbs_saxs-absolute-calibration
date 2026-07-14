"""BL19B2 detector-space absolute 2D batch correction workflow.

This module is intentionally separate from the GUI.  It implements a
configuration-driven batch path for the Spring-8 BL19B2 TIFF layout used in
``dat001`` while preserving the original data tree as read-only input.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import importlib.metadata as importlib_metadata
import json
import math
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import numpy as np

from saxsabs.core.calibration import estimate_k_factor_robust
from saxsabs.core.calibration_context import normalize_standard_key
from saxsabs.core.detector_reduction import normalize_detector_frame, validate_blank_transmission
from saxsabs.core.normalization import compute_norm_factor as _core_compute_norm_factor
from saxsabs.core.uncertainty import AbsoluteUncertaintyBudget, propagate_absolute_uncertainty
from saxsabs.constants import get_reference_data


SCHEMA_VERSION = "saxsabs.bl19b2_abs2d.v4"
FORMULA_VERSION = "v3_monitor_mode_background_i0_only"
INTENSITY_UNIT = "cm^-1"
UNCERTAINTY_MASK_POLICY = "masked_pixels_zeroed_excluded_from_summaries_v1"
SRM3600_THICKNESS_CM = 0.1055
BACKGROUND_TRANSMISSION_TOLERANCE = 0.02
DEFAULT_MAX_BEER_LAMBERT_TRANSMISSION = 0.999
DEFAULT_MIN_BEER_LAMBERT_TRANSMISSION = 0.001
INSTRUMENT_RELATIVE_TOLERANCE = 0.005
BEAM_CENTER_TOLERANCE_PX = 1.0
EXCLUDED_SAMPLE_PARTS = {"reference_saxs", "csv_output", "sum", "test"}
EXCLUDED_PREFIXES = ("processed_",)


@dataclass(frozen=True)
class BL19B2Header:
    exposure_s: float | None = None
    monitor: float | None = None
    transmission: float | None = None
    energy_kev: float | None = None
    distance_mm: float | None = None
    beam_x_px: float | None = None
    beam_y_px: float | None = None
    pixel_size_m: float | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FrameClassification:
    status: str
    reason: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputPaths:
    h5: Path
    edf: Path
    metadata: Path
    preview: Path


@dataclass(frozen=True)
class ReferencePaths:
    dark: Path
    background: Path
    standard: Path
    direct: Path | None = None
    mask: Path | None = None


class SourceChangedDuringReadError(RuntimeError):
    """Raised when a detector source is not stable across one logical read."""


@dataclass(frozen=True)
class DetectorSourceSnapshot:
    """Pixels, header, and identity captured from the same stable source state."""

    path: Path
    image: np.ndarray
    header: BL19B2Header
    identity: dict[str, Any]


@dataclass(frozen=True)
class PydidasCalibration:
    source_path: Path
    detector_name: str
    distance_m: float
    poni1_m: float
    poni2_m: float
    pixel1_m: float
    pixel2_m: float
    rot1: float
    rot2: float
    rot3: float
    wavelength_m: float
    mask_path: Path | None = None


@dataclass(frozen=True)
class BL19B2Abs2DConfig:
    input_root: Path
    poni_path: Path | None = None
    pydidas_cali_yaml: Path | None = None
    mask_path: Path | None = None
    dark_path: Path | None = None
    background_path: Path | None = None
    standard_path: Path | None = None
    direct_path: Path | None = None
    output_root: Path | None = None
    mu_cm_inv: float | None = None
    sample_thickness_cm: float | None = None
    monitor_mode: str | None = None
    transmission_abs_uncertainty: float | None = None
    monitor_relative_standard_uncertainty: float | None = None
    sample_thickness_relative_standard_uncertainty: float | None = None
    standard_thickness_relative_standard_uncertainty: float | None = None

    mu_relative_standard_uncertainty: float | None = None
    alpha_standard_uncertainty: float | None = None
    alpha: float = 1.0
    q_window: tuple[float, float] = (0.01, 0.2)
    npt: int = 1000
    dtype: str = "float32"
    dry_run: bool = False
    max_frames: int | None = None
    overwrite: bool = False
    write_preview: bool = True
    standard_thickness_cm: float | None = None
    standard_key: str = "SRM3600"
    correct_solid_angle_for_k: bool = True
    polarization_factor: float | None = None
    dark_hot_pixel_threshold: float = 10.0
    standard_transmission_abs_uncertainty: float | None = None
    standard_monitor_relative_standard_uncertainty: float | None = None
    calibration_background_monitor_relative_standard_uncertainty: float | None = None
    system_coverage_factor: float | None = None
    include_manifest_path: Path | None = None
    thickness_derivation_path: Path | None = None
    def resolved_output_root(self) -> Path:
        if self.output_root is not None:
            return Path(self.output_root)
        return Path(self.input_root).parent / f"{Path(self.input_root).name}_absolute_corrected_2D"


@dataclass(frozen=True)
class StandardCalibration:
    k_factor: float
    k_std: float
    q_min_overlap: float
    q_max_overlap: float
    points_used: int
    points_total: int
    standard_thickness_cm: float
    norm_standard: float
    norm_background: float
    bg_transmission_used: float
    standard_thickness_source: str
    warnings: tuple[str, ...] = ()
    k_statistical_standard_uncertainty: float | None = None
    k_standard_uncertainty: float | None = None
    k_expanded_uncertainty: float | None = None
    coverage_factor: float | None = None
    reference_coverage_factor: float | None = None
    uncertainty_status: str = "partial"
    expanded_uncertainty_status: str = "unavailable"
    k_independent_standard_uncertainty: float | None = None
    k_alpha_relative_sensitivity: float | None = None
    k_calibration_background_monitor_relative_sensitivity: float | None = None
    uncertainty_components: dict[str, float | None] = field(default_factory=dict)
    uncertainty_unknown_components: tuple[str, ...] = ()
    parallelism_max_relative_deviation: float | None = None
    parallelism_relative_tolerance: float | None = None
    parallelism_check_passed: bool | None = None


K_STD_SEMANTICS = "inlier ratio scatter; not combined K uncertainty"
_K_CALIBRATION_KEYS = (
    "k_factor",
    "k_std",
    "k_std_semantics",
    "k_statistical_standard_uncertainty",
    "k_standard_uncertainty",
    "k_expanded_uncertainty",
    "coverage_factor",
    "reference_coverage_factor",
    "uncertainty_status",
    "expanded_uncertainty_status",
    "k_independent_standard_uncertainty",
    "k_alpha_relative_sensitivity",
    "k_calibration_background_monitor_relative_sensitivity",
    "uncertainty_components",
    "uncertainty_unknown_components",
    "parallelism_max_relative_deviation",
    "parallelism_relative_tolerance",
    "parallelism_check_passed",
)
_UNCERTAINTY_DATASETS = {
    "statistical": "statistical",
    "k": "k",
    "standard": "standard",
    "transmission": "transmission",
    "monitor": "monitor",
    "thickness": "thickness",
    "mu": "mu",
    "alpha": "alpha",
    "combined_standard": "combined_standard_uncertainty",
    "expanded": "expanded_uncertainty",
}


def _k_calibration_contract(
    calibration: StandardCalibration | dict[str, Any],
    *,
    require_complete: bool = False,
) -> dict[str, Any]:
    if isinstance(calibration, StandardCalibration):
        payload = {
            "k_factor": calibration.k_factor,
            "k_std": calibration.k_std,
            "k_std_semantics": K_STD_SEMANTICS,
            "k_statistical_standard_uncertainty": (
                calibration.k_statistical_standard_uncertainty
            ),
            "k_standard_uncertainty": calibration.k_standard_uncertainty,
            "k_expanded_uncertainty": calibration.k_expanded_uncertainty,
            "coverage_factor": calibration.coverage_factor,
            "reference_coverage_factor": calibration.reference_coverage_factor,
            "uncertainty_status": calibration.uncertainty_status,
            "expanded_uncertainty_status": calibration.expanded_uncertainty_status,
            "k_independent_standard_uncertainty": calibration.k_independent_standard_uncertainty,
            "k_alpha_relative_sensitivity": calibration.k_alpha_relative_sensitivity,
            "k_calibration_background_monitor_relative_sensitivity": (
                calibration.k_calibration_background_monitor_relative_sensitivity
            ),
            "uncertainty_components": calibration.uncertainty_components,
            "uncertainty_unknown_components": list(calibration.uncertainty_unknown_components),
            "parallelism_max_relative_deviation": (
                calibration.parallelism_max_relative_deviation
            ),
            "parallelism_relative_tolerance": calibration.parallelism_relative_tolerance,
            "parallelism_check_passed": calibration.parallelism_check_passed,
        }
    else:
        payload = {key: calibration.get(key) for key in _K_CALIBRATION_KEYS}
    if require_complete:
        missing = (
            []
            if isinstance(calibration, StandardCalibration)
            else [key for key in _K_CALIBRATION_KEYS if key not in calibration]
        )
        required_values = (
            "k_factor",
            "k_std",
            "k_std_semantics",
            "k_statistical_standard_uncertainty",
        )
        missing.extend(key for key in required_values if payload.get(key) is None)
        if missing:
            raise ValueError("incomplete K calibration uncertainty contract: " + ", ".join(missing))
        if payload["k_std_semantics"] != K_STD_SEMANTICS:
            raise ValueError("unexpected k_std semantics in K calibration contract")
        numeric_rules = {
            "k_factor": True,
            "k_std": False,
            "k_statistical_standard_uncertainty": False,
            "k_standard_uncertainty": False,
            "k_expanded_uncertainty": False,
            "coverage_factor": True,
            "reference_coverage_factor": True,
            "k_independent_standard_uncertainty": False,
        }
        for key, strictly_positive in numeric_rules.items():
            value = payload[key]
            if value is None:
                continue
            numeric = float(value)
            if not math.isfinite(numeric) or (numeric <= 0 if strictly_positive else numeric < 0):
                comparison = "> 0" if strictly_positive else ">= 0"
                raise ValueError(f"{key} must be finite and {comparison}")
        for key in (
            "k_alpha_relative_sensitivity",
            "k_calibration_background_monitor_relative_sensitivity",
        ):
            value = payload[key]
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{key} must be finite")

        uncertainty_status = payload["uncertainty_status"]
        if uncertainty_status not in {"complete", "partial"}:
            raise ValueError("uncertainty_status must be 'complete' or 'partial'")
        expanded_status = payload["expanded_uncertainty_status"]
        if expanded_status not in {"available", "unavailable"}:
            raise ValueError(
                "expanded_uncertainty_status must be 'available' or 'unavailable'"
            )

        components = payload["uncertainty_components"]
        if not isinstance(components, dict):
            raise ValueError("uncertainty_components must be a mapping")
        for name, value in components.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("uncertainty_components keys must be non-empty strings")
            if value is None:
                continue
            if isinstance(value, (bool, np.bool_)):
                raise ValueError(
                    f"uncertainty_components.{name} must be finite and >= 0 or null"
                )
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"uncertainty_components.{name} must be finite and >= 0 or null"
                ) from exc
            if not math.isfinite(numeric) or numeric < 0:
                raise ValueError(
                    f"uncertainty_components.{name} must be finite and >= 0 or null"
                )

        unknown_components = payload["uncertainty_unknown_components"]
        if not isinstance(unknown_components, (list, tuple)):
            raise ValueError("uncertainty_unknown_components must be a list of strings")
        if any(
            not isinstance(name, str) or not name.strip()
            for name in unknown_components
        ):
            raise ValueError(
                "uncertainty_unknown_components must contain non-empty strings"
            )
        if len(set(unknown_components)) != len(unknown_components):
            raise ValueError("uncertainty_unknown_components must not contain duplicates")

        parallelism_max = payload["parallelism_max_relative_deviation"]
        parallelism_tolerance = payload["parallelism_relative_tolerance"]
        for key, value, strictly_positive in (
            ("parallelism_max_relative_deviation", parallelism_max, False),
            ("parallelism_relative_tolerance", parallelism_tolerance, True),
        ):
            if value is None:
                continue
            if isinstance(value, (bool, np.bool_)):
                raise ValueError(f"{key} must be a finite numeric value")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be a finite numeric value") from exc
            if not math.isfinite(numeric) or (
                numeric <= 0 if strictly_positive else numeric < 0
            ):
                comparison = "> 0" if strictly_positive else ">= 0"
                raise ValueError(f"{key} must be finite and {comparison}")
        if (parallelism_max is None) != (parallelism_tolerance is None):
            raise ValueError(
                "parallelism_max_relative_deviation and "
                "parallelism_relative_tolerance must be provided together"
            )
        parallelism_passed = payload["parallelism_check_passed"]
        if parallelism_passed is not None and not isinstance(
            parallelism_passed, (bool, np.bool_)
        ):
            raise ValueError("parallelism_check_passed must be boolean or null")
        if parallelism_passed is not None:
            if parallelism_max is None or parallelism_tolerance is None:
                raise ValueError(
                    "parallelism_check_passed requires both parallelism metrics"
                )
            expected_passed = float(parallelism_max) <= float(parallelism_tolerance)
            if bool(parallelism_passed) is not expected_passed:
                raise ValueError(
                    "parallelism_check_passed is inconsistent with the recorded metrics"
                )
    return _json_safe(payload)


def _uncertainty_input_payload(config: BL19B2Abs2DConfig) -> dict[str, float | None]:
    return {
        "transmission_abs_standard_uncertainty": config.transmission_abs_uncertainty,
        "monitor_relative_standard_uncertainty": (
            config.monitor_relative_standard_uncertainty
        ),
        "sample_thickness_relative_standard_uncertainty": (
            config.sample_thickness_relative_standard_uncertainty
        ),
        "standard_thickness_relative_standard_uncertainty": (
            config.standard_thickness_relative_standard_uncertainty
        ),
        "standard_transmission_abs_standard_uncertainty": (
            config.standard_transmission_abs_uncertainty
        ),
        "standard_monitor_relative_standard_uncertainty": (
            config.standard_monitor_relative_standard_uncertainty
        ),
        "calibration_background_monitor_relative_standard_uncertainty": (
            config.calibration_background_monitor_relative_standard_uncertainty
        ),
        "system_coverage_factor": config.system_coverage_factor,
        "mu_relative_standard_uncertainty": config.mu_relative_standard_uncertainty,
        "alpha_standard_uncertainty": config.alpha_standard_uncertainty,
    }


def _standard_side_relative_sensitivities(
    *,
    standard_profile: np.ndarray,
    background_profile: np.ndarray,
    alpha: float,
    standard_transmission: float,
    standard_thickness_cm: float,
    k_factor: float,
    estimate_k_for_profile: Callable[[np.ndarray], float],
) -> dict[str, float]:
    """Differentiate the actual robust K estimator with central differences."""
    standard = np.asarray(standard_profile, dtype=np.float64)
    background = np.asarray(background_profile, dtype=np.float64)
    if standard.shape != background.shape or standard.ndim != 1:
        raise ValueError("standard and background profiles must be matching 1-D arrays")
    if not np.any(np.isfinite(standard) & np.isfinite(background)):
        raise ValueError("standard and background profiles have no jointly finite points")
    alpha_value = float(alpha)
    transmission = float(standard_transmission)
    thickness = float(standard_thickness_cm)
    nominal_k = float(k_factor)
    positive_inputs = {
        "alpha": alpha_value,
        "standard_transmission": transmission,
        "standard_thickness_cm": thickness,
        "k_factor": nominal_k,
    }
    for name, value in positive_inputs.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and > 0")

    def _estimate(profile_per_cm: np.ndarray) -> float:
        value = float(estimate_k_for_profile(np.asarray(profile_per_cm, dtype=np.float64)))
        if not math.isfinite(value) or value <= 0:
            raise ValueError("perturbed robust K estimate must be finite and > 0")
        return value

    net = standard - alpha_value * background
    base_profile = net / thickness
    estimated_nominal_k = _estimate(base_profile)
    if not math.isclose(estimated_nominal_k, nominal_k, rel_tol=1e-10, abs_tol=0.0):
        raise ValueError(
            "uncertainty sensitivity estimator does not reproduce the nominal K factor"
        )

    relative_step = 1e-6

    def _relative_k_derivative(
        plus_profile: np.ndarray,
        minus_profile: np.ndarray,
        input_step: float,
    ) -> float:
        k_plus = _estimate(plus_profile)
        k_minus = _estimate(minus_profile)
        return (k_plus - k_minus) / (2.0 * input_step * nominal_k)

    transmission_step = relative_step * transmission
    alpha_step = relative_step * alpha_value
    return {
        "standard_transmission_per_abs": _relative_k_derivative(
            (
                standard * transmission / (transmission + transmission_step)
                - alpha_value * background
            )
            / thickness,
            (
                standard * transmission / (transmission - transmission_step)
                - alpha_value * background
            )
            / thickness,
            transmission_step,
        ),
        "standard_monitor_per_relative": _relative_k_derivative(
            (standard / (1.0 + relative_step) - alpha_value * background)
            / thickness,
            (standard / (1.0 - relative_step) - alpha_value * background)
            / thickness,
            relative_step,
        ),
        "calibration_background_monitor_per_relative": _relative_k_derivative(
            (standard - alpha_value * background / (1.0 + relative_step))
            / thickness,
            (standard - alpha_value * background / (1.0 - relative_step))
            / thickness,
            relative_step,
        ),
        "standard_thickness_per_relative": _relative_k_derivative(
            net / (thickness * (1.0 + relative_step)),
            net / (thickness * (1.0 - relative_step)),
            relative_step,
        ),
        "alpha_per_abs": _relative_k_derivative(
            (standard - (alpha_value + alpha_step) * background) / thickness,
            (standard - (alpha_value - alpha_step) * background) / thickness,
            alpha_step,
        ),
    }


def _build_standard_uncertainty_contract(
    config: BL19B2Abs2DConfig,
    *,
    k_result: Any,
    standard_profile: np.ndarray,
    background_profile: np.ndarray,
    standard_transmission: float,
    standard_thickness_cm: float,
    estimate_k_for_profile: Callable[[np.ndarray], float] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed standard-side K uncertainty contract."""
    k_value = float(k_result.k_factor)
    k_stat = float(k_result.k_statistical_standard_uncertainty)
    sensitivity_keys = (
        "standard_transmission_per_abs",
        "standard_monitor_per_relative",
        "calibration_background_monitor_per_relative",
        "standard_thickness_per_relative",
        "alpha_per_abs",
    )
    sensitivities: dict[str, float | None]
    if estimate_k_for_profile is None:
        sensitivities = {key: None for key in sensitivity_keys}
    else:
        sensitivities = _standard_side_relative_sensitivities(
            standard_profile=standard_profile,
            background_profile=background_profile,
            alpha=config.alpha,
            standard_transmission=standard_transmission,
            standard_thickness_cm=standard_thickness_cm,
            k_factor=k_value,
            estimate_k_for_profile=estimate_k_for_profile,
        )

    partial_k_u = getattr(k_result, "k_standard_uncertainty", None)
    reference_u = None
    if partial_k_u is not None:
        reference_u = math.sqrt(max(float(partial_k_u) ** 2 - k_stat**2, 0.0))

    inputs = {
        "standard_transmission": config.standard_transmission_abs_uncertainty,
        "standard_monitor": config.standard_monitor_relative_standard_uncertainty,
        "calibration_background_monitor": (
            config.calibration_background_monitor_relative_standard_uncertainty
        ),
        "standard_thickness": config.standard_thickness_relative_standard_uncertainty,
        "alpha": config.alpha_standard_uncertainty,
    }
    unknown = [name for name, value in inputs.items() if value is None]
    if reference_u is None:
        unknown.insert(0, "reference_standard")
    if estimate_k_for_profile is None:
        unknown.append("estimator_consistency")
    unknown.extend(
        (
            "calibration_background_raw_counts_covariance",
            "calibration_dark_raw_counts_covariance",
        )
    )

    def _component(input_name: str, sensitivity_name: str) -> float | None:
        uncertainty = inputs[input_name]
        sensitivity = sensitivities[sensitivity_name]
        if uncertainty is None:
            return None
        uncertainty_value = float(uncertainty)
        if uncertainty_value == 0:
            return 0.0
        if sensitivity is None:
            return None
        return abs(k_value * float(sensitivity)) * uncertainty_value

    components: dict[str, float | None] = {
        "ratio_scatter": k_stat,
        "reference_standard": reference_u,
        "standard_transmission": _component(
            "standard_transmission", "standard_transmission_per_abs"
        ),
        "standard_monitor": _component(
            "standard_monitor", "standard_monitor_per_relative"
        ),
        "calibration_background_monitor": _component(
            "calibration_background_monitor",
            "calibration_background_monitor_per_relative",
        ),
        "standard_thickness": _component(
            "standard_thickness", "standard_thickness_per_relative"
        ),
        "alpha": _component("alpha", "alpha_per_abs"),
    }
    independent_names = (
        "ratio_scatter",
        "reference_standard",
        "standard_transmission",
        "standard_monitor",
        "standard_thickness",
    )
    independent = None
    if all(components[name] is not None for name in independent_names):
        independent = math.sqrt(
            sum(float(components[name]) ** 2 for name in independent_names)
        )
    combined = None
    shared_k_names = ("calibration_background_monitor", "alpha")
    if independent is not None and all(
        components[name] is not None for name in shared_k_names
    ):
        combined = math.sqrt(
            independent**2
            + sum(float(components[name]) ** 2 for name in shared_k_names)
        )

    reference_coverage = getattr(k_result, "reference_coverage_factor", None)
    if reference_coverage is None:
        # Compatibility with pre-v4 estimator results: their coverage factor
        # described the reference certificate and is never reused system-wide.
        reference_coverage = getattr(k_result, "coverage_factor", None)
    return {
        "status": "partial",
        "expanded_status": "unavailable",
        "unknown_components": list(dict.fromkeys(unknown)),
        "components": components,
        "sensitivities": sensitivities,
        "k_independent_standard_uncertainty": independent,
        "k_standard_uncertainty": combined,
        "k_expanded_uncertainty": None,
        "k_alpha_relative_sensitivity": sensitivities["alpha_per_abs"],
        "k_calibration_background_monitor_relative_sensitivity": sensitivities[
            "calibration_background_monitor_per_relative"
        ],
        "reference_coverage_factor": reference_coverage,
        "system_coverage_factor": config.system_coverage_factor,
        "assumptions": {
            "combination": "first_order_with_shared_joint_sensitivities",
            "reference_q_covariance": "unknown_no_averaging_reduction",
            "calibration_background_monitor": "shared_joint_sensitivity",
            "alpha": "shared_joint_sensitivity",
            "shared_background_dark_covariance": "unquantified",
        },
    }

def _uncertainty_array_summary(
    values: np.ndarray,
    *,
    detector_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    arr = np.asarray(values, dtype=np.float64)
    if detector_mask is not None:
        mask = np.asarray(detector_mask, dtype=bool)
        if mask.shape != arr.shape:
            raise ValueError(
                f"detector_mask shape mismatch: {mask.shape} vs {arr.shape}"
            )
        arr = arr[~mask]
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {"status": "unknown", "min": None, "max": None, "mean": None}
    status = "known" if finite.size == arr.size else "partial"
    return {
        "status": status,
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
    }


def _frame_uncertainty_metadata(
    config: BL19B2Abs2DConfig,
    calibration: StandardCalibration,
    budget: AbsoluteUncertaintyBudget,
    *,
    detector_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    inputs = _uncertainty_input_payload(config)
    k_contract = _k_calibration_contract(calibration)
    calibration_unknown = list(calibration.uncertainty_unknown_components)
    unknown: list[str] = []
    for name in budget.unknown_components:
        if name == "standard" and calibration_unknown:
            unknown.extend(calibration_unknown)
        else:
            unknown.append(name)
    unknown.extend(calibration_unknown)
    unknown = list(dict.fromkeys(unknown))

    component_summaries = {
        name: _uncertainty_array_summary(
            getattr(budget, attribute),
            detector_mask=detector_mask,
        )
        for name, attribute in _UNCERTAINTY_DATASETS.items()
        if name not in {"combined_standard", "expanded"}
    }
    valid_pixels = np.ones(budget.combined_standard_uncertainty.shape, dtype=bool)
    if detector_mask is not None:
        mask = np.asarray(detector_mask, dtype=bool)
        if mask.shape != valid_pixels.shape:
            raise ValueError(
                f"detector_mask shape mismatch: {mask.shape} vs {valid_pixels.shape}"
            )
        valid_pixels = ~mask
    has_valid_pixels = bool(np.any(valid_pixels))
    combined_known = has_valid_pixels and bool(
        np.all(np.isfinite(budget.combined_standard_uncertainty[valid_pixels]))
    )
    expanded_known = has_valid_pixels and bool(
        np.all(np.isfinite(budget.expanded_uncertainty[valid_pixels]))
    )
    status = "complete" if not unknown and combined_known else "partial"
    expanded_status = (
        "available"
        if status == "complete" and expanded_known and budget.coverage_factor is not None
        else "unavailable"
    )
    return {
        "status": status,
        "expanded_status": expanded_status,
        "mask_policy": UNCERTAINTY_MASK_POLICY,
        "masked_pixel_count": int(np.size(valid_pixels) - np.count_nonzero(valid_pixels)),
        "reference_coverage_factor": calibration.reference_coverage_factor,
        "system_coverage_factor": calibration.coverage_factor,
        "missing_for_expanded": (
            []
            if expanded_status == "available"
            else [
                *unknown,
                *(["system_coverage_factor"] if budget.coverage_factor is None else []),
            ]
        ),
        "calibration_status": calibration.uncertainty_status,
        "calibration_components": calibration.uncertainty_components,
        **inputs,
        "k_statistical_standard_uncertainty": k_contract[
            "k_statistical_standard_uncertainty"
        ],
        "k_standard_uncertainty": k_contract["k_standard_uncertainty"],
        "k_expanded_uncertainty": k_contract["k_expanded_uncertainty"],
        "coverage_factor": k_contract["coverage_factor"],
        "components": component_summaries,
        "combined_standard_uncertainty": (
            _uncertainty_array_summary(
                budget.combined_standard_uncertainty,
                detector_mask=detector_mask,
            )
            if combined_known
            else None
        ),
        "expanded_uncertainty": (
            _uncertainty_array_summary(
                budget.expanded_uncertainty,
                detector_mask=detector_mask,
            )
            if expanded_known
            else None
        ),
        "datasets": {
            key: f"/entry/data/uncertainty/{key}"
            for key in _UNCERTAINTY_DATASETS
        },
        "unknown_components": unknown,
        "note": (
            "Unknown components remain null and are not treated as zero; "
            "masked detector pixels are zero-valued placeholders in uncertainty datasets "
            "and are excluded from summaries; use the distributed mask for all analysis."
        ),
    }


@dataclass(frozen=True)
class MaskInfo:
    mask: np.ndarray
    npy_path: Path
    edf_path: Path
    checksum_sha256: str
    user_mask_path: Path | None
    user_mask_pixels: int
    detector_mask_pixels: int
    dark_hot_pixels: int
    combined_mask_pixels: int
    dark_hot_pixel_threshold: float


@dataclass(frozen=True)
class ProvenancePaths:
    run_command: Path
    processing_environment: Path
    code_state: Path
    provenance_summary: Path


@dataclass(frozen=True)
class IncludeManifestInfo:
    source_path: Path
    sha256: str
    relative_paths: tuple[Path, ...]
    content: bytes = field(repr=False)
    copied_path: Path | None = None


@dataclass(frozen=True)
class ThicknessDerivationInfo:
    source_path: Path
    sha256: str
    fixed_thickness_cm: float
    payload: dict[str, Any]
    content: bytes = field(repr=False)
    copied_path: Path | None = None


@dataclass(frozen=True)
class RunControlInputs:
    include_manifest: IncludeManifestInfo | None = None
    thickness_derivation: ThicknessDerivationInfo | None = None


_FIELD_RE = re.compile(
    r"#\s*([^=#:\r\n]+?)\s*(?:=|:)\s*([^#\r\n]+)"
    r"|#\s*(Exposure_time|Exposure_period|Pixel_size)\s+([^#\r\n]+)",
    re.IGNORECASE,
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _parse_float(raw: Any) -> float | None:
    if raw is None:
        return None
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(raw))
    if match is None:
        return None
    try:
        value = float(match.group(0))
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _parse_required_float(fields: dict[str, str], key: str, path: Path) -> float:
    value = _parse_float(fields.get(key))
    if value is None:
        raise ValueError(f"{path} missing numeric {key}")
    return value


def _parse_required_positive_float(fields: dict[str, str], key: str, path: Path) -> float:
    value = _parse_required_float(fields, key, path)
    if value <= 0:
        raise ValueError(f"{path} {key} must be finite and > 0")
    return value


def _norm_key(key: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(key).upper())


def _read_flat_yaml(path: str | Path) -> dict[str, str]:
    yaml_path = Path(path)
    fields: dict[str, str] = {}
    for raw_line in yaml_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("'\"")
    return fields


def _resolve_yaml_path(raw: str | None, yaml_path: Path) -> Path | None:
    if raw is None:
        return None
    raw_text = str(raw).strip().strip("'\"")
    if not raw_text or raw_text == "." or raw_text.lower() in {"none", "null"}:
        return None
    path = Path(raw_text)
    if path.is_absolute():
        return path
    return yaml_path.parent / path


def parse_pydidas_cali_yaml(path: str | Path) -> PydidasCalibration:
    """Parse a flat pydidas calibration YAML file and convert units for pyFAI PONI."""
    yaml_path = Path(path)
    fields = _read_flat_yaml(yaml_path)
    distance_m = _parse_required_positive_float(fields, "detector_dist", yaml_path)
    pixel_x_um = _parse_required_positive_float(fields, "detector_pxsizex", yaml_path)
    pixel_y_um = _parse_required_positive_float(fields, "detector_pxsizey", yaml_path)
    wavelength_angstrom = _parse_required_positive_float(fields, "xray_wavelength", yaml_path)
    return PydidasCalibration(
        source_path=yaml_path,
        detector_name=fields.get("detector_name", "Pilatus 2M"),
        distance_m=distance_m,
        poni1_m=_parse_required_float(fields, "detector_poni1", yaml_path),
        poni2_m=_parse_required_float(fields, "detector_poni2", yaml_path),
        pixel1_m=round(pixel_y_um * 1e-6, 12),
        pixel2_m=round(pixel_x_um * 1e-6, 12),
        rot1=_parse_float(fields.get("detector_rot1")) or 0.0,
        rot2=_parse_float(fields.get("detector_rot2")) or 0.0,
        rot3=_parse_float(fields.get("detector_rot3")) or 0.0,
        wavelength_m=round(wavelength_angstrom * 1e-10, 23),
        mask_path=_resolve_yaml_path(fields.get("detector_mask_file"), yaml_path),
    )


def _poni_detector_name(detector_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "", detector_name)
    if normalized.lower() == "pilatus2m":
        return "Pilatus2M"
    return normalized or "Pilatus2M"


def _render_pydidas_poni(cali_yaml: str | Path) -> str:
    geometry = parse_pydidas_cali_yaml(cali_yaml)
    detector_config = {"pixel1": geometry.pixel1_m, "pixel2": geometry.pixel2_m}
    return "\n".join(
        [
            "# Nota: C-Order, 1 refers to the Y axis, 2 to the X axis",
            f"# Calibration imported from {geometry.source_path}",
            "poni_version: 2",
            f"Detector: {_poni_detector_name(geometry.detector_name)}",
            f"Detector_config: {json.dumps(detector_config)}",
            f"Distance: {geometry.distance_m:.17g}",
            f"Poni1: {geometry.poni1_m:.17g}",
            f"Poni2: {geometry.poni2_m:.17g}",
            f"Rot1: {geometry.rot1:.17g}",
            f"Rot2: {geometry.rot2:.17g}",
            f"Rot3: {geometry.rot3:.17g}",
            f"Wavelength: {geometry.wavelength_m:.12g}",
            "",
            "# This file was generated by SAXSAbs from pydidas Cali.yaml.",
            "",
        ]
    )


def write_pydidas_poni(cali_yaml: str | Path, poni_path: str | Path) -> Path:
    """Write a pyFAI PONI file from pydidas calibration YAML."""
    rendered = _render_pydidas_poni(cali_yaml)
    target = Path(poni_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    return target

def parse_bl19b2_description(description: str) -> BL19B2Header:
    """Parse BL19B2 Pilatus TIFF ImageDescription text."""
    text = str(description or "").replace("\x00", "\n").replace("\r", "\n")
    fields: dict[str, str] = {}
    for match in _FIELD_RE.finditer(text):
        if match.group(1):
            key = match.group(1).strip()
            value = match.group(2).strip()
        else:
            key = match.group(3).strip()
            value = match.group(4).strip()
        fields[_norm_key(key)] = value

    return BL19B2Header(
        exposure_s=_parse_float(fields.get("EXPOSURETIME")),
        monitor=_parse_float(fields.get("MON")),
        transmission=_parse_float(fields.get("ABS")),
        energy_kev=_parse_float(fields.get("E0")),
        distance_mm=_parse_float(fields.get("CAML")),
        beam_x_px=_parse_float(fields.get("DRTX")),
        beam_y_px=_parse_float(fields.get("DRTY")),
        pixel_size_m=_parse_float(fields.get("PIXELSIZE")),
        raw_fields=fields,
    )


def read_tiff_header(path: str | Path) -> BL19B2Header:
    """Read BL19B2 header fields from a TIFF file without loading all pixels."""
    try:
        import tifffile
    except ImportError as exc:  # pragma: no cover
        raise ImportError("tifffile is required for BL19B2 TIFF header scanning") from exc

    with tifffile.TiffFile(str(path)) as tif:
        page = tif.pages[0]
        tag = page.tags.get("ImageDescription")
        description = "" if tag is None else str(tag.value)
    return parse_bl19b2_description(description)


def _is_finite_positive(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value)) and float(value) > 0


def classify_sample_frame(
    header: BL19B2Header,
    *,
    beer_lambert_thickness: bool = True,
    transmission_abs_uncertainty: float | None = None,
) -> FrameClassification:
    """Return whether a sample frame has enough metadata for cm^-1 output."""
    missing: list[str] = []
    if not _is_finite_positive(header.exposure_s):
        missing.append("Exposure_time")
    if not _is_finite_positive(header.monitor):
        missing.append("MON")
    if not _is_finite_positive(header.transmission):
        missing.append("ABS/transmission")
    if missing:
        return FrameClassification("rejected", "missing or invalid " + ", ".join(missing))

    assert header.transmission is not None
    if header.transmission > 1.0:
        return FrameClassification(
            "rejected",
            f"transmission ABS must be <= 1 for sample frames, got {header.transmission:.6g}",
        )
    if beer_lambert_thickness:
        try:
            estimate_thickness_cm(
                header.transmission,
                1.0,
                transmission_abs_uncertainty=transmission_abs_uncertainty,
            )
        except ValueError as exc:
            return FrameClassification("rejected", str(exc))
    return FrameClassification("ok")


def estimate_thickness_cm(
    transmission: float,
    mu_cm_inv: float,
    *,
    transmission_abs_uncertainty: float | None = None,
) -> np.float64:
    """Estimate thickness from Beer-Lambert law: d = -ln(T) / mu."""
    t = float(transmission)
    mu = float(mu_cm_inv)
    if not math.isfinite(t) or t <= 0 or t >= 1:
        raise ValueError(f"transmission must satisfy 0 < T < 1, got {transmission!r}")
    if not math.isfinite(mu) or mu <= 0:
        raise ValueError(f"mu_cm_inv must be finite and > 0, got {mu_cm_inv!r}")
    if transmission_abs_uncertainty is None:
        if not (
            DEFAULT_MIN_BEER_LAMBERT_TRANSMISSION
            < t
            < DEFAULT_MAX_BEER_LAMBERT_TRANSMISSION
        ):
            raise ValueError(
                "Beer-Lambert thickness is ill-conditioned for transmission "
                f"T={t:.10g}; provide a fixed sample thickness or a measured transmission "
                "uncertainty"
            )
    else:
        u_t = float(transmission_abs_uncertainty)
        if not math.isfinite(u_t) or u_t < 0:
            raise ValueError("transmission_abs_uncertainty must be finite and >= 0")
        if t <= 3.0 * u_t or 1.0 - t <= 3.0 * u_t:
            raise ValueError(
                "Beer-Lambert thickness is ill-conditioned: both T and attenuation (1-T) "
                "must exceed three times transmission_abs_uncertainty"
            )
    return np.float64(-math.log(t) / mu)


def compute_norm_factor(
    exposure_s: float,
    monitor: float,
    transmission: float,
    monitor_mode: str = "rate",
) -> float:
    """Compute normalization for a rate or exposure-integrated monitor."""
    exp_v = float(exposure_s)
    mon_v = float(monitor)
    trans_v = float(transmission)
    if not all(math.isfinite(v) and v > 0 for v in (exp_v, mon_v, trans_v)):
        raise ValueError("exposure_s, monitor, and transmission must be finite and > 0")
    norm = _core_compute_norm_factor(exp_v, mon_v, trans_v, monitor_mode)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("exposure_s, monitor, and transmission must define a positive normalization")
    return float(norm)


def _resolve_standard_reference_data(
    standard_key: str,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    canonical_key = normalize_standard_key(standard_key)
    if canonical_key == "SRM3600":
        return None, None
    return get_reference_data(canonical_key)

def _resolve_standard_thickness_cm(config: BL19B2Abs2DConfig) -> tuple[float, str]:
    is_srm3600 = normalize_standard_key(config.standard_key) == "SRM3600"
    if is_srm3600:
        if config.standard_thickness_cm is not None and not math.isclose(
            float(config.standard_thickness_cm),
            SRM3600_THICKNESS_CM,
            rel_tol=0.0,
            abs_tol=np.finfo(np.float64).eps,
        ):
            raise ValueError(
                "SRM 3600 standard_thickness_cm must equal the certified 0.1055 cm"
            )
        return SRM3600_THICKNESS_CM, "nist_srm3600_certificate"
    if config.standard_thickness_cm is None:
        raise ValueError(
            "standard_thickness_cm is required for standards other than SRM 3600"
        )
    return float(config.standard_thickness_cm), "user_config"


def validate_config(config: BL19B2Abs2DConfig) -> None:
    if (config.poni_path is None) == (config.pydidas_cali_yaml is None):
        raise ValueError("provide exactly one of poni_path or pydidas_cali_yaml")
    if not math.isfinite(float(config.alpha)) or float(config.alpha) <= 0:
        raise ValueError("alpha must be finite and > 0")
    if config.standard_thickness_cm is not None:
        thickness = float(config.standard_thickness_cm)
        if not math.isfinite(thickness) or thickness <= 0:
            raise ValueError("standard_thickness_cm must be finite and > 0")
    _resolve_standard_thickness_cm(config)
    has_mu = config.mu_cm_inv is not None
    has_fixed_thickness = config.sample_thickness_cm is not None
    if has_mu == has_fixed_thickness:
        raise ValueError("provide exactly one of mu_cm_inv or sample_thickness_cm")
    if has_mu and (
        not math.isfinite(float(config.mu_cm_inv)) or float(config.mu_cm_inv) <= 0
    ):
        raise ValueError("mu_cm_inv must be finite and > 0")
    if has_fixed_thickness and (
        not math.isfinite(float(config.sample_thickness_cm))
        or float(config.sample_thickness_cm) <= 0
    ):
        raise ValueError("sample_thickness_cm must be finite and > 0")
    if str(config.monitor_mode).strip().lower() not in {"rate", "integrated"}:
        raise ValueError("monitor_mode must be 'rate' or 'integrated'")
    uncertainty_fields = (
        "transmission_abs_uncertainty",
        "monitor_relative_standard_uncertainty",
        "sample_thickness_relative_standard_uncertainty",
        "standard_thickness_relative_standard_uncertainty",
        "standard_transmission_abs_uncertainty",
        "standard_monitor_relative_standard_uncertainty",
        "calibration_background_monitor_relative_standard_uncertainty",
        "mu_relative_standard_uncertainty",
        "alpha_standard_uncertainty",
    )
    for field_name in uncertainty_fields:
        value = getattr(config, field_name)
        if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
            raise ValueError(f"{field_name} must be finite and >= 0")
    if config.system_coverage_factor is not None and (
        not math.isfinite(float(config.system_coverage_factor))
        or float(config.system_coverage_factor) <= 0
    ):
        raise ValueError("system_coverage_factor must be finite and > 0")
    if has_mu and config.sample_thickness_relative_standard_uncertainty is not None:
        raise ValueError(
            "sample_thickness_relative_standard_uncertainty requires sample_thickness_cm"
        )
    if has_fixed_thickness and config.mu_relative_standard_uncertainty is not None:
        raise ValueError("mu_relative_standard_uncertainty requires mu_cm_inv")
    _load_run_control_inputs(config)
    q_lo, q_hi = config.q_window
    if not (math.isfinite(float(q_lo)) and math.isfinite(float(q_hi)) and q_lo < q_hi):
        raise ValueError("q_window must contain finite increasing values")
    if int(config.npt) <= 0:
        raise ValueError("npt must be > 0")
    if not math.isfinite(float(config.dark_hot_pixel_threshold)) or config.dark_hot_pixel_threshold < 0:
        raise ValueError("dark_hot_pixel_threshold must be finite and >= 0")


def subtract_dark_for_exposure(
    image: np.ndarray,
    dark: np.ndarray,
    *,
    image_exposure_s: float,
    dark_exposure_s: float,
) -> np.ndarray:
    """Subtract a dark image after scaling it to the image exposure time."""
    img = np.asarray(image, dtype=np.float64)
    dark_arr = np.asarray(dark, dtype=np.float64)
    if img.shape != dark_arr.shape:
        raise ValueError(f"dark shape mismatch: {dark_arr.shape} vs {img.shape}")
    exp_v = float(image_exposure_s)
    dark_exp_v = float(dark_exposure_s)
    if not (math.isfinite(exp_v) and exp_v > 0):
        raise ValueError("image_exposure_s must be finite and > 0")
    if not (math.isfinite(dark_exp_v) and dark_exp_v > 0):
        raise ValueError("dark_exposure_s must be finite and > 0")
    return img - dark_arr * (exp_v / dark_exp_v)


def normalize_dark_corrected_image(
    image: np.ndarray,
    dark: np.ndarray,
    *,
    image_exposure_s: float,
    dark_exposure_s: float,
    monitor: float,
    transmission: float,
    monitor_mode: str = "rate",
) -> tuple[np.ndarray, float]:
    result = normalize_detector_frame(
        image,
        dark,
        image_exposure_s=image_exposure_s,
        dark_exposure_s=dark_exposure_s,
        monitor=monitor,
        transmission=transmission,
        monitor_mode=monitor_mode,
    )
    return result.image, result.normalization_factor


def compute_bl19b2_uncertainty_budget(
    intensity_abs: np.ndarray,
    *,
    sample_raw: np.ndarray,
    background_raw: np.ndarray,
    dark_raw: np.ndarray,
    sample_exposure_s: float,
    background_exposure_s: float,
    dark_exposure_s: float,
    norm_sample: float,
    norm_background: float,
    alpha: float,
    k_factor: float,
    thickness_cm: float,
    transmission: float,
    mu_cm_inv: float | None,
    k_statistical_standard_uncertainty: float | None,
    k_standard_uncertainty: float | None,
    standard_thickness_relative_standard_uncertainty: float | None,
    transmission_abs_uncertainty: float | None,
    monitor_relative_standard_uncertainty: float | None,
    thickness_relative_standard_uncertainty: float | None,
    mu_relative_standard_uncertainty: float | None,
    alpha_standard_uncertainty: float | None,
    coverage_factor: float | None,
    k_independent_standard_uncertainty: float | None = None,
    k_alpha_relative_sensitivity: float | None = None,
    k_calibration_background_monitor_relative_sensitivity: float | None = None,
    calibration_background_monitor_relative_standard_uncertainty: float | None = None,
    detector_mask: np.ndarray | None = None,
) -> AbsoluteUncertaintyBudget:
    """Propagate BL19B2 raw-count and scale uncertainties to detector pixels."""
    intensity = np.asarray(intensity_abs, dtype=np.float64)
    sample = np.asarray(sample_raw, dtype=np.float64)
    background = np.asarray(background_raw, dtype=np.float64)
    dark = np.asarray(dark_raw, dtype=np.float64)
    if not (intensity.shape == sample.shape == background.shape == dark.shape):
        raise ValueError("intensity, sample, background, and dark shapes must match")
    if detector_mask is None:
        masked = np.zeros(intensity.shape, dtype=bool)
    else:
        mask_values = np.asarray(detector_mask)
        if mask_values.shape != intensity.shape:
            raise ValueError(
                f"detector_mask shape mismatch: {mask_values.shape} vs {intensity.shape}"
            )
        is_boolean = np.issubdtype(mask_values.dtype, np.bool_)
        is_real_numeric = np.issubdtype(
            mask_values.dtype, np.integer
        ) or np.issubdtype(mask_values.dtype, np.floating)
        if not (is_boolean or is_real_numeric):
            raise ValueError("detector_mask must be boolean or finite real numeric")
        if is_real_numeric and not np.all(np.isfinite(mask_values)):
            raise ValueError("detector_mask must contain finite values")
        masked = mask_values.astype(bool)

    invalid_intensity = ~np.isfinite(intensity)
    if np.any(invalid_intensity & ~masked):
        raise ValueError("intensity_abs must contain finite values at unmasked pixels")
    if np.any(masked):
        intensity = intensity.copy()
        intensity[masked] = 0.0

    def _sanitize_raw_counts(label: str, image: np.ndarray) -> np.ndarray:
        invalid = ~np.isfinite(image) | (image < 0)
        if np.any(invalid & ~masked):
            raise ValueError(
                f"{label} must contain finite non-negative detector counts at unmasked pixels"
            )
        if not np.any(invalid) and not np.any(masked):
            return image
        sanitized = image.copy()
        sanitized[masked] = 0.0
        return sanitized

    sample = _sanitize_raw_counts("sample_raw", sample)
    background = _sanitize_raw_counts("background_raw", background)
    dark = _sanitize_raw_counts("dark_raw", dark)

    sample_exp = float(sample_exposure_s)
    background_exp = float(background_exposure_s)
    dark_exp = float(dark_exposure_s)
    norm_s = float(norm_sample)
    norm_bg = float(norm_background)
    alpha_value = float(alpha)
    k_value = float(k_factor)
    thickness = float(thickness_cm)
    trans = float(transmission)
    required_positive = {
        "sample_exposure_s": sample_exp,
        "background_exposure_s": background_exp,
        "dark_exposure_s": dark_exp,
        "norm_sample": norm_s,
        "norm_background": norm_bg,
        "alpha": alpha_value,
        "k_factor": k_value,
        "thickness_cm": thickness,
        "transmission": trans,
    }
    for name, value in required_positive.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and > 0")

    sample_dark_scale = sample_exp / dark_exp
    background_dark_scale = background_exp / dark_exp
    coefficient_sample = 1.0 / norm_s
    coefficient_background = -alpha_value / norm_bg
    coefficient_shared_dark = (
        -sample_dark_scale / norm_s
        + alpha_value * background_dark_scale / norm_bg
    )
    variance_net = (
        np.square(coefficient_sample) * sample
        + np.square(coefficient_background) * background
        + np.square(coefficient_shared_dark) * dark
    )
    statistical_abs = np.sqrt(variance_net) * abs(k_value / thickness)

    sample_normed = (sample - dark * sample_dark_scale) / norm_s
    background_normed = (background - dark * background_dark_scale) / norm_bg
    net = sample_normed - alpha_value * background_normed

    if transmission_abs_uncertainty is None:
        transmission_relative: np.ndarray | None = None
    else:
        u_t = float(transmission_abs_uncertainty)
        if not math.isfinite(u_t) or u_t < 0:
            raise ValueError("transmission_abs_uncertainty must be finite and >= 0")
        if u_t == 0:
            transmission_relative = np.zeros_like(intensity)
        else:
            with np.errstate(divide="ignore", invalid="ignore"):
                sensitivity = -sample_normed / (trans * net)
                if mu_cm_inv is not None:
                    mu_value = float(mu_cm_inv)
                    if not math.isfinite(mu_value) or mu_value <= 0:
                        raise ValueError("mu_cm_inv must be finite and > 0")
                    sensitivity = sensitivity + 1.0 / (mu_value * trans * thickness)
                transmission_relative = np.abs(sensitivity) * u_t
            transmission_relative[masked] = 0.0
            transmission_relative[~np.isfinite(transmission_relative)] = np.nan

    if k_statistical_standard_uncertainty is None:
        k_relative = None
        standard_relative = None
    else:
        k_stat_u = float(k_statistical_standard_uncertainty)
        if not math.isfinite(k_stat_u) or k_stat_u < 0:
            raise ValueError("k_statistical_standard_uncertainty must be finite and >= 0")
        k_relative = k_stat_u / k_value
        if k_independent_standard_uncertainty is None:
            # Pre-v4 K budgets omit standard T/MON/BG inputs.  Do not infer
            # completeness from their certificate-plus-scatter subtotal.
            standard_relative = None
        else:
            independent_u = float(k_independent_standard_uncertainty)
            if not math.isfinite(independent_u) or independent_u < k_stat_u:
                raise ValueError(
                    "k_independent_standard_uncertainty must be finite and >= "
                    "k_statistical_standard_uncertainty"
                )
            standard_relative = math.sqrt(
                max(independent_u**2 - k_stat_u**2, 0.0)
            ) / k_value
    sample_monitor_absolute: np.ndarray | None
    if monitor_relative_standard_uncertainty is None:
        sample_monitor_absolute = None
    else:
        monitor_u = float(monitor_relative_standard_uncertainty)
        if not math.isfinite(monitor_u) or monitor_u < 0:
            raise ValueError(
                "monitor_relative_standard_uncertainty must be finite and >= 0"
            )
        sample_monitor_absolute = (
            abs(k_value / thickness) * np.abs(sample_normed) * monitor_u
        )

    background_monitor_absolute: np.ndarray | None
    background_monitor_u = calibration_background_monitor_relative_standard_uncertainty
    if background_monitor_u is None:
        background_monitor_absolute = None
    else:
        background_monitor_u_value = float(background_monitor_u)
        if not math.isfinite(background_monitor_u_value) or background_monitor_u_value < 0:
            raise ValueError(
                "calibration_background_monitor_relative_standard_uncertainty "
                "must be finite and >= 0"
            )
        if background_monitor_u_value == 0:
            background_monitor_absolute = np.zeros_like(intensity)
        elif k_calibration_background_monitor_relative_sensitivity is None:
            background_monitor_absolute = None
        else:
            background_k_sensitivity = float(
                k_calibration_background_monitor_relative_sensitivity
            )
            if not math.isfinite(background_k_sensitivity):
                raise ValueError(
                    "k_calibration_background_monitor_relative_sensitivity "
                    "must be finite"
                )
            absolute_background = background_normed * (k_value / thickness)
            background_monitor_absolute = np.abs(
                intensity * background_k_sensitivity
                + alpha_value * absolute_background
            ) * background_monitor_u_value

    if sample_monitor_absolute is None or background_monitor_absolute is None:
        monitor_relative: np.ndarray | None = None
    else:
        monitor_absolute = np.hypot(
            sample_monitor_absolute,
            background_monitor_absolute,
        )
        monitor_relative = np.zeros_like(intensity)
        nonzero_intensity = np.abs(intensity) > 0
        monitor_relative[nonzero_intensity] = (
            monitor_absolute[nonzero_intensity] / np.abs(intensity[nonzero_intensity])
        )
        undefined = ~nonzero_intensity & (monitor_absolute > 0)
        monitor_relative[undefined] = np.nan
    if mu_cm_inv is None:
        thickness_relative = thickness_relative_standard_uncertainty
        mu_relative = 0.0
    else:
        thickness_relative = 0.0
        mu_relative = mu_relative_standard_uncertainty
    absolute_background = background_normed * (k_value / thickness)
    alpha_u_for_core = alpha_standard_uncertainty
    alpha_sensitivity_image = absolute_background
    if alpha_standard_uncertainty is not None:
        alpha_u = float(alpha_standard_uncertainty)
        if not math.isfinite(alpha_u) or alpha_u < 0:
            raise ValueError("alpha_standard_uncertainty must be finite and >= 0")
        if alpha_u == 0:
            alpha_sensitivity_image = np.zeros_like(intensity)
        elif k_alpha_relative_sensitivity is None:
            alpha_u_for_core = None
        else:
            k_alpha_sensitivity = float(k_alpha_relative_sensitivity)
            if not math.isfinite(k_alpha_sensitivity):
                raise ValueError("k_alpha_relative_sensitivity must be finite")
            # The same alpha appears in K and sample/background subtraction.
            # Preserve signs so covariance/cancellation is represented.
            alpha_sensitivity_image = (
                intensity * k_alpha_sensitivity - absolute_background
            )
    budget = propagate_absolute_uncertainty(
        intensity,
        statistical_standard_uncertainty=statistical_abs,
        k_relative_standard_uncertainty=k_relative,
        standard_relative_standard_uncertainty=standard_relative,
        transmission_relative_standard_uncertainty=transmission_relative,
        monitor_relative_standard_uncertainty=monitor_relative,
        thickness_relative_standard_uncertainty=thickness_relative,
        mu_relative_standard_uncertainty=mu_relative,
        alpha_standard_uncertainty=alpha_u_for_core,
        buffer_intensity=alpha_sensitivity_image,
        coverage_factor=coverage_factor,
    )
    if not np.any(masked):
        return budget
    masked_components: dict[str, np.ndarray] = {}
    for attribute in _UNCERTAINTY_DATASETS.values():
        values = np.asarray(getattr(budget, attribute), dtype=np.float64).copy()
        values[masked] = 0.0
        masked_components[attribute] = values
    return replace(budget, **masked_components)


def _require_close(
    *,
    label: str,
    measured: float,
    expected: float,
    relative_tolerance: float | None = None,
    absolute_tolerance: float | None = None,
) -> None:
    if relative_tolerance is not None:
        tolerance = relative_tolerance * max(abs(expected), np.finfo(float).tiny)
    elif absolute_tolerance is not None:
        tolerance = absolute_tolerance
    else:  # pragma: no cover - internal contract
        raise ValueError("an instrument consistency tolerance is required")
    if abs(measured - expected) > tolerance:
        raise ValueError(
            f"{label} mismatch: measured {measured:.10g}, expected {expected:.10g}, "
            f"tolerance {tolerance:.6g}"
        )


def validate_instrument_consistency(
    header: BL19B2Header,
    *,
    image_shape: tuple[int, ...],
    integrator: Any,
    label: str,
    reference_header: BL19B2Header | None = None,
    relative_tolerance: float = INSTRUMENT_RELATIVE_TOLERANCE,
    beam_center_tolerance_px: float = BEAM_CENTER_TOLERANCE_PX,
) -> tuple[str, ...]:
    """Validate a BL19B2 frame against its PONI geometry and optional standard header.

    Image/PONI shape and all scientific header fields are mandatory for formal
    absolute-intensity output.
    """
    shape = tuple(int(v) for v in image_shape)
    if len(shape) != 2 or any(v <= 0 for v in shape):
        raise ValueError(f"{label} detector image must have a positive 2D shape")
    detector = getattr(integrator, "detector", None)
    poni_shape = getattr(detector, "shape", None)
    if poni_shape is None:
        poni_shape = getattr(detector, "max_shape", None)
    if poni_shape is None:
        raise ValueError("PONI detector shape is missing; instrument consistency cannot be verified")
    poni_shape_tuple = tuple(int(v) for v in poni_shape)
    if shape != poni_shape_tuple:
        raise ValueError(f"{label} shape mismatch: image {shape}, PONI detector {poni_shape_tuple}")

    rel_tol = float(relative_tolerance)
    beam_tol = float(beam_center_tolerance_px)
    if not math.isfinite(rel_tol) or rel_tol <= 0:
        raise ValueError("relative_tolerance must be finite and > 0")
    if not math.isfinite(beam_tol) or beam_tol <= 0:
        raise ValueError("beam_center_tolerance_px must be finite and > 0")

    distance_m = float(getattr(integrator, "dist", math.nan))
    wavelength_m = float(getattr(integrator, "wavelength", math.nan))
    pixel_y_m = float(getattr(detector, "pixel1", math.nan))
    pixel_x_m = float(getattr(detector, "pixel2", math.nan))
    try:
        fit2d = integrator.getFit2D()
        poni_beam_x = float(fit2d["centerX"])
        poni_beam_y = float(fit2d["centerY"])
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("PONI beam center is missing; instrument consistency cannot be verified") from exc
    positive_poni_values = (distance_m, wavelength_m, pixel_y_m, pixel_x_m)
    if not all(math.isfinite(value) and value > 0 for value in positive_poni_values) or not all(
        math.isfinite(value) and value >= 0 for value in (poni_beam_x, poni_beam_y)
    ):
        raise ValueError("PONI geometry contains missing or non-positive instrument values")
    poni_energy_kev = 12.398419843320026 / (wavelength_m * 1.0e10)

    warnings: list[str] = []
    fields = (
        ("energy_kev", header.energy_kev, poni_energy_kev, rel_tol, None),
        ("distance_mm", header.distance_mm, distance_m * 1000.0, rel_tol, None),
        ("pixel_size_m/y", header.pixel_size_m, pixel_y_m, rel_tol, None),
        ("pixel_size_m/x", header.pixel_size_m, pixel_x_m, rel_tol, None),
        ("beam_x_px", header.beam_x_px, poni_beam_x, None, beam_tol),
        ("beam_y_px", header.beam_y_px, poni_beam_y, None, beam_tol),
    )
    for field_name, measured, expected, relative, absolute in fields:
        if measured is None:
            raise ValueError(
                f"{label} {field_name} is missing; instrument consistency cannot be verified"
            )
        _require_close(
            label=f"{label} {field_name} vs PONI",
            measured=float(measured),
            expected=float(expected),
            relative_tolerance=relative,
            absolute_tolerance=absolute,
        )

    if reference_header is not None:
        reference_fields = (
            ("energy_kev", header.energy_kev, reference_header.energy_kev, rel_tol, None),
            ("distance_mm", header.distance_mm, reference_header.distance_mm, rel_tol, None),
            ("pixel_size_m", header.pixel_size_m, reference_header.pixel_size_m, rel_tol, None),
            ("beam_x_px", header.beam_x_px, reference_header.beam_x_px, None, beam_tol),
            ("beam_y_px", header.beam_y_px, reference_header.beam_y_px, None, beam_tol),
        )
        for field_name, measured, expected, relative, absolute in reference_fields:
            if measured is None or expected is None:
                raise ValueError(
                    f"{label} {field_name} vs standard is missing; instrument consistency "
                    "cannot be verified"
                )
            _require_close(
                label=f"{label} {field_name} vs standard",
                measured=float(measured),
                expected=float(expected),
                relative_tolerance=relative,
                absolute_tolerance=absolute,
            )
    return tuple(warnings)


def natural_key(path: str | Path) -> list[Any]:
    text = str(path)
    parts = re.split(r"(\d+)", text)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def is_sample_tiff(path: str | Path, input_root: str | Path) -> bool:
    p = Path(path)
    if p.suffix.lower() not in (".tif", ".tiff"):
        return False
    try:
        rel = p.relative_to(Path(input_root))
    except ValueError:
        rel = p
    parts = [part.lower() for part in rel.parts[:-1]]
    if any(part in EXCLUDED_SAMPLE_PARTS for part in parts):
        return False
    return not any(part.startswith(EXCLUDED_PREFIXES) for part in parts)


def build_output_paths(source: str | Path, *, input_root: str | Path, output_root: str | Path) -> OutputPaths:
    source_path = Path(source)
    root = Path(input_root)
    out = Path(output_root)
    rel_parent = source_path.parent.relative_to(root)
    stem = source_path.stem
    return OutputPaths(
        h5=out / "images_h5" / rel_parent / f"{stem}_abs2d_cm-1.h5",
        edf=out / "images_edf" / rel_parent / f"{stem}_abs2d_cm-1.edf",
        metadata=out / "metadata" / rel_parent / f"{stem}_abs2d.json",
        preview=out / "previews" / rel_parent / f"{stem}_preview.png",
    )


def _resolve_mask_path(
    ref: Path,
    *,
    mask_path: str | Path | None = None,
    pydidas_cali_yaml: str | Path | None = None,
) -> Path | None:
    if mask_path is not None:
        explicit = Path(mask_path)
        if not explicit.is_file():
            raise FileNotFoundError(f"explicit BL19B2 mask must be a file: {explicit}")
        return explicit
    if pydidas_cali_yaml is not None:
        yaml_path = Path(pydidas_cali_yaml)
        fields = _read_flat_yaml(yaml_path)
        yaml_mask = _resolve_yaml_path(fields.get("detector_mask_file"), yaml_path)
        if yaml_mask is not None and yaml_mask.is_file():
            return yaml_mask
    for name in ("MASK_file.edf", "Mask.edf", "mask.edf"):
        candidate = ref / name
        if candidate.is_file():
            return candidate
    return None


def _resolve_reference_file(
    input_root: Path,
    default_path: Path,
    explicit_path: str | Path | None,
    label: str,
    *,
    required: bool,
) -> Path | None:
    if explicit_path is None:
        path = default_path
    else:
        path = Path(explicit_path)
        if not path.is_absolute():
            path = input_root / path

    if path.is_file():
        return path
    if required or explicit_path is not None:
        raise FileNotFoundError(f"Missing BL19B2 {label} reference file: {path}")
    return path


def find_reference_paths(
    input_root: str | Path,
    *,
    mask_path: str | Path | None = None,
    pydidas_cali_yaml: str | Path | None = None,
    dark_path: str | Path | None = None,
    background_path: str | Path | None = None,
    standard_path: str | Path | None = None,
    direct_path: str | Path | None = None,
) -> ReferencePaths:
    root = Path(input_root)
    ref = root / "reference_saxs"
    paths = ReferencePaths(
        dark=_resolve_reference_file(root, ref / "dark001.tif", dark_path, "dark", required=True),
        background=_resolve_reference_file(
            root,
            ref / "BG001.tif",
            background_path,
            "background",
            required=True,
        ),
        standard=_resolve_reference_file(root, ref / "GC001.tif", standard_path, "standard", required=True),
        direct=_resolve_reference_file(root, ref / "drt001.tif", direct_path, "direct-beam", required=False),
        mask=_resolve_mask_path(ref, mask_path=mask_path, pydidas_cali_yaml=pydidas_cali_yaml),
    )
    missing = [
        str(path)
        for path in (paths.dark, paths.background, paths.standard)
        if not Path(path).exists()
    ]
    if missing:
        raise FileNotFoundError("Missing required BL19B2 reference file(s): " + "; ".join(missing))
    return paths


def read_detector_image(path: str | Path) -> np.ndarray:
    """Read a detector image using fabio and return float64 pixels."""
    try:
        import fabio
    except ImportError as exc:  # pragma: no cover
        raise ImportError("fabio is required for BL19B2 detector image reading") from exc
    image = fabio.open(str(path))
    try:
        return np.array(image.data, dtype=np.float64, copy=True, order="C")
    finally:
        close = getattr(image, "close", None)
        if callable(close):
            close()


def build_combined_mask(
    detector_mask: np.ndarray | None,
    user_mask: np.ndarray | None,
    dark: np.ndarray,
    *,
    dark_hot_pixel_threshold: float = 10.0,
) -> tuple[np.ndarray, dict[str, int]]:
    dark_arr = np.asarray(dark, dtype=np.float64)
    if detector_mask is None:
        det_mask = np.zeros(dark_arr.shape, dtype=bool)
    else:
        det_mask = np.asarray(detector_mask) != 0
        if det_mask.shape != dark_arr.shape:
            raise ValueError(f"detector mask shape mismatch: {det_mask.shape} vs {dark_arr.shape}")
    if user_mask is None:
        usr_mask = np.zeros(dark_arr.shape, dtype=bool)
    else:
        usr_mask = np.asarray(user_mask) != 0
        if usr_mask.shape != dark_arr.shape:
            raise ValueError(f"user mask shape mismatch: {usr_mask.shape} vs {dark_arr.shape}")
    hot_threshold = float(dark_hot_pixel_threshold)
    if not math.isfinite(hot_threshold) or hot_threshold < 0:
        raise ValueError("dark_hot_pixel_threshold must be finite and >= 0")
    dark_hot = np.abs(dark_arr) > hot_threshold
    combined = (usr_mask | det_mask | dark_hot).astype(np.uint8)
    return combined, {
        "user_mask_pixels": int(np.count_nonzero(usr_mask)),
        "detector_mask_pixels": int(np.count_nonzero(det_mask)),
        "dark_hot_pixels": int(np.count_nonzero(dark_hot)),
        "combined_mask_pixels": int(np.count_nonzero(combined)),
    }


def _mask_checksum(mask: np.ndarray) -> str:
    arr = np.asarray(mask, dtype=np.uint8)
    h = hashlib.sha256()
    h.update(str(arr.shape).encode("ascii"))
    h.update(arr.tobytes(order="C"))
    return h.hexdigest()


def _file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _stable_file_fingerprint(path: str | Path) -> dict[str, int | str]:
    """Hash a file while verifying that its size and mtime stay unchanged."""
    source = Path(path)
    try:
        before = source.stat()
        sha256 = _file_sha256(source)
        after = source.stat()
    except OSError as exc:
        raise SourceChangedDuringReadError(
            f"detector source became unavailable while being read: {source}"
        ) from exc
    before_stat = (int(before.st_size), int(before.st_mtime_ns))
    after_stat = (int(after.st_size), int(after.st_mtime_ns))
    if before_stat != after_stat:
        raise SourceChangedDuringReadError(
            f"detector source changed while being hashed: {source}"
        )
    return {
        "sha256": sha256,
        "size_bytes": after_stat[0],
        "mtime_ns": after_stat[1],
    }


def _read_stable_control_file(path: str | Path, *, label: str) -> tuple[bytes, str]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f'{label} not found or not a regular file: {source}')
    before = source.stat()
    content = source.read_bytes()
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SourceChangedDuringReadError(f'{label} changed while being read: {source}')
    return content, hashlib.sha256(content).hexdigest()


def _safe_manifest_relative_path(raw: Any, *, input_root: Path) -> Path:
    raw_text = "" if raw is None else str(raw)
    value = raw_text.strip()
    if not value:
        raise ValueError('include manifest relative_path must not be empty')
    if raw_text != value:
        raise ValueError(
            f'include manifest path has unsafe leading or trailing whitespace: {raw_text!r}'
        )
    normalized = value.replace('\\', '/')
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(normalized)
    if windows_path.drive or windows_path.root or posix_path.is_absolute():
        raise ValueError(f'include manifest path must be relative: {value!r}')
    segments = normalized.split('/')
    if any(segment in {'', '.', '..'} for segment in segments):
        raise ValueError(f'include manifest path is not a safe relative path: {value!r}')
    if any(
        ':' in segment or segment.endswith((' ', '.'))
        for segment in segments
    ):
        raise ValueError(
            f'include manifest path contains a Windows-unsafe segment: {value!r}'
        )
    relative = Path(*segments)
    root_resolved = input_root.resolve()
    candidate = (root_resolved / relative).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise ValueError(f'include manifest path escapes input_root: {value!r}')
    if not candidate.is_file():
        raise FileNotFoundError(
            f'include manifest sample not found or not a regular file: {value!r}'
        )
    if candidate.suffix.lower() not in {'.tif', '.tiff'}:
        raise ValueError(f'include manifest path is not a TIFF: {value!r}')
    if not is_sample_tiff(candidate, root_resolved):
        raise ValueError(f'include manifest path is not a discovered sample TIFF: {value!r}')
    return candidate.relative_to(root_resolved)


def _manifest_path_key(path: str | Path) -> str:
    return str(path).strip().replace('\\', '/').casefold()


def _load_include_manifest(config: BL19B2Abs2DConfig) -> IncludeManifestInfo | None:
    if config.include_manifest_path is None:
        return None
    source = Path(config.include_manifest_path)
    content, sha256 = _read_stable_control_file(source, label='include manifest')
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('include manifest must be UTF-8 CSV') from exc
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None or reader.fieldnames.count('relative_path') != 1:
        raise ValueError('include manifest must contain a relative_path column')
    raw_rows: list[tuple[int, Any]] = []
    seen: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(
                f'include manifest row {row_number} contains unnamed extra columns'
            )
        raw_relative = row.get('relative_path')
        key = _manifest_path_key('' if raw_relative is None else raw_relative)
        if key in seen:
            raise ValueError(
                'include manifest contains a duplicate relative_path '
                f'at row {row_number}: {raw_relative!r}'
            )
        seen.add(key)
        raw_rows.append((row_number, raw_relative))
    relative_paths: list[Path] = []
    for _row_number, raw_relative in raw_rows:
        relative = _safe_manifest_relative_path(
            raw_relative, input_root=Path(config.input_root)
        )
        relative_paths.append(relative)
    if not relative_paths:
        raise ValueError('include manifest must contain at least one sample row')
    return IncludeManifestInfo(
        source_path=source,
        sha256=sha256,
        relative_paths=tuple(relative_paths),
        content=content,
    )


def _load_thickness_derivation(
    config: BL19B2Abs2DConfig,
) -> ThicknessDerivationInfo | None:
    if config.thickness_derivation_path is None:
        return None
    if config.sample_thickness_cm is None:
        raise ValueError(
            'thickness_derivation_path requires fixed sample_thickness_cm mode'
        )
    source = Path(config.thickness_derivation_path)
    content, sha256 = _read_stable_control_file(
        source, label='thickness derivation JSON'
    )
    try:
        payload = json.loads(content.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('thickness derivation must be a UTF-8 JSON object') from exc
    if not isinstance(payload, dict):
        raise ValueError('thickness derivation must be a JSON object')
    value = payload.get('fixed_thickness_cm')
    if isinstance(value, bool):
        raise ValueError(
            'thickness derivation fixed_thickness_cm must be finite and > 0'
        )
    try:
        fixed_thickness_cm = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            'thickness derivation fixed_thickness_cm must be finite and > 0'
        ) from exc
    if not math.isfinite(fixed_thickness_cm) or fixed_thickness_cm <= 0:
        raise ValueError(
            'thickness derivation fixed_thickness_cm must be finite and > 0'
        )
    configured = float(config.sample_thickness_cm)
    if not math.isclose(
        fixed_thickness_cm, configured, rel_tol=1e-9, abs_tol=1e-12
    ):
        raise ValueError(
            'thickness derivation fixed_thickness_cm does not match '
            f'sample_thickness_cm: {fixed_thickness_cm:.12g} vs {configured:.12g}'
        )
    return ThicknessDerivationInfo(
        source_path=source,
        sha256=sha256,
        fixed_thickness_cm=fixed_thickness_cm,
        payload=payload,
        content=content,
    )


def _required_derivation_number(
    mapping: dict[str, Any],
    field_name: str,
    *,
    context: str = 'thickness derivation',
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    value = mapping.get(field_name)
    if isinstance(value, bool):
        raise ValueError(f'{context} {field_name} must be a finite number')
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{context} {field_name} must be a finite number') from exc
    if not math.isfinite(numeric):
        raise ValueError(f'{context} {field_name} must be a finite number')
    if positive and numeric <= 0:
        raise ValueError(f'{context} {field_name} must be finite and > 0')
    if nonnegative and numeric < 0:
        raise ValueError(f'{context} {field_name} must be finite and >= 0')
    return numeric


def _required_positive_derivation_mapping(
    payload: dict[str, Any], field_name: str
) -> dict[str, float]:
    raw = payload.get(field_name)
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f'thickness derivation {field_name} must be a non-empty object')
    values: dict[str, float] = {}
    for element, value in raw.items():
        if not isinstance(element, str) or not element.strip():
            raise ValueError(
                f'thickness derivation {field_name} contains an invalid element key'
            )
        values[element] = _required_derivation_number(
            raw,
            element,
            context=f'thickness derivation {field_name}',
            positive=True,
        )
    return values


def _validate_thickness_derivation_physics(payload: dict[str, Any]) -> None:
    required_strings = (
        'schema',
        'method',
        'parameter_source',
        'uncertainty_status',
        'mass_attenuation_model',
        'mass_attenuation_model_formula',
        'density_model',
        'density_model_formula',
        'mu_model',
        'mu_model_formula',
    )
    for field_name in required_strings:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f'thickness derivation {field_name} must be a non-empty string'
            )
    if payload['parameter_source'] != 'composition_model_derived':
        raise ValueError(
            "thickness derivation parameter_source must be 'composition_model_derived'"
        )
    if payload['uncertainty_status'] not in {'partial', 'complete'}:
        raise ValueError(
            "thickness derivation uncertainty_status must be 'partial' or 'complete'"
        )
    material = payload.get('material')
    if not isinstance(material, str) or not material.strip():
        raise ValueError('thickness derivation material must be a non-empty string')

    energy = _required_derivation_number(payload, 'energy_kev', positive=True)
    table_energy = _required_derivation_number(
        payload, 'nist_table_energy_kev', positive=True
    )
    if not math.isclose(table_energy, 30.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError('thickness derivation NIST table energy must equal 30 keV')
    if not math.isclose(energy, table_energy, rel_tol=0.0, abs_tol=0.001):
        raise ValueError(
            'thickness derivation experimental energy is not within 0.001 keV '
            'of the nearest NIST table point'
        )

    composition = _required_positive_derivation_mapping(
        payload, 'composition_wt_percent'
    )
    if not math.isclose(
        math.fsum(composition.values()), 100.0, rel_tol=0.0, abs_tol=1e-8
    ):
        raise ValueError('thickness derivation composition wt% must sum to 100')
    element_mu_rho = _required_positive_derivation_mapping(
        payload, 'nist_element_mass_attenuation_cm2_g_at_30kev'
    )
    element_density = _required_positive_derivation_mapping(
        payload, 'nist_element_density_g_cm3'
    )
    element_keys = set(composition)
    if set(element_mu_rho) != element_keys or set(element_density) != element_keys:
        raise ValueError(
            'thickness derivation composition and NIST element tables must have identical keys'
        )

    fractions = {element: wt_percent / 100.0 for element, wt_percent in composition.items()}
    expected_mu_rho = math.fsum(
        fractions[element] * element_mu_rho[element] for element in element_keys
    )
    expected_density = 1.0 / math.fsum(
        fractions[element] / element_density[element] for element in element_keys
    )
    recorded_mu_rho = _required_derivation_number(
        payload, 'mixture_mass_attenuation_cm2_g', positive=True
    )
    alias_mu_rho = _required_derivation_number(
        payload, 'mass_attenuation_cm2_g', positive=True
    )
    recorded_density = _required_derivation_number(
        payload, 'ideal_mixture_density_g_cm3', positive=True
    )
    if not math.isclose(
        recorded_mu_rho, expected_mu_rho, rel_tol=1e-8, abs_tol=5e-7
    ):
        raise ValueError('thickness derivation mixture mass attenuation is inconsistent')
    if not math.isclose(
        alias_mu_rho, recorded_mu_rho, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError('thickness derivation mass attenuation alias is inconsistent')
    if not math.isclose(
        recorded_density, expected_density, rel_tol=1e-8, abs_tol=5e-7
    ):
        raise ValueError('thickness derivation ideal mixture density is inconsistent')

    recorded_mu = _required_derivation_number(payload, 'mu_cm_inv', positive=True)
    expected_mu = expected_mu_rho * expected_density
    if not math.isclose(recorded_mu, expected_mu, rel_tol=1e-8, abs_tol=5e-7):
        raise ValueError('thickness derivation linear mu is inconsistent')
    representative = _required_derivation_number(
        payload, 'representative_transmission', positive=True
    )
    if representative >= 1:
        raise ValueError(
            'thickness derivation representative_transmission must be < 1'
        )
    fixed_thickness = _required_derivation_number(
        payload, 'fixed_thickness_cm', positive=True
    )
    expected_thickness = -math.log(representative) / recorded_mu
    if not math.isclose(
        fixed_thickness, expected_thickness, rel_tol=1e-9, abs_tol=1e-12
    ):
        raise ValueError('thickness derivation fixed thickness is inconsistent')

    statistics = payload.get('transmission_statistics')
    if not isinstance(statistics, dict):
        raise ValueError('thickness derivation transmission_statistics must be an object')
    count = statistics.get('count')
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError(
            'thickness derivation transmission_statistics.count must be an integer > 0'
        )
    median = _required_derivation_number(
        statistics,
        'median',
        context='thickness derivation transmission_statistics',
        positive=True,
    )
    mad = _required_derivation_number(
        statistics,
        'mad',
        context='thickness derivation transmission_statistics',
        nonnegative=True,
    )
    p5 = _required_derivation_number(
        statistics,
        'p5',
        context='thickness derivation transmission_statistics',
        positive=True,
    )
    p95 = _required_derivation_number(
        statistics,
        'p95',
        context='thickness derivation transmission_statistics',
        positive=True,
    )
    if max(median, p5, p95) > 1 or not p5 <= median <= p95:
        raise ValueError('thickness derivation transmission quantiles are inconsistent')
    if not math.isclose(representative, median, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            'thickness derivation representative transmission does not equal median'
        )
    relative_span = statistics.get('relative_p5_p95_span')
    if relative_span is not None:
        recorded_span = _required_derivation_number(
            statistics,
            'relative_p5_p95_span',
            context='thickness derivation transmission_statistics',
            nonnegative=True,
        )
        expected_span = (p95 - p5) / median
        if not math.isclose(
            recorded_span, expected_span, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ValueError(
                'thickness derivation transmission relative span is inconsistent'
            )
    if mad > 1:
        raise ValueError('thickness derivation transmission MAD is inconsistent')

    warnings = payload.get('warnings')
    if not isinstance(warnings, list) or not all(
        isinstance(item, str) for item in warnings
    ):
        raise ValueError('thickness derivation warnings must be a list of strings')


def _load_run_control_inputs(config: BL19B2Abs2DConfig) -> RunControlInputs:
    inputs = RunControlInputs(
        include_manifest=_load_include_manifest(config),
        thickness_derivation=_load_thickness_derivation(config),
    )
    derivation = inputs.thickness_derivation
    if derivation is None:
        return inputs
    manifest = inputs.include_manifest
    if manifest is None:
        raise ValueError(
            'thickness derivation requires an include manifest for one sample folder'
        )
    folder = derivation.payload.get('folder')
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError('thickness derivation must contain a non-empty folder field')
    normalized = folder.strip().replace('\\', '/')
    if '/' in normalized or normalized in {'.', '..'}:
        raise ValueError('thickness derivation folder must be one relative directory name')
    input_folder = Path(config.input_root).resolve().name
    if normalized.casefold() != input_folder.casefold():
        raise ValueError(
            f'thickness derivation folder does not match input_root: '
            f'{folder!r} vs {input_folder!r}'
        )
    _validate_thickness_derivation_physics(derivation.payload)
    return inputs


def _copy_control_input(
    *, content: bytes, sha256: str, target: Path, overwrite: bool
) -> Path:
    if target.exists():
        if not target.is_file() or _file_sha256(target) != sha256:
            if not overwrite:
                raise ValueError(
                    f'existing provenance input differs from current source: {target}'
                )
        else:
            return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _copy_run_control_inputs(
    config: BL19B2Abs2DConfig,
    inputs: RunControlInputs,
) -> tuple[BL19B2Abs2DConfig, RunControlInputs]:
    target_dir = config.resolved_output_root() / 'config' / 'inputs'
    include = inputs.include_manifest
    derivation = inputs.thickness_derivation
    if include is not None:
        copied = _copy_control_input(
            content=include.content,
            sha256=include.sha256,
            target=target_dir / 'include_manifest.csv',
            overwrite=config.overwrite,
        )
        include = replace(include, copied_path=copied)
    if derivation is not None:
        copied = _copy_control_input(
            content=derivation.content,
            sha256=derivation.sha256,
            target=target_dir / 'thickness_derivation.json',
            overwrite=config.overwrite,
        )
        derivation = replace(derivation, copied_path=copied)
    copied_inputs = RunControlInputs(
        include_manifest=include, thickness_derivation=derivation
    )
    return (
        replace(
            config,
            include_manifest_path=(include.copied_path if include is not None else None),
            thickness_derivation_path=(
                derivation.copied_path if derivation is not None else None
            ),
        ),
        copied_inputs,
    )


def _control_inputs_signature_payload(inputs: RunControlInputs) -> dict[str, Any]:
    include = inputs.include_manifest
    derivation = inputs.thickness_derivation
    return {
        'include_manifest': (
            {'sha256': include.sha256, 'row_count': len(include.relative_paths)}
            if include is not None
            else None
        ),
        'thickness_derivation': (
            {
                'sha256': derivation.sha256,
                'fixed_thickness_cm': derivation.fixed_thickness_cm,
                'payload': derivation.payload,
            }
            if derivation is not None
            else None
        ),
    }


def _control_inputs_provenance_payload(inputs: RunControlInputs) -> dict[str, Any]:
    payload = _control_inputs_signature_payload(inputs)
    include = inputs.include_manifest
    derivation = inputs.thickness_derivation
    if include is not None:
        payload['include_manifest'].update(
            {
                'source_path': str(include.source_path),
                'copied_path': str(include.copied_path or ''),
            }
        )
    if derivation is not None:
        payload['thickness_derivation'].update(
            {
                'source_path': str(derivation.source_path),
                'copied_path': str(derivation.copied_path or ''),
            }
        )
    return payload


def _header_identity(header: BL19B2Header) -> dict[str, Any]:
    return {
        "exposure_s": header.exposure_s,
        "monitor": header.monitor,
        "transmission": header.transmission,
        "energy_kev": header.energy_kev,
        "distance_mm": header.distance_mm,
        "beam_x_px": header.beam_x_px,
        "beam_y_px": header.beam_y_px,
        "pixel_size_m": header.pixel_size_m,
        "raw_fields": dict(sorted(header.raw_fields.items())),
    }


def _source_identity(path: str | Path, header: BL19B2Header | None = None) -> dict[str, Any]:
    """Capture a stable source identity without loading detector pixels."""
    source = Path(path)
    if header is None:
        before = _stable_file_fingerprint(source)
        parsed_header = read_tiff_header(source)
        after = _stable_file_fingerprint(source)
        if before != after:
            raise SourceChangedDuringReadError(
                f"detector source changed while its header was being read: {source}"
            )
        fingerprint = after
    else:
        parsed_header = header
        fingerprint = _stable_file_fingerprint(source)
    return {
        "sha256": fingerprint["sha256"],
        "size_bytes": fingerprint["size_bytes"],
        "header": _header_identity(parsed_header),
    }


def capture_detector_source(path: str | Path) -> DetectorSourceSnapshot:
    """Read pixels/header and bind them to one stable, content-hashed source state."""
    source = Path(path)
    before = _stable_file_fingerprint(source)
    header = read_tiff_header(source)
    image = np.array(read_detector_image(source), dtype=np.float64, copy=True, order="C")
    after = _stable_file_fingerprint(source)
    if before != after:
        raise SourceChangedDuringReadError(
            f"detector source changed while pixels/header were being read: {source}"
        )
    identity = {
        "sha256": after["sha256"],
        "size_bytes": after["size_bytes"],
        "header": _header_identity(header),
    }
    return DetectorSourceSnapshot(
        path=source,
        image=image,
        header=header,
        identity=identity,
    )


def _frame_signature(processing_signature: str, source_identity: dict[str, Any]) -> str:
    payload = {
        "processing_signature": processing_signature,
        "source_identity": source_identity,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _array_sha256(image: np.ndarray) -> str:
    arr = np.asarray(image)
    canonical = np.ascontiguousarray(arr.astype(arr.dtype.name, copy=False))
    h = hashlib.sha256()
    h.update(str(canonical.shape).encode("ascii"))
    h.update(canonical.dtype.name.encode("ascii"))
    h.update(canonical.tobytes(order="C"))
    return h.hexdigest()


def _write_edf_array(path: Path, data: np.ndarray, header: dict[str, str] | None = None) -> None:
    try:
        from fabio.edfimage import EdfImage
    except ImportError as exc:  # pragma: no cover
        raise ImportError("fabio is required for BL19B2 EDF output") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    EdfImage(data=data, header=header or {}).write(str(path))


def load_and_write_mask(
    *,
    safe_poni_path: Path,
    dark: np.ndarray,
    reference_paths: ReferencePaths,
    config: BL19B2Abs2DConfig,
) -> MaskInfo:
    try:
        import pyFAI
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pyFAI is required for BL19B2 mask export") from exc

    ai = pyFAI.load(str(safe_poni_path))
    detector_mask = getattr(ai.detector, "mask", None)
    user_mask: np.ndarray | None = None
    user_mask_path: Path | None = None
    if reference_paths.mask is not None and reference_paths.mask.is_file():
        user_mask_path = reference_paths.mask
        user_mask = read_detector_image(user_mask_path)
    mask, counts = build_combined_mask(
        detector_mask,
        user_mask,
        dark,
        dark_hot_pixel_threshold=config.dark_hot_pixel_threshold,
    )
    out_root = config.resolved_output_root()
    npy_path = out_root / "masks" / "bl19b2_mask.npy"
    edf_path = out_root / "masks" / "bl19b2_mask.edf"
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(npy_path, mask)
    _write_edf_array(
        edf_path,
        mask,
        header={
            "SAXSAbsSchema": SCHEMA_VERSION,
            "MaskConvention": "pyFAI: 0=valid, 1=masked",
            "MaskSources": "user mask + pyFAI detector mask + abs(dark) > threshold",
            "DarkHotPixelThreshold": f"{float(config.dark_hot_pixel_threshold):.10g}",
        },
    )
    return MaskInfo(
        mask=mask,
        npy_path=npy_path,
        edf_path=edf_path,
        checksum_sha256=_mask_checksum(mask),
        user_mask_path=user_mask_path,
        user_mask_pixels=counts["user_mask_pixels"],
        detector_mask_pixels=counts["detector_mask_pixels"],
        dark_hot_pixels=counts["dark_hot_pixels"],
        combined_mask_pixels=counts["combined_mask_pixels"],
        dark_hot_pixel_threshold=float(config.dark_hot_pixel_threshold),
    )


def _processing_signature_digest(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError('processing_signature_payload must be an object')
    text = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_processing_signature(
    config: BL19B2Abs2DConfig,
    *,
    mask_info: MaskInfo,
    calibration: StandardCalibration,
    safe_poni_path: Path,
    reference_paths: ReferencePaths,
    reference_identities: dict[str, dict[str, Any]] | None = None,
    control_inputs: RunControlInputs | None = None,
) -> tuple[str, dict[str, Any]]:
    monitor_mode = str(config.monitor_mode).strip().lower()
    if control_inputs is None:
        control_inputs = _load_run_control_inputs(config)

    def _reference_sha256(name: str, path: Path) -> str:
        if reference_identities is not None:
            identity = reference_identities.get(name)
            if identity is None or not isinstance(identity.get("sha256"), str):
                raise ValueError(f"missing captured source identity for {name}")
            return str(identity["sha256"])
        return str(_stable_file_fingerprint(path)["sha256"])

    reference_payload = {
        "dark": {
            "path": str(reference_paths.dark),
            "sha256": _reference_sha256("dark", reference_paths.dark),
        },
        "background": {
            "path": str(reference_paths.background),
            "sha256": _reference_sha256("background", reference_paths.background),
        },
        "standard": {
            "path": str(reference_paths.standard),
            "sha256": _reference_sha256("standard", reference_paths.standard),
        },
        "direct": {
            "path": str(reference_paths.direct or ""),
            "sha256": str(_stable_file_fingerprint(reference_paths.direct)["sha256"])
            if reference_paths.direct is not None and reference_paths.direct.is_file()
            else "",
        },
    }
    payload = {
        'run_control_inputs': _control_inputs_signature_payload(control_inputs),
        "schema": SCHEMA_VERSION,
        "formula_version": FORMULA_VERSION,
        "geometry_source": "pydidas_cali_yaml" if config.pydidas_cali_yaml is not None else "poni",
        "safe_poni_checksum_sha256": _file_sha256(safe_poni_path),
        "monitor_mode": monitor_mode,
        "normalization_formula": (
            "exposure_s * MON * ABS" if monitor_mode == "rate" else "MON * ABS"
        ),
        "dark_scaling": "exposure_matched",
        "uncertainty_mask_policy": UNCERTAINTY_MASK_POLICY,
        "mu_cm_inv": config.mu_cm_inv,
        "sample_thickness_cm": config.sample_thickness_cm,
        "transmission_abs_uncertainty": config.transmission_abs_uncertainty,
        **_uncertainty_input_payload(config),
        "alpha": float(config.alpha),
        "q_window": [float(config.q_window[0]), float(config.q_window[1])],
        "npt": int(config.npt),
        "dtype": config.dtype,
        "standard_key": config.standard_key,
        "standard_thickness_cm": float(calibration.standard_thickness_cm),
        "standard_thickness_source": calibration.standard_thickness_source,
        "standard_calibration": _k_calibration_contract(calibration, require_complete=True),
        "correct_solid_angle_for_k": bool(config.correct_solid_angle_for_k),
        "polarization_factor": config.polarization_factor,
        "mask_checksum_sha256": mask_info.checksum_sha256,
        "dark_hot_pixel_threshold": float(config.dark_hot_pixel_threshold),
        "reference_files": reference_payload,
    }
    return _processing_signature_digest(payload), payload


def _provenance_paths(out_root: Path) -> ProvenancePaths:
    config_dir = out_root / "config"
    return ProvenancePaths(
        run_command=config_dir / "run_command.ps1",
        processing_environment=config_dir / "processing_environment.json",
        code_state=config_dir / "code_state.txt",
        provenance_summary=config_dir / "provenance_summary.json",
    )


def _package_version(distribution_name: str) -> str | None:
    try:
        return importlib_metadata.version(distribution_name)
    except importlib_metadata.PackageNotFoundError:
        return None


def collect_software_versions() -> dict[str, Any]:
    try:
        import saxsabs

        saxsabs_version = getattr(saxsabs, "__version__", None)
    except Exception:
        saxsabs_version = _package_version("saxsabs")
    packages = {
        "saxsabs": saxsabs_version,
        "numpy": np.__version__,
        "pyFAI": _package_version("pyFAI"),
        "fabio": _package_version("fabio"),
        "h5py": _package_version("h5py"),
        "tifffile": _package_version("tifffile"),
        "matplotlib": _package_version("matplotlib"),
    }
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
    }


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git_output(args: list[str], cwd: Path, *, timeout_s: int = 30) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except Exception as exc:
        return f"<git command failed: {exc}>"
    text = (result.stdout or "").strip()
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        return text or f"<git {' '.join(args)} failed: {err}>"
    return text


def collect_code_state(repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _default_repo_root()
    if not (root / ".git").exists():
        return {
            "repo_root": str(root),
            "available": False,
            "status": "unknown",
            "reason": ".git directory not found",
        }
    status_short = _git_output(["status", "--short"], root)
    dirty = bool(status_short.strip())
    untracked_files = _git_output(["ls-files", "--others", "--exclude-standard"], root) if dirty else ""
    untracked_snapshots: list[dict[str, str]] = []
    for rel_path in [line.strip() for line in untracked_files.splitlines() if line.strip()]:
        candidate = root / rel_path
        if candidate.suffix.lower() not in (".py", ".md", ".yml", ".yaml", ".toml", ".txt"):
            continue
        try:
            if candidate.is_file() and candidate.stat().st_size <= 256_000:
                untracked_snapshots.append(
                    {
                        "path": rel_path,
                        "content": candidate.read_text(encoding="utf-8", errors="replace"),
                    }
                )
        except OSError:
            continue
    return {
        "repo_root": str(root),
        "available": True,
        "branch": _git_output(["branch", "--show-current"], root),
        "commit": _git_output(["rev-parse", "HEAD"], root),
        "status": "dirty" if dirty else "clean",
        "status_short": status_short,
        "diff_stat": _git_output(["diff", "--stat"], root) if dirty else "",
        "diff": _git_output(["diff"], root, timeout_s=120) if dirty else "",
        "untracked_files": untracked_files,
        "untracked_file_snapshots": untracked_snapshots,
    }


def format_code_state_text(code_state: dict[str, Any]) -> str:
    lines = [
        "# SAXSAbs code state",
        f"generated_at: {_dt.datetime.now().isoformat(timespec='seconds')}",
        f"repo_root: {code_state.get('repo_root', '')}",
        f"available: {code_state.get('available', '')}",
        f"branch: {code_state.get('branch', '')}",
        f"commit: {code_state.get('commit', '')}",
        f"status: {code_state.get('status', '')}",
        "",
        "## git status --short",
        str(code_state.get("status_short", "")),
        "",
        "## git diff --stat",
        str(code_state.get("diff_stat", "")),
        "",
        "## untracked files",
        str(code_state.get("untracked_files", "")),
        "",
        "## git diff",
        str(code_state.get("diff", "")),
        "",
        "## untracked file snapshots",
    ]
    for item in code_state.get("untracked_file_snapshots", []) or []:
        lines.extend(
            [
                f"### {item.get('path', '')}",
                "```",
                str(item.get("content", "")),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _ps_single_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _optional_path_text(value: str | Path | None) -> str:
    return "" if value is None else str(Path(value))


def _rerun_hash_preflight_lines(
    *, variable: str, path: Path, expected_sha256: str, label: str
) -> list[str]:
    expected_variable = f'expected{variable[0].upper()}{variable[1:]}Sha256'
    actual_variable = f'actual{variable[0].upper()}{variable[1:]}Sha256'
    return [
        f'${variable} = {_ps_single_quote(path)}',
        f'${expected_variable} = {_ps_single_quote(expected_sha256)}',
        (
            f"if (-not (Test-Path -LiteralPath ${variable} -PathType Leaf)) "
            f"{{ throw {_ps_single_quote(label + ' is missing or not a file')} }}"
        ),
        (
            f'${actual_variable} = (Get-FileHash -Algorithm SHA256 '
            f'-LiteralPath ${variable}).Hash.ToLowerInvariant()'
        ),
        (
            f'if (${actual_variable} -ne ${expected_variable}) '
            f"{{ throw {_ps_single_quote(label + ' SHA256 mismatch')} }}"
        ),
    ]


def build_rerun_command(
    config: BL19B2Abs2DConfig,
    *,
    poni_path: Path | None = None,
    control_inputs: RunControlInputs | None = None,
) -> str:
    qmin, qmax = config.q_window
    monitor_mode = str(config.monitor_mode).strip().lower()
    lines = ["$env:PYTHONPATH='src'"]
    if control_inputs is not None:
        include = control_inputs.include_manifest
        derivation = control_inputs.thickness_derivation
        if include is not None:
            include_path = Path(
                config.include_manifest_path
                or include.copied_path
                or include.source_path
            )
            lines.extend(
                _rerun_hash_preflight_lines(
                    variable='includeManifest',
                    path=include_path,
                    expected_sha256=include.sha256,
                    label='include manifest',
                )
            )
        if derivation is not None:
            derivation_path = Path(
                config.thickness_derivation_path
                or derivation.copied_path
                or derivation.source_path
            )
            lines.extend(
                _rerun_hash_preflight_lines(
                    variable='thicknessDerivation',
                    path=derivation_path,
                    expected_sha256=derivation.sha256,
                    label='thickness derivation',
                )
            )
    lines.extend(
        [
        f"& {_ps_single_quote(sys.executable)} -m saxsabs.cli bl19b2-abs2d `",
        f"  --input-root {_ps_single_quote(Path(config.input_root))} `",
        ]
    )
    if config.pydidas_cali_yaml is not None:
        lines.append(f"  --pydidas-cali-yaml {_ps_single_quote(Path(config.pydidas_cali_yaml))} `")
    else:
        source_poni = Path(poni_path) if poni_path is not None else Path(config.poni_path)
        lines.append(f"  --poni {_ps_single_quote(source_poni)} `")
    if config.mask_path is not None:
        lines.append(f"  --mask {_ps_single_quote(Path(config.mask_path))} `")
    if config.dark_path is not None:
        lines.append(f"  --dark {_ps_single_quote(Path(config.dark_path))} `")
    if config.background_path is not None:
        lines.append(f"  --background {_ps_single_quote(Path(config.background_path))} `")
    if config.standard_path is not None:
        lines.append(f"  --standard {_ps_single_quote(Path(config.standard_path))} `")
    if config.direct_path is not None:
        lines.append(f"  --direct-beam {_ps_single_quote(Path(config.direct_path))} `")
    if config.include_manifest_path is not None:
        lines.append(
            f'  --include-manifest {_ps_single_quote(Path(config.include_manifest_path))} `'
        )
    if config.thickness_derivation_path is not None:
        lines.append(
            '  --thickness-derivation-json '
            f'{_ps_single_quote(Path(config.thickness_derivation_path))} `'
        )
    lines.extend(
        [
            f"  --output-root {_ps_single_quote(config.resolved_output_root())} `",
            f"  --monitor-mode {monitor_mode} `",
            f"  --alpha {float(config.alpha):.10g} `",
            f"  --qmin {float(qmin):.10g} `",
            f"  --qmax {float(qmax):.10g} `",
            f"  --npt {int(config.npt)} `",
            f"  --dtype {config.dtype} `",
            f"  --standard-key {_ps_single_quote(config.standard_key)} `",
            (
                "  --correct-solid-angle-for-k `"
                if config.correct_solid_angle_for_k
                else "  --no-correct-solid-angle-for-k `"
            ),
            (
                "  --no-polarization-correction `"
                if config.polarization_factor is None
                else f"  --polarization-factor {float(config.polarization_factor):.10g} `"
            ),
            f"  --dark-hot-pixel-threshold {float(config.dark_hot_pixel_threshold):.10g}",
        ]
    )
    lines[-1] += " `"
    if config.mu_cm_inv is not None:
        lines.append(f"  --mu {float(config.mu_cm_inv):.10g}")
    else:
        lines.append(f"  --sample-thickness-cm {float(config.sample_thickness_cm):.10g}")
    if config.transmission_abs_uncertainty is not None:
        lines[-1] += " `"
        lines.append(
            "  --transmission-abs-uncertainty "
            f"{float(config.transmission_abs_uncertainty):.10g}"
        )
    uncertainty_cli = (
        (
            "--standard-transmission-abs-uncertainty",
            config.standard_transmission_abs_uncertainty,
        ),
        (
            "--standard-monitor-relative-standard-uncertainty",
            config.standard_monitor_relative_standard_uncertainty,
        ),
        (
            "--calibration-background-monitor-relative-standard-uncertainty",
            config.calibration_background_monitor_relative_standard_uncertainty,
        ),
        ("--system-coverage-factor", config.system_coverage_factor),
        (
            "--monitor-relative-standard-uncertainty",
            config.monitor_relative_standard_uncertainty,
        ),
        (
            "--sample-thickness-relative-standard-uncertainty",
            config.sample_thickness_relative_standard_uncertainty,
        ),
        (
            "--standard-thickness-relative-standard-uncertainty",
            config.standard_thickness_relative_standard_uncertainty,
        ),
        ("--mu-relative-standard-uncertainty", config.mu_relative_standard_uncertainty),
        ("--alpha-standard-uncertainty", config.alpha_standard_uncertainty),
    )
    for option, value in uncertainty_cli:
        if value is not None:
            lines[-1] += " `"
            lines.append(f"  {option} {float(value):.10g}")
    if config.standard_thickness_cm is not None:
        lines[-1] += " `"
        lines.append(f"  --standard-thickness-cm {float(config.standard_thickness_cm):.10g}")

    execution_options = []
    if config.max_frames is not None:
        execution_options.append(f"--max-frames {int(config.max_frames)}")
    if config.dry_run:
        execution_options.append("--dry-run")
    if config.overwrite:
        execution_options.append("--overwrite")
    if not config.write_preview:
        execution_options.append("--no-preview")
    for option in execution_options:
        lines[-1] += " `"
        lines.append(f"  {option}")
    return "\n".join(lines) + "\n"


def write_provenance_package(
    *,
    config: BL19B2Abs2DConfig,
    safe_poni_path: Path,
    reference_paths: ReferencePaths,
    mask_info: MaskInfo,
    calibration: StandardCalibration,
    processing_signature: str,
    signature_payload: dict[str, Any],
    counts: dict[str, int],
    software_versions: dict[str, Any],
    code_state: dict[str, Any],
    run_status: str,
    control_inputs: RunControlInputs | None = None,
) -> ProvenancePaths:
    out_root = config.resolved_output_root()
    paths = _provenance_paths(out_root)
    paths.run_command.parent.mkdir(parents=True, exist_ok=True)
    if control_inputs is None:
        control_inputs = _load_run_control_inputs(config)
    paths.run_command.write_text(
        build_rerun_command(
            config,
            poni_path=safe_poni_path,
            control_inputs=control_inputs,
        ),
        encoding="utf-8",
    )
    _write_json(paths.processing_environment, software_versions)
    paths.code_state.write_text(format_code_state_text(code_state), encoding="utf-8")
    summary = {
        'run_control_inputs': _control_inputs_provenance_payload(control_inputs),
        "schema": SCHEMA_VERSION,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "run_status": run_status,
        "input_root": str(Path(config.input_root)),
        "output_root": str(out_root),
        "source_poni_path": _optional_path_text(config.poni_path),
        "pydidas_cali_yaml": _optional_path_text(config.pydidas_cali_yaml),
        "safe_poni_path": str(safe_poni_path),
        "references": {
            "dark": str(reference_paths.dark),
            "background": str(reference_paths.background),
            "standard": str(reference_paths.standard),
            "direct": str(reference_paths.direct or ""),
            "user_mask": str(reference_paths.mask or ""),
        },
        "mask": {
            "npy": str(mask_info.npy_path),
            "edf": str(mask_info.edf_path),
            "checksum_sha256": mask_info.checksum_sha256,
            "user_mask_pixels": mask_info.user_mask_pixels,
            "detector_mask_pixels": mask_info.detector_mask_pixels,
            "dark_hot_pixels": mask_info.dark_hot_pixels,
            "combined_mask_pixels": mask_info.combined_mask_pixels,
        },
        "processing_signature": processing_signature,
        "processing_signature_payload": signature_payload,
        "uncertainty_inputs": _uncertainty_input_payload(config),
        "standard_calibration": {
            **_k_calibration_contract(calibration, require_complete=True),
            "q_min_overlap": calibration.q_min_overlap,
            "q_max_overlap": calibration.q_max_overlap,
            "points_used": calibration.points_used,
            "points_total": calibration.points_total,
            "standard_thickness_cm": calibration.standard_thickness_cm,
            "standard_thickness_source": calibration.standard_thickness_source,
        },
        "counts": dict(counts),
        "software_versions": software_versions,
        "code_state": {
            "status": code_state.get("status"),
            "branch": code_state.get("branch"),
            "commit": code_state.get("commit"),
            "repo_root": code_state.get("repo_root"),
            "details": str(paths.code_state),
        },
        "files": {
            "run_command": str(paths.run_command),
            "processing_environment": str(paths.processing_environment),
            "code_state": str(paths.code_state),
            "provenance_summary": str(paths.provenance_summary),
        },
    }
    _write_json(paths.provenance_summary, summary)
    return paths


def build_provenance_metadata(
    *,
    provenance_paths: ProvenancePaths,
    software_versions: dict[str, Any],
    code_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "software_versions": software_versions,
        "code_state_ref": str(provenance_paths.code_state),
        "code_state_status": code_state.get("status", "unknown"),
        "provenance": {
            "run_command": str(provenance_paths.run_command),
            "processing_environment": str(provenance_paths.processing_environment),
            "code_state": str(provenance_paths.code_state),
            "provenance_summary": str(provenance_paths.provenance_summary),
        },
    }


def update_metadata_provenance(
    metadata_path: Path,
    *,
    provenance_paths: ProvenancePaths,
    software_versions: dict[str, Any],
    code_state: dict[str, Any],
) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["last_resume_validation"] = {
        "validated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "validated_by": build_provenance_metadata(
            provenance_paths=provenance_paths,
            software_versions=software_versions,
            code_state=code_state,
        ),
    }
    _write_json(metadata_path, metadata)


def _copy_poni_to_safe_path(config: BL19B2Abs2DConfig) -> Path:
    out_root = config.resolved_output_root()
    target_dir = out_root / "config" / "geometry"
    target = target_dir / "BL19B2_SAXS_Califile.poni"

    if config.pydidas_cali_yaml is not None:
        desired_text = _render_pydidas_poni(config.pydidas_cali_yaml)
        if target.exists() and not config.overwrite:
            if target.read_text(encoding="utf-8") != desired_text:
                raise ValueError(
                    "existing safe PONI differs from the current pydidas calibration; "
                    "use a new output root or explicitly enable overwrite"
                )
            return target
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(desired_text, encoding="utf-8")
        return target

    assert config.poni_path is not None
    source = Path(config.poni_path)
    if target.exists() and not config.overwrite:
        if _file_sha256(source) != _file_sha256(target):
            raise ValueError(
                "existing safe PONI differs from the current source PONI; "
                "use a new output root or explicitly enable overwrite"
            )
        return target
    if not source.is_file():
        raise FileNotFoundError(f"PONI file not found or not a regular file: {source}")
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target

def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        ordered: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in ordered:
                    ordered.append(key)
        fieldnames = ordered
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_processing_config(
    config: BL19B2Abs2DConfig,
    safe_poni: Path,
    *,
    mask_info: MaskInfo | None = None,
    processing_signature: str = "",
    signature_payload: dict[str, Any] | None = None,
    control_inputs: RunControlInputs | None = None,
) -> None:
    out_root = config.resolved_output_root()
    lines = [
        f"schema: {SCHEMA_VERSION}",
        f"input_root: {Path(config.input_root)}",
        f"output_root: {out_root}",
        f"source_poni_path: {_optional_path_text(config.poni_path)}",
        f"pydidas_cali_yaml: {_optional_path_text(config.pydidas_cali_yaml)}",
        f"configured_mask_path: {_optional_path_text(config.mask_path)}",
        f"configured_dark_path: {_optional_path_text(config.dark_path)}",
        f"configured_background_path: {_optional_path_text(config.background_path)}",
        f"configured_standard_path: {_optional_path_text(config.standard_path)}",
        f"configured_direct_path: {_optional_path_text(config.direct_path)}",
        f"safe_poni_path: {safe_poni}",
        f"mu_cm_inv: {config.mu_cm_inv}",
        f"sample_thickness_cm: {config.sample_thickness_cm}",
        f"monitor_mode: {config.monitor_mode}",
        f"transmission_abs_uncertainty: {config.transmission_abs_uncertainty}",
        "monitor_relative_standard_uncertainty: "
        f"{config.monitor_relative_standard_uncertainty}",
        "sample_thickness_relative_standard_uncertainty: "
        f"{config.sample_thickness_relative_standard_uncertainty}",
        "standard_thickness_relative_standard_uncertainty: "
        f"{config.standard_thickness_relative_standard_uncertainty}",
        "standard_transmission_abs_uncertainty: "
        f"{config.standard_transmission_abs_uncertainty}",
        "standard_monitor_relative_standard_uncertainty: "
        f"{config.standard_monitor_relative_standard_uncertainty}",
        "calibration_background_monitor_relative_standard_uncertainty: "
        f"{config.calibration_background_monitor_relative_standard_uncertainty}",
        f"system_coverage_factor: {config.system_coverage_factor}",
        f"mu_relative_standard_uncertainty: {config.mu_relative_standard_uncertainty}",
        f"alpha_standard_uncertainty: {config.alpha_standard_uncertainty}",
        f"alpha: {config.alpha}",
        f"standard_key: {config.standard_key}",
        f"q_window: [{config.q_window[0]}, {config.q_window[1]}]",
        f"npt: {config.npt}",
        f"dtype: {config.dtype}",
        f"dry_run: {str(config.dry_run).lower()}",
        f"max_frames: {config.max_frames if config.max_frames is not None else ''}",
        f"overwrite: {str(config.overwrite).lower()}",
        f"dark_hot_pixel_threshold: {config.dark_hot_pixel_threshold}",
        "normalization_formula: "
        + ("exposure_s * MON * ABS" if config.monitor_mode == "rate" else "MON * ABS"),
        "thickness_formula: configured fixed thickness or -ln(ABS) / mu_cm_inv",
        "dark_scaling: exposure_matched",
        "corrected_2d_formula: ((S-dark*exp_s/exp_dark)/N_s - alpha*(BG-dark*exp_bg/exp_dark)/(I0_bg[ * exp_bg])) * K / d_cm",
        "solid_angle_applied_in_image: false",
        "polarization_applied_in_image: false",
    ]
    if control_inputs is not None:
        lines.append(
            'run_control_inputs_json: '
            + json.dumps(_control_inputs_provenance_payload(control_inputs), sort_keys=True)
        )
    if mask_info is not None:
        lines.extend(
            [
                f"mask_npy: {mask_info.npy_path}",
                f"mask_edf: {mask_info.edf_path}",
                f"mask_checksum_sha256: {mask_info.checksum_sha256}",
                f"user_mask_path: {mask_info.user_mask_path or ''}",
                f"user_mask_pixels: {mask_info.user_mask_pixels}",
                f"detector_mask_pixels: {mask_info.detector_mask_pixels}",
                f"dark_hot_pixels: {mask_info.dark_hot_pixels}",
                f"combined_mask_pixels: {mask_info.combined_mask_pixels}",
            ]
        )
    if processing_signature:
        lines.append(f"processing_signature: {processing_signature}")
    if signature_payload:
        lines.append("processing_signature_payload_json: " + json.dumps(signature_payload, sort_keys=True))
    path = out_root / "config" / "processing_config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def scan_inputs(
    config: BL19B2Abs2DConfig,
    *,
    include_manifest: IncludeManifestInfo | None = None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Scan TIFF inputs and return inventory rows plus candidate sample paths."""
    root = Path(config.input_root)
    if not root.exists():
        raise FileNotFoundError(f"input_root does not exist: {root}")
    rows: list[dict[str, Any]] = []
    sample_paths: list[Path] = []
    manifest = include_manifest
    if manifest is None:
        manifest = _load_include_manifest(config)
    included_keys = (
        {_manifest_path_key(path) for path in manifest.relative_paths}
        if manifest is not None
        else None
    )
    refs = find_reference_paths(
        root,
        mask_path=config.mask_path,
        pydidas_cali_yaml=config.pydidas_cali_yaml,
        dark_path=config.dark_path,
        background_path=config.background_path,
        standard_path=config.standard_path,
        direct_path=config.direct_path,
    )
    reference_set = {refs.dark.resolve(), refs.background.resolve(), refs.standard.resolve()}
    if refs.direct is not None and refs.direct.exists():
        reference_set.add(refs.direct.resolve())
    if refs.mask is not None and refs.mask.exists():
        reference_set.add(refs.mask.resolve())

    for path in sorted(root.rglob("*"), key=natural_key):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        ext = path.suffix.lower()
        if ext not in (".tif", ".tiff"):
            if ext in (".csv", ".dat", ".py", ".bat", ".7z", ".asc", ".json"):
                rows.append(
                    {
                        "relative_path": str(rel),
                        "kind": "ignored_non_tiff",
                        "status": "ignored",
                        "reason": f"extension {ext} is not raw detector TIFF input",
                    }
                )
            continue

        kind = "sample" if is_sample_tiff(path, root) else "ignored_tiff"
        if path.resolve() in reference_set:
            kind = "reference"
        if kind == 'sample' and included_keys is not None:
            key = _manifest_path_key(rel)
            if key not in included_keys:
                rows.append(
                    {
                        'relative_path': str(rel),
                        'kind': 'sample_not_in_include_manifest',
                        'status': 'ignored',
                        'reason': 'not selected by include manifest',
                    }
                )
                continue
        header = read_tiff_header(path)
        classification = (
            classify_sample_frame(
                header,
                beer_lambert_thickness=config.sample_thickness_cm is None,
                transmission_abs_uncertainty=config.transmission_abs_uncertainty,
            )
            if kind == "sample"
            else FrameClassification("ok")
        )
        if kind == "sample":
            sample_paths.append(path)
        rows.append(
            {
                "relative_path": str(rel),
                "kind": kind,
                "status": classification.status,
                "reason": classification.reason,
                "exposure_s": header.exposure_s,
                "monitor": header.monitor,
                "transmission_abs": header.transmission,
                "energy_kev": header.energy_kev,
                "distance_mm": header.distance_mm,
                "beam_x_px": header.beam_x_px,
                "beam_y_px": header.beam_y_px,
                "pixel_size_m": header.pixel_size_m,
                "size_bytes": path.stat().st_size,
                "mtime": _dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    if manifest is not None:
        discovered = {
            _manifest_path_key(path.relative_to(root)): path for path in sample_paths
        }
        missing = [
            str(relative)
            for relative in manifest.relative_paths
            if _manifest_path_key(relative) not in discovered
        ]
        if missing:
            raise ValueError(
                'include manifest entries were not discovered as sample TIFFs: '
                + '; '.join(missing)
            )
        sample_paths = [
            discovered[_manifest_path_key(relative)]
            for relative in manifest.relative_paths
        ]
    return rows, sample_paths


def _background_transmission(header: BL19B2Header) -> tuple[float, list[str]]:
    warnings: list[str] = []
    trans = header.transmission
    try:
        measured = validate_blank_transmission(
            trans,
            tolerance=BACKGROUND_TRANSMISSION_TOLERANCE,
        )
    except ValueError as exc:
        raise ValueError(f"check the background definition before absolute calibration: {exc}") from exc
    deviation = abs(measured - 1.0)
    if deviation > 0:
        warnings.append(
            f"BG ABS={measured:.6g} recorded for QC only; background transmission is not applied"
        )
    return 1.0, warnings


def calibrate_standard(
    config: BL19B2Abs2DConfig,
    *,
    reference_paths: ReferencePaths,
    safe_poni_path: Path,
    dark: np.ndarray,
    background: np.ndarray,
    dark_header: BL19B2Header,
    mask: np.ndarray,
    background_header: BL19B2Header | None = None,
    standard_image: np.ndarray | None = None,
    standard_header: BL19B2Header | None = None,
) -> tuple[StandardCalibration, np.ndarray]:
    """Estimate K from GC001 and return calibration plus normalized BG image."""
    try:
        import pyFAI
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pyFAI is required for BL19B2 K calibration") from exc

    bg_header = (
        read_tiff_header(reference_paths.background)
        if background_header is None
        else background_header
    )
    std_header = (
        read_tiff_header(reference_paths.standard)
        if standard_header is None
        else standard_header
    )
    std_class = classify_sample_frame(std_header, beer_lambert_thickness=False)
    if std_class.status != "ok":
        raise ValueError(f"standard frame is not usable: {std_class.reason}")
    if not _is_finite_positive(dark_header.exposure_s):
        raise ValueError("dark frame requires Exposure_time for exposure-matched subtraction")
    assert dark_header.exposure_s is not None

    bg_t, warnings = _background_transmission(bg_header)
    if not _is_finite_positive(bg_header.exposure_s) or not _is_finite_positive(bg_header.monitor):
        raise ValueError("background frame requires Exposure_time and MON")
    assert bg_header.exposure_s is not None and bg_header.monitor is not None
    norm_bg = compute_norm_factor(
        bg_header.exposure_s,
        bg_header.monitor,
        1.0,
        config.monitor_mode,
    )

    assert std_header.exposure_s is not None
    assert std_header.monitor is not None
    assert std_header.transmission is not None
    norm_std = compute_norm_factor(
        std_header.exposure_s,
        std_header.monitor,
        std_header.transmission,
        config.monitor_mode,
    )
    std_thickness, std_thickness_source = _resolve_standard_thickness_cm(config)

    standard = (
        read_detector_image(reference_paths.standard)
        if standard_image is None
        else np.asarray(standard_image, dtype=np.float64)
    )
    if standard.shape != dark.shape or background.shape != dark.shape:
        raise ValueError(
            "reference image shape mismatch: "
            f"standard{standard.shape}, background{background.shape}, dark{dark.shape}"
        )
    mask_arr = np.asarray(mask, dtype=np.uint8)
    if mask_arr.shape != dark.shape:
        raise ValueError(f"mask shape mismatch: {mask_arr.shape} vs {dark.shape}")

    bg_net, _ = normalize_dark_corrected_image(
        background,
        dark,
        image_exposure_s=bg_header.exposure_s,
        dark_exposure_s=dark_header.exposure_s,
        monitor=bg_header.monitor,
        transmission=1.0,
        monitor_mode=config.monitor_mode,
    )
    std_normed, _ = normalize_dark_corrected_image(
        standard,
        dark,
        image_exposure_s=std_header.exposure_s,
        dark_exposure_s=dark_header.exposure_s,
        monitor=std_header.monitor,
        transmission=std_header.transmission,
        monitor_mode=config.monitor_mode,
    )
    ai = pyFAI.load(str(safe_poni_path))
    warnings.extend(
        validate_instrument_consistency(
            std_header,
            image_shape=standard.shape,
            integrator=ai,
            label="standard",
        )
    )
    kwargs: dict[str, Any] = {
        "unit": "q_A^-1",
        "correctSolidAngle": bool(config.correct_solid_angle_for_k),
        "mask": mask_arr,
    }
    if config.polarization_factor is not None:
        kwargs["polarization_factor"] = float(config.polarization_factor)
    standard_res = ai.integrate1d(std_normed, int(config.npt), **kwargs)
    background_res = ai.integrate1d(bg_net, int(config.npt), **kwargs)
    q = np.asarray(standard_res.radial, dtype=np.float64)
    standard_profile = np.asarray(standard_res.intensity, dtype=np.float64)
    background_profile = np.asarray(background_res.intensity, dtype=np.float64)
    i_net_vol = (standard_profile - config.alpha * background_profile) / std_thickness

    q_ref, i_ref = _resolve_standard_reference_data(config.standard_key)

    def _estimate_profile_result(profile_per_cm: np.ndarray) -> Any:
        return estimate_k_factor_robust(
            q_meas=q,
            i_meas_per_cm=profile_per_cm,
            q_ref=q_ref,
            i_ref=i_ref,
            q_window=config.q_window,
            standard_thickness_cm=std_thickness,
        )

    k_result = _estimate_profile_result(i_net_vol)
    uncertainty_contract = _build_standard_uncertainty_contract(
        config,
        k_result=k_result,
        standard_profile=standard_profile,
        background_profile=background_profile,
        standard_transmission=std_header.transmission,
        standard_thickness_cm=std_thickness,
        estimate_k_for_profile=lambda profile: float(
            _estimate_profile_result(profile).k_factor
        ),
    )
    calibration = StandardCalibration(
        k_factor=float(k_result.k_factor),
        k_std=float(k_result.k_std),
        q_min_overlap=float(k_result.q_min_overlap),
        q_max_overlap=float(k_result.q_max_overlap),
        points_used=int(k_result.points_used),
        points_total=int(k_result.points_total),
        standard_thickness_cm=float(std_thickness),
        norm_standard=float(norm_std),
        norm_background=float(norm_bg),
        bg_transmission_used=float(bg_t),
        standard_thickness_source=std_thickness_source,
        warnings=tuple(warnings),
        k_statistical_standard_uncertainty=float(
            k_result.k_statistical_standard_uncertainty
        ),
        k_standard_uncertainty=uncertainty_contract["k_standard_uncertainty"],
        k_expanded_uncertainty=uncertainty_contract["k_expanded_uncertainty"],
        coverage_factor=uncertainty_contract["system_coverage_factor"],
        reference_coverage_factor=uncertainty_contract["reference_coverage_factor"],
        uncertainty_status=uncertainty_contract["status"],
        expanded_uncertainty_status=uncertainty_contract["expanded_status"],
        k_independent_standard_uncertainty=uncertainty_contract[
            "k_independent_standard_uncertainty"
        ],
        k_alpha_relative_sensitivity=uncertainty_contract[
            "k_alpha_relative_sensitivity"
        ],
        k_calibration_background_monitor_relative_sensitivity=uncertainty_contract[
            "k_calibration_background_monitor_relative_sensitivity"
        ],
        uncertainty_components=uncertainty_contract["components"],
        uncertainty_unknown_components=tuple(
            uncertainty_contract["unknown_components"]
        ),
        parallelism_max_relative_deviation=(
            k_result.parallelism_max_relative_deviation
        ),
        parallelism_relative_tolerance=k_result.parallelism_relative_tolerance,
        parallelism_check_passed=k_result.parallelism_check_passed,
    )
    return calibration, bg_net


def _coerce_output_dtype(
    image: np.ndarray,
    dtype: str,
    *,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    dtype_n = str(dtype).strip().lower()
    with np.errstate(over="ignore", invalid="ignore"):
        if dtype_n == "float32":
            output = np.asarray(image).astype(np.float32, copy=False)
        elif dtype_n == "float64":
            output = np.asarray(image).astype(np.float64, copy=False)
        else:
            raise ValueError("dtype must be float32 or float64")
    valid_pixels = np.ones(output.shape, dtype=bool)
    if mask is not None:
        mask_arr = np.asarray(mask)
        if mask_arr.shape != output.shape:
            raise ValueError(f"mask shape mismatch: {mask_arr.shape} vs {output.shape}")
        valid_pixels = mask_arr == 0
    if np.any(~np.isfinite(output[valid_pixels])):
        raise ValueError(
            f"{dtype_n} conversion produced non-finite unmasked detector values; "
            "absolute output was not written"
        )
    return output


def _edf_optional_float(value: Any) -> str:
    if value is None:
        return "unknown"
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("EDF calibration values must be finite or null")
    return f"{numeric:.10g}"


def _uncertainty_budget_arrays(
    budget: AbsoluteUncertaintyBudget,
) -> dict[str, np.ndarray]:
    return {
        dataset_name: np.asarray(getattr(budget, attribute), dtype=np.float64)
        for dataset_name, attribute in _UNCERTAINTY_DATASETS.items()
    }


def write_hdf5_image(
    path: Path,
    image: np.ndarray,
    metadata: dict[str, Any],
    uncertainty_budget: AbsoluteUncertaintyBudget | None = None,
) -> None:
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover
        raise ImportError("h5py is required for BL19B2 HDF5 output") from exc

    k_contract = _k_calibration_contract(
        metadata.get("absolute_calibration", {}),
        require_complete=True,
    )
    if uncertainty_budget is None:
        uncertainty_budget = propagate_absolute_uncertainty(
            image,
            coverage_factor=None,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(str(path), "w") as f:
        entry = f.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        entry.attrs["schema"] = SCHEMA_VERSION
        entry.attrs["formula_version"] = FORMULA_VERSION
        entry.attrs["processing_signature"] = str(metadata.get("processing_signature", ""))
        entry.attrs["frame_signature"] = str(metadata.get("frame_signature", ""))
        entry.attrs["k_calibration_json"] = json.dumps(k_contract, sort_keys=True)
        data = entry.create_group("data")
        data.attrs["NX_class"] = "NXdata"
        data.attrs["signal"] = "I_abs_2d"
        selection = metadata.get('sample_selection') or {}
        derivation = metadata.get('thickness', {}).get('derivation') or {}
        entry.attrs['include_manifest_sha256'] = str(selection.get('sha256', ''))
        entry.attrs['thickness_derivation_sha256'] = str(
            derivation.get('sha256', '')
        )
        ds = data.create_dataset(
            "I_abs_2d",
            data=image,
            compression="gzip",
            compression_opts=4,
            shuffle=True,
        )
        ds.attrs["units"] = INTENSITY_UNIT
        ds.attrs["sha256"] = str(metadata.get("output_image", {}).get("sha256", ""))
        ds.attrs["long_name"] = "detector-space absolute corrected SAXS image"
        uncertainty_group = data.create_group("uncertainty")
        uncertainty_group.attrs["schema"] = SCHEMA_VERSION
        uncertainty_group.attrs["formula_version"] = FORMULA_VERSION
        uncertainty_group.attrs["mask_policy"] = str(
            metadata.get("uncertainty", {}).get(
                "mask_policy", UNCERTAINTY_MASK_POLICY
            )
        )
        uncertainty_group.attrs["status"] = str(
            metadata.get("uncertainty", {}).get("status", "unknown")
        )
        uncertainty_group.attrs["expanded_status"] = str(
            metadata.get("uncertainty", {}).get("expanded_status", "unavailable")
        )
        uncertainty_group.attrs["coverage_factor"] = (
            math.nan
            if uncertainty_budget.coverage_factor is None
            else float(uncertainty_budget.coverage_factor)
        )
        uncertainty_group.attrs["unknown_components_json"] = json.dumps(
            list(uncertainty_budget.unknown_components)
        )
        for dataset_name, values in _uncertainty_budget_arrays(uncertainty_budget).items():
            uncertainty_ds = uncertainty_group.create_dataset(
                dataset_name,
                data=values,
                compression="gzip",
                compression_opts=4,
                shuffle=True,
            )
            uncertainty_ds.attrs["units"] = INTENSITY_UNIT
        entry.create_dataset("metadata_json", data=json.dumps(_json_safe(metadata), ensure_ascii=False))


def write_edf_image(path: Path, image: np.ndarray, metadata: dict[str, Any]) -> None:
    calibration = metadata.get("absolute_calibration", {})
    k_contract = _k_calibration_contract(calibration, require_complete=True)
    mask = metadata.get("mask", {})
    thickness = metadata.get("thickness", {})
    normalization = metadata.get("normalization", {})
    dark = metadata.get("dark", {})
    mask = metadata.get("mask", {})
    corrections = metadata.get("corrections_applied_in_image", {})
    selection = metadata.get('sample_selection') or {}
    derivation = metadata.get('thickness', {}).get('derivation') or {}
    header = {
        "SAXSAbsSchema": SCHEMA_VERSION,
        "ImageType": "detector_space_absolute_corrected_2d",
        "IntensityUnit": INTENSITY_UNIT,
        "RawSample": str(metadata.get("raw_sample", "")),
        "ProcessingSignature": str(metadata.get("processing_signature", "")),
        "FrameSignature": str(metadata.get("frame_signature", "")),
        "IncludeManifestSHA256": str(selection.get('sha256', '')),
        "ThicknessDerivationSHA256": str(derivation.get('sha256', '')),
        "FormulaVersion": FORMULA_VERSION,
        "ImageSHA256": str(metadata.get("output_image", {}).get("sha256", "")),
        "OutputDType": str(metadata.get("output_image", {}).get("dtype", "")),
        "OutputShape": "x".join(str(v) for v in metadata.get("output_image", {}).get("shape", [])),
        "KFactor": f"{float(calibration.get('k_factor', math.nan)):.10g}",
        "KStd": _edf_optional_float(k_contract["k_std"]),
        "KStdMeaning": str(k_contract["k_std_semantics"]).replace(";", ""),
        "KStatStdU": _edf_optional_float(k_contract["k_statistical_standard_uncertainty"]),
        "KStandardU": _edf_optional_float(k_contract["k_standard_uncertainty"]),
        "KExpandedU": _edf_optional_float(k_contract["k_expanded_uncertainty"]),
        "KCoverage": _edf_optional_float(k_contract["coverage_factor"]),
        "ThicknessCm": f"{float(thickness.get('thickness_cm', math.nan)):.10g}",
        "NormSample": f"{float(normalization.get('norm_sample', math.nan)):.10g}",
        "TransmissionAbs": f"{float(normalization.get('transmission_abs', math.nan)):.10g}",
        "ExposureSample": f"{float(normalization.get('exposure_s', math.nan)):.10g}",
        "DarkExposure": f"{float(dark.get('exposure_s', math.nan)):.10g}",
        "MaskPath": str(mask.get("edf", "")),
        "SolidAngleAppliedInImage": str(bool(corrections.get("solid_angle", False))).lower(),
        "PolarizationAppliedInImage": str(bool(corrections.get("polarization", False))).lower(),
        "MonitorMode": str(normalization.get("monitor_mode", "unknown")),
        "Normalization": str(normalization.get("formula", "unknown")),
        "UncertaintyStatus": str(metadata.get("uncertainty", {}).get("status", "unknown")),
        "ExpandedUStatus": str(
            metadata.get("uncertainty", {}).get("expanded_status", "unavailable")
        ),
        "UncertaintyHDF5": str(metadata.get("outputs", {}).get("hdf5", "")),
    }
    _write_edf_array(path, image, header=header)


def _unmasked_pixel_selector(
    image: np.ndarray,
    detector_mask: np.ndarray | None,
) -> np.ndarray:
    selector = np.ones(np.asarray(image).shape, dtype=bool)
    if detector_mask is None:
        return selector
    mask = np.asarray(detector_mask, dtype=bool)
    if mask.shape != selector.shape:
        raise ValueError(
            f"detector_mask shape mismatch: {mask.shape} vs {selector.shape}"
        )
    return ~mask


def write_preview_png(
    path: Path,
    image: np.ndarray,
    *,
    detector_mask: np.ndarray | None = None,
) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False

    valid_pixels = _unmasked_pixel_selector(image, detector_mask)
    finite_pixels = valid_pixels & np.isfinite(image)
    finite = image[finite_pixels]
    if finite.size == 0:
        return False
    lo, hi = np.nanpercentile(finite, [1.0, 99.5])
    if not np.isfinite(lo) or not np.isfinite(hi) or lo >= hi:
        lo = float(np.nanmin(finite))
        hi = float(np.nanmax(finite))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6.0, 6.8), dpi=120)
    display_image = np.ma.array(image, mask=~finite_pixels)
    im = ax.imshow(display_image, origin="upper", cmap="viridis", vmin=lo, vmax=hi)
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label=INTENSITY_UNIT)
    fig.tight_layout(pad=0.05)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def _qc_stats(
    image: np.ndarray,
    *,
    detector_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    valid_pixels = _unmasked_pixel_selector(image, detector_mask)
    valid_pixel_count = int(np.count_nonzero(valid_pixels))
    finite_mask = valid_pixels & np.isfinite(image)
    finite = image[finite_mask]
    if valid_pixel_count == 0 or finite.size == 0:
        return {
            "finite_fraction": 0.0,
            "negative_fraction": 0.0,
            "min": None,
            "max": None,
            "mean": None,
            "p01": None,
            "p50": None,
            "p995": None,
        }
    return {
        "finite_fraction": float(finite.size / valid_pixel_count),
        "negative_fraction": float(np.sum(finite < 0) / finite.size),
        "min": float(np.nanmin(finite)),
        "max": float(np.nanmax(finite)),
        "mean": float(np.nanmean(finite)),
        "p01": float(np.nanpercentile(finite, 1.0)),
        "p50": float(np.nanpercentile(finite, 50.0)),
        "p995": float(np.nanpercentile(finite, 99.5)),
    }


def _pydidas_index_row(
    *,
    source: Path,
    paths: OutputPaths,
    safe_poni_path: Path,
    mask_info: MaskInfo,
) -> dict[str, Any]:
    return {
        "raw_sample": str(source),
        "edf": str(paths.edf),
        "hdf5": str(paths.h5),
        "poni": str(safe_poni_path),
        "mask": str(mask_info.npy_path),
        "mask_edf": str(mask_info.edf_path),
        "metadata": str(paths.metadata),
        "normalization_factor": 1.0,
        "dark": "",
        "flat": "",
    }


def _validate_resumed_array(
    image: np.ndarray,
    *,
    metadata: dict[str, Any],
    label: str,
) -> None:
    arr = np.asarray(image)
    image_meta = metadata.get("output_image", {})
    expected_shape = tuple(image_meta.get("shape", ()))
    expected_dtype = str(image_meta.get("dtype", ""))
    expected_sha = str(image_meta.get("sha256", ""))
    if not expected_shape or arr.shape != expected_shape:
        raise ValueError(f"existing {label} shape mismatch: {arr.shape} vs {expected_shape}")
    if not expected_dtype or arr.dtype.name != expected_dtype:
        raise ValueError(f"existing {label} dtype mismatch: {arr.dtype.name} vs {expected_dtype}")
    if not expected_sha or _array_sha256(arr) != expected_sha:
        raise ValueError(f"existing {label} detector image checksum mismatch")
    finite = np.isfinite(arr)
    if np.all(finite):
        return
    mask_path = Path(str(metadata.get("mask", {}).get("npy", "")))
    try:
        mask = np.load(mask_path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise ValueError(f"existing {label} contains non-finite values and mask is unreadable") from exc
    if mask.shape != arr.shape or np.any(~finite[mask == 0]):
        raise ValueError(f"existing {label} contains non-finite unmasked detector values")


def _validate_existing_outputs(paths: OutputPaths, metadata: dict[str, Any]) -> None:
    outputs = metadata.get("outputs", {})
    external_k_contract = _k_calibration_contract(
        metadata.get("absolute_calibration", {}),
        require_complete=True,
    )
    for key, expected_path in (
        ("hdf5", paths.h5),
        ("edf", paths.edf),
        ("metadata", paths.metadata),
    ):
        recorded = str(outputs.get(key, ""))
        if not recorded or Path(recorded).resolve() != expected_path.resolve():
            raise ValueError(f"existing output path mismatch for {key}: {recorded!r}")
    for label, path, key in (
        ("HDF5", paths.h5, "hdf5_sha256"),
        ("EDF", paths.edf, "edf_sha256"),
    ):
        expected = str(outputs.get(key, ""))
        if not expected or _file_sha256(path) != expected:
            raise ValueError(f"existing {label} file checksum mismatch or missing")

    try:
        import h5py

        with h5py.File(str(paths.h5), "r") as h5:
            entry = h5["entry"]
            dataset = h5["entry/data/I_abs_2d"]
            if entry.attrs.get("schema") != SCHEMA_VERSION:
                raise ValueError("existing HDF5 internal schema mismatch")
            if entry.attrs.get("formula_version") != FORMULA_VERSION:
                raise ValueError("existing HDF5 formula version mismatch")
            if entry.attrs.get("processing_signature") != metadata.get("processing_signature"):
                raise ValueError("existing HDF5 processing signature mismatch")
            if entry.attrs.get("frame_signature") != metadata.get("frame_signature"):
                raise ValueError("existing HDF5 frame signature mismatch")
            selection = metadata.get('sample_selection') or {}
            derivation = metadata.get('thickness', {}).get('derivation') or {}
            if str(entry.attrs.get('include_manifest_sha256', '')) != str(
                selection.get('sha256', '')
            ):
                raise ValueError('existing HDF5 include manifest checksum mismatch')
            if str(entry.attrs.get('thickness_derivation_sha256', '')) != str(
                derivation.get('sha256', '')
            ):
                raise ValueError('existing HDF5 thickness derivation checksum mismatch')
            if dataset.attrs.get("units") != INTENSITY_UNIT:
                raise ValueError("existing HDF5 intensity unit mismatch")
            embedded_raw = h5["entry/metadata_json"][()]
            if isinstance(embedded_raw, bytes):
                embedded_raw = embedded_raw.decode("utf-8")
            embedded_metadata = json.loads(str(embedded_raw))
            embedded_k_contract = _k_calibration_contract(
                embedded_metadata.get("absolute_calibration", {}),
                require_complete=True,
            )
            if embedded_k_contract != external_k_contract:
                raise ValueError("existing HDF5 K calibration uncertainty mismatch")
            if embedded_metadata.get("uncertainty") != metadata.get("uncertainty"):
                raise ValueError("existing HDF5 uncertainty metadata mismatch")
            attr_k_contract = json.loads(str(entry.attrs.get("k_calibration_json", "")))
            if attr_k_contract != external_k_contract:
                raise ValueError("existing HDF5 K calibration attribute mismatch")
            h5_image = dataset[()]
            uncertainty_group = h5["entry/data/uncertainty"]
            if uncertainty_group.attrs.get("schema") != SCHEMA_VERSION:
                raise ValueError("existing HDF5 uncertainty schema mismatch")
            if uncertainty_group.attrs.get("formula_version") != FORMULA_VERSION:
                raise ValueError("existing HDF5 uncertainty formula version mismatch")
            expected_mask_policy = str(
                metadata.get("uncertainty", {}).get(
                    "mask_policy", UNCERTAINTY_MASK_POLICY
                )
            )
            if uncertainty_group.attrs.get("mask_policy") != expected_mask_policy:
                raise ValueError("existing HDF5 uncertainty mask policy mismatch")
            uncertainty_status = str(metadata.get("uncertainty", {}).get("status", "unknown"))
            if uncertainty_group.attrs.get("status") != uncertainty_status:
                raise ValueError("existing HDF5 uncertainty status mismatch")
            expanded_status = str(
                metadata.get("uncertainty", {}).get(
                    "expanded_status", "unavailable"
                )
            )
            if uncertainty_group.attrs.get("expanded_status") != expanded_status:
                raise ValueError("existing HDF5 expanded uncertainty status mismatch")
            for dataset_name in _UNCERTAINTY_DATASETS:
                uncertainty_ds = uncertainty_group[dataset_name]
                values = uncertainty_ds[()]
                if values.shape != h5_image.shape:
                    raise ValueError(
                        f"existing HDF5 uncertainty shape mismatch for {dataset_name}"
                    )
                if values.dtype.name != "float64":
                    raise ValueError(
                        f"existing HDF5 uncertainty dtype mismatch for {dataset_name}"
                    )
                if uncertainty_ds.attrs.get("units") != INTENSITY_UNIT:
                    raise ValueError(
                        f"existing HDF5 uncertainty unit mismatch for {dataset_name}"
                    )
                if np.any(np.isinf(values)) or np.any(np.isfinite(values) & (values < 0)):
                    raise ValueError(
                        f"existing HDF5 uncertainty values invalid for {dataset_name}"
                    )
                requires_finite = (
                    uncertainty_status == "complete" and dataset_name != "expanded"
                ) or (expanded_status == "available" and dataset_name == "expanded")
                if requires_finite and not np.all(np.isfinite(values)):
                    raise ValueError(
                        f"existing complete HDF5 uncertainty contains unknown {dataset_name}"
                    )
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing HDF5 output is unreadable or incomplete: {paths.h5}") from exc
    _validate_resumed_array(h5_image, metadata=metadata, label="HDF5")

    try:
        import fabio

        edf = fabio.open(str(paths.edf))
        try:
            header = edf.header
            if header.get("SAXSAbsSchema") != SCHEMA_VERSION:
                raise ValueError("existing EDF internal schema mismatch")
            if header.get("FormulaVersion") != FORMULA_VERSION:
                raise ValueError("existing EDF formula version mismatch")
            if header.get("ProcessingSignature") != metadata.get("processing_signature"):
                raise ValueError("existing EDF processing signature mismatch")
            if header.get("FrameSignature") != metadata.get("frame_signature"):
                raise ValueError("existing EDF frame signature mismatch")
            selection = metadata.get('sample_selection') or {}
            derivation = metadata.get('thickness', {}).get('derivation') or {}
            if header.get('IncludeManifestSHA256', '') != str(selection.get('sha256', '')):
                raise ValueError('existing EDF include manifest checksum mismatch')
            if header.get('ThicknessDerivationSHA256', '') != str(
                derivation.get('sha256', '')
            ):
                raise ValueError('existing EDF thickness derivation checksum mismatch')
            if header.get("IntensityUnit") != INTENSITY_UNIT:
                raise ValueError("existing EDF intensity unit mismatch")
            expected_k_headers = {
                "KFactor": _edf_optional_float(external_k_contract["k_factor"]),
                "KStd": _edf_optional_float(external_k_contract["k_std"]),
                "KStdMeaning": str(external_k_contract["k_std_semantics"]).replace(";", ""),
                "KStatStdU": _edf_optional_float(
                    external_k_contract["k_statistical_standard_uncertainty"]
                ),
                "KStandardU": _edf_optional_float(
                    external_k_contract["k_standard_uncertainty"]
                ),
                "KExpandedU": _edf_optional_float(
                    external_k_contract["k_expanded_uncertainty"]
                ),
                "KCoverage": _edf_optional_float(external_k_contract["coverage_factor"]),
            }
            for key, expected in expected_k_headers.items():
                if header.get(key) != expected:
                    raise ValueError(f"existing EDF K calibration uncertainty mismatch for {key}")
            expected_uncertainty_status = str(
                metadata.get("uncertainty", {}).get("status", "unknown")
            )
            if header.get("UncertaintyStatus") != expected_uncertainty_status:
                raise ValueError("existing EDF uncertainty status mismatch")
            expected_expanded_status = str(
                metadata.get("uncertainty", {}).get("expanded_status", "unavailable")
            )
            if header.get("ExpandedUStatus") != expected_expanded_status:
                raise ValueError("existing EDF expanded uncertainty status mismatch")
            if Path(str(header.get("UncertaintyHDF5", ""))).resolve() != paths.h5.resolve():
                raise ValueError("existing EDF uncertainty HDF5 pointer mismatch")
            edf_image = np.asarray(edf.data)
        finally:
            edf.close()
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError(f"existing EDF output is unreadable or incomplete: {paths.edf}") from exc
    _validate_resumed_array(edf_image, metadata=metadata, label="EDF")


def _validate_metadata_processing_signature(metadata: dict[str, Any]) -> None:
    payload = metadata.get('processing_signature_payload')
    if not isinstance(payload, dict):
        raise ValueError('existing processing_signature_payload is missing or invalid')
    recorded_signature = metadata.get('processing_signature')
    if recorded_signature != _processing_signature_digest(payload):
        raise ValueError('existing processing signature payload digest mismatch')
    run_controls = payload.get('run_control_inputs')
    if not isinstance(run_controls, dict):
        raise ValueError('existing processing signature lacks run_control_inputs')

    selection = metadata.get('sample_selection')
    signed_selection = run_controls.get('include_manifest')
    if signed_selection is None:
        if selection is not None:
            raise ValueError('existing include manifest metadata/signature mismatch')
    elif not isinstance(signed_selection, dict) or not isinstance(selection, dict):
        raise ValueError('existing include manifest metadata/signature mismatch')
    else:
        for field_name in ('sha256', 'row_count'):
            if selection.get(field_name) != signed_selection.get(field_name):
                raise ValueError(
                    f'existing include manifest {field_name} metadata/signature mismatch'
                )

    derivation = metadata.get('thickness', {}).get('derivation')
    signed_derivation = run_controls.get('thickness_derivation')
    if signed_derivation is None:
        if derivation is not None:
            raise ValueError('existing thickness derivation metadata/signature mismatch')
    elif not isinstance(signed_derivation, dict) or not isinstance(derivation, dict):
        raise ValueError('existing thickness derivation metadata/signature mismatch')
    else:
        for field_name in ('sha256', 'fixed_thickness_cm', 'payload'):
            if derivation.get(field_name) != signed_derivation.get(field_name):
                raise ValueError(
                    f'existing thickness derivation {field_name} metadata/signature mismatch'
                )


def _frame_qc_row_from_metadata(
    *,
    source: Path,
    rel: Path,
    paths: OutputPaths,
    expected_signature: str | None = None,
) -> dict[str, Any]:
    try:
        metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"existing BL19B2 output metadata is unreadable for {rel}: {paths.metadata}"
        ) from exc
    if metadata.get("schema") != SCHEMA_VERSION:
        raise ValueError(
            "existing BL19B2 output metadata schema mismatch for "
            f"{rel}: expected {SCHEMA_VERSION}, got {metadata.get('schema')!r}"
        )
    _validate_metadata_processing_signature(metadata)
    if expected_signature is not None and metadata.get("processing_signature") != expected_signature:
        raise ValueError(
            "existing BL19B2 output processing_signature mismatch for "
            f"{rel}: expected {expected_signature}, got {metadata.get('processing_signature')!r}"
        )
    uncertainty = metadata.get("uncertainty")
    if not isinstance(uncertainty, dict):
        raise ValueError(
            f"existing BL19B2 output uncertainty metadata is missing or invalid for {rel}"
        )
    if metadata.get("formula_version") != FORMULA_VERSION:
        raise ValueError(
            "existing BL19B2 output formula version mismatch for "
            f"{rel}: expected {FORMULA_VERSION}, got {metadata.get('formula_version')!r}"
        )
    current_source_identity = _source_identity(source)
    if metadata.get("source_identity") != current_source_identity:
        raise ValueError(f"existing BL19B2 output source identity mismatch for {rel}")
    expected_frame_signature = _frame_signature(
        str(metadata.get("processing_signature", "")),
        current_source_identity,
    )
    if metadata.get("frame_signature") != expected_frame_signature:
        raise ValueError(f"existing BL19B2 output frame signature mismatch for {rel}")
    _validate_existing_outputs(paths, metadata)
    outputs = metadata.get("outputs", {})
    qc = metadata.get("qc", {})
    normalization = metadata.get("normalization", {})
    thickness = metadata.get("thickness", {})
    calibration = metadata.get("absolute_calibration", {})
    mask = metadata.get("mask", {})
    warnings = metadata.get("warnings", [])
    warning_text = " | ".join(str(item) for item in warnings) if isinstance(warnings, list) else str(warnings)
    preview = str(outputs.get("preview") or paths.preview)
    if not Path(preview).exists():
        preview = ""
    return {
        "relative_path": str(rel),
        "status": "success_existing",
        "hdf5": str(outputs.get("hdf5") or paths.h5),
        "edf": str(outputs.get("edf") or paths.edf),
        "metadata": str(outputs.get("metadata") or paths.metadata),
        "preview": preview,
        "processing_signature": metadata.get("processing_signature", ""),
        "mask": str(mask.get("npy", "")),
        "k_factor": calibration.get("k_factor", ""),
        "k_std": calibration.get("k_std", ""),
        "k_statistical_standard_uncertainty": calibration.get(
            "k_statistical_standard_uncertainty", ""
        ),
        "k_standard_uncertainty": calibration.get("k_standard_uncertainty", ""),
        "k_expanded_uncertainty": calibration.get("k_expanded_uncertainty", ""),
        "coverage_factor": calibration.get("coverage_factor", ""),
        "thickness_cm": thickness.get("thickness_cm", ""),
        "norm_sample": normalization.get("norm_sample", ""),
        "transmission_abs": normalization.get("transmission_abs", ""),
        "uncertainty_status": uncertainty.get("status", ""),
        **qc,
        "warnings": warning_text,
    }


def _frame_metadata(
    *,
    source: Path,
    header: BL19B2Header,
    source_identity: dict[str, Any],
    norm_s: float,
    thickness_cm: float,
    calibration: StandardCalibration,
    paths: OutputPaths,
    qc: dict[str, Any],
    safe_poni_path: Path,
    reference_paths: ReferencePaths,
    config: BL19B2Abs2DConfig,
    dark_header: BL19B2Header,
    mask_info: MaskInfo,
    processing_signature: str,
    signature_payload: dict[str, Any],
    provenance_paths: ProvenancePaths,
    software_versions: dict[str, Any],
    code_state: dict[str, Any],
    warnings: list[str],
    image: np.ndarray,
    uncertainty_budget: AbsoluteUncertaintyBudget,
    control_inputs: RunControlInputs | None = None,
) -> dict[str, Any]:
    if control_inputs is None:
        control_inputs = _load_run_control_inputs(config)
    control_provenance = _control_inputs_provenance_payload(control_inputs)
    metadata = {
        'sample_selection': control_provenance['include_manifest'],
        "schema": SCHEMA_VERSION,
        "formula_version": FORMULA_VERSION,
        "processing_signature": processing_signature,
        "processing_signature_payload": signature_payload,
        "source_identity": source_identity,
        "frame_signature": _frame_signature(processing_signature, source_identity),
        "raw_sample": str(source),
        "outputs": {
            "hdf5": str(paths.h5),
            "edf": str(paths.edf),
            "metadata": str(paths.metadata),
            "preview": str(paths.preview),
        },
        "intensity_unit": INTENSITY_UNIT,
        "output_image": {
            "shape": list(image.shape),
            "dtype": image.dtype.name,
            "sha256": _array_sha256(image),
        },
        "normalization": {
            "monitor_mode": config.monitor_mode,
            "formula": (
                "exposure_s * MON * ABS" if config.monitor_mode == "rate" else "MON * ABS"
            ),
            "exposure_s": header.exposure_s,
            "monitor": header.monitor,
            "transmission_abs": header.transmission,
            "norm_sample": norm_s,
        },
        "dark": {
            "file": str(reference_paths.dark),
            "exposure_s": dark_header.exposure_s,
            "scaling": "exposure_matched",
            "formula": "dark_scaled = dark * exposure_s / dark_exposure_s",
        },
        "thickness": {
            "method": (
                "fixed configured thickness"
                if config.sample_thickness_cm is not None
                else "Beer-Lambert from ABS and mu"
            ),
            "mu_cm_inv": config.mu_cm_inv,
            "thickness_cm": thickness_cm,
        },
        "absolute_calibration": {
            "standard_file": str(reference_paths.standard),
            "standard_key": config.standard_key,
            **_k_calibration_contract(calibration, require_complete=True),
            "q_min_overlap": calibration.q_min_overlap,
            "q_max_overlap": calibration.q_max_overlap,
            "points_used": calibration.points_used,
            "points_total": calibration.points_total,
            "standard_thickness_cm": calibration.standard_thickness_cm,
            "standard_thickness_source": calibration.standard_thickness_source,
        },
        "uncertainty": _frame_uncertainty_metadata(
            config,
            calibration,
            uncertainty_budget,
            detector_mask=mask_info.mask,
        ),
        "background": {
            "background_file": str(reference_paths.background),
            "alpha": config.alpha,
            "norm_background": calibration.norm_background,
            "transmission_used": calibration.bg_transmission_used,
            "transmission_policy": "QC only; normalized with T_bg=1 under NIST convention",
        },
        "mask": {
            "npy": str(mask_info.npy_path),
            "edf": str(mask_info.edf_path),
            "checksum_sha256": mask_info.checksum_sha256,
            "convention": "pyFAI: 0=valid, 1=masked",
            "sources": {
                "user_mask": str(mask_info.user_mask_path or ""),
                "pyfai_detector_mask": True,
                "dark_hot_pixel_threshold": mask_info.dark_hot_pixel_threshold,
            },
            "counts": {
                "user_mask_pixels": mask_info.user_mask_pixels,
                "detector_mask_pixels": mask_info.detector_mask_pixels,
                "dark_hot_pixels": mask_info.dark_hot_pixels,
                "combined_mask_pixels": mask_info.combined_mask_pixels,
            },
        },
        "geometry": {
            "poni": str(safe_poni_path),
            "source_poni_path": _optional_path_text(config.poni_path),
            "pydidas_cali_yaml": _optional_path_text(config.pydidas_cali_yaml),
            "energy_kev": header.energy_kev,
            "distance_mm_header": header.distance_mm,
            "beam_x_px_header": header.beam_x_px,
            "beam_y_px_header": header.beam_y_px,
            "pixel_size_m_header": header.pixel_size_m,
        },
        "direct_beam": {
            "file": str(reference_paths.direct or ""),
            "role": "provenance_only",
            "transmission_qc_applied": False,
        },
        "corrections_applied_in_image": {
            "dark": True,
            "dark_scaling": "exposure_matched",
            "background": True,
            "monitor": True,
            "transmission": True,
            "absolute_k": True,
            "thickness": True,
            "flat": False,
            "mask": False,
            "solid_angle": False,
            "polarization": False,
        },
        "corrections_deferred_to_integration": {
            "mask": str(mask_info.npy_path),
            "solid_angle": bool(config.correct_solid_angle_for_k),
            "polarization_factor": config.polarization_factor,
        },
        "recommended_reintegration": {
            "dark": None,
            "flat": None,
            "mask": str(mask_info.npy_path),
            "normalization_factor": 1.0,
            "do_not_repeat": ["dark", "background", "transmission", "monitor", "thickness", "K"],
            "correctSolidAngle": bool(config.correct_solid_angle_for_k),
            "polarization_factor": config.polarization_factor,
            "solid_angle_and_polarization": "apply once during integration, not in the 2D image",
        },
        "qc": qc,
        "warnings": warnings,
    }
    metadata['thickness']['derivation'] = control_provenance['thickness_derivation']
    metadata.update(
        build_provenance_metadata(
            provenance_paths=provenance_paths,
            software_versions=software_versions,
            code_state=code_state,
        )
    )
    return metadata


def _ensure_output_dirs(out_root: Path) -> None:
    for rel in [
        "config",
        "config/geometry",
        "images_h5",
        "images_edf",
        "metadata",
        "previews",
        "qc",
        "logs",
        "manifests",
        "masks",
    ]:
        (out_root / rel).mkdir(parents=True, exist_ok=True)


def _write_readme(out_root: Path, config: BL19B2Abs2DConfig) -> None:
    normalization = (
        "exposure/MON/transmission normalization"
        if config.monitor_mode == "rate"
        else "integrated-MON/transmission normalization"
    )
    thickness = (
        "configured fixed-thickness scaling"
        if config.sample_thickness_cm is not None
        else "Beer-Lambert thickness scaling"
    )
    text = f"""# BL19B2 dat001 absolute corrected 2D outputs

These detector-space images have already had exposure-matched dark subtraction,
NIST-convention background subtraction, {normalization}, {thickness}, and
GC-derived K-factor scaling applied.

The 2D matrix does not have mask, solid-angle, or polarization corrections
burned into pixel values.

For pyFAI/pydidas reintegration use the copied PONI file and set:

- dark = None
- flat = None
- mask = masks/bl19b2_mask.npy
- normalization_factor = 1.0
- correctSolidAngle = {bool(config.correct_solid_angle_for_k)}
- do not reapply transmission, monitor, thickness, or K scaling

PNG previews are for inspection only and are not scientific data.
"""
    (out_root / "README.md").write_text(text, encoding="utf-8")


def run_bl19b2_abs2d(config: BL19B2Abs2DConfig) -> dict[str, Any]:
    """Run BL19B2 scan and optional absolute corrected 2D export."""
    validate_config(config)
    normalized_monitor_mode = str(config.monitor_mode).strip().lower()
    if config.monitor_mode != normalized_monitor_mode:
        config = replace(config, monitor_mode=normalized_monitor_mode)
    input_root = Path(config.input_root)
    out_root = config.resolved_output_root()
    control_inputs = _load_run_control_inputs(config)
    reference_paths = find_reference_paths(
        input_root,
        mask_path=config.mask_path,
        pydidas_cali_yaml=config.pydidas_cali_yaml,
        dark_path=config.dark_path,
        background_path=config.background_path,
        standard_path=config.standard_path,
        direct_path=config.direct_path,
    )
    inventory_rows, sample_paths = scan_inputs(
        config, include_manifest=control_inputs.include_manifest
    )

    reference_sources: dict[str, DetectorSourceSnapshot] | None = None
    if not config.dry_run:
        # Capture every computational reference before creating run outputs.  Later stages
        # consume only these arrays, headers, and identities, so provenance cannot drift.
        reference_sources = {
            "dark": capture_detector_source(reference_paths.dark),
            "background": capture_detector_source(reference_paths.background),
            "standard": capture_detector_source(reference_paths.standard),
        }

    _ensure_output_dirs(out_root)
    config, control_inputs = _copy_run_control_inputs(config, control_inputs)
    safe_poni = _copy_poni_to_safe_path(config)
    _write_readme(out_root, config)
    software_versions = collect_software_versions()
    code_state = collect_code_state()
    provenance_paths = _provenance_paths(out_root)
    _write_csv(out_root / "manifests" / "input_inventory.csv", inventory_rows)
    _write_csv(
        out_root / "config" / "reference_selection.csv",
        [
            {"kind": "dark", "path": str(reference_paths.dark)},
            {"kind": "background", "path": str(reference_paths.background)},
            {"kind": "standard", "path": str(reference_paths.standard)},
            {"kind": "direct", "path": str(reference_paths.direct or "")},
            {"kind": "mask", "path": str(reference_paths.mask or "")},
            {"kind": "poni", "path": str(safe_poni)},
        ],
    )

    sample_total = len(sample_paths)
    rejected_scan = [row for row in inventory_rows if row.get("kind") == "sample" and row["status"] != "ok"]
    if config.dry_run:
        _write_processing_config(
            config, safe_poni, control_inputs=control_inputs
        )
        provenance_paths.run_command.parent.mkdir(parents=True, exist_ok=True)
        provenance_paths.run_command.write_text(
            build_rerun_command(
                config,
                poni_path=safe_poni,
                control_inputs=control_inputs,
            ),
            encoding="utf-8",
        )
        _write_json(provenance_paths.processing_environment, software_versions)
        provenance_paths.code_state.write_text(format_code_state_text(code_state), encoding="utf-8")
        _write_csv(out_root / "qc" / "rejected_frames.csv", rejected_scan)
        return {
            "status": "dry-run",
            "output_root": str(out_root),
            "sample_total": sample_total,
            "rejected": len(rejected_scan),
            "inventory_csv": str(out_root / "manifests" / "input_inventory.csv"),
            "run_command": str(provenance_paths.run_command),
        }

    assert reference_sources is not None
    dark_source = reference_sources["dark"]
    background_source = reference_sources["background"]
    standard_source = reference_sources["standard"]
    dark = dark_source.image
    dark_header = dark_source.header
    background = background_source.image
    mask_info = load_and_write_mask(
        safe_poni_path=safe_poni,
        dark=dark,
        reference_paths=reference_paths,
        config=config,
    )
    calibration, bg_net = calibrate_standard(
        config,
        reference_paths=reference_paths,
        safe_poni_path=safe_poni,
        dark=dark,
        background=background,
        dark_header=dark_header,
        mask=mask_info.mask,
        background_header=background_source.header,
        standard_image=standard_source.image,
        standard_header=standard_source.header,
    )
    processing_signature, signature_payload = build_processing_signature(
        config,
        mask_info=mask_info,
        calibration=calibration,
        safe_poni_path=safe_poni,
        reference_paths=reference_paths,
        reference_identities={
            name: snapshot.identity for name, snapshot in reference_sources.items()
        },
        control_inputs=control_inputs,
    )
    _write_processing_config(
        config,
        safe_poni,
        mask_info=mask_info,
        processing_signature=processing_signature,
        signature_payload=signature_payload,
        control_inputs=control_inputs,
    )
    standard_rows = [
        {
            "schema": SCHEMA_VERSION,
            "processing_signature": processing_signature,
            "k_factor": calibration.k_factor,
            "k_std": calibration.k_std,
            "k_std_semantics": K_STD_SEMANTICS,
            "k_statistical_standard_uncertainty": (
                calibration.k_statistical_standard_uncertainty
            ),
            "k_standard_uncertainty": calibration.k_standard_uncertainty,
            "k_expanded_uncertainty": calibration.k_expanded_uncertainty,
            "coverage_factor": calibration.coverage_factor,
            "reference_coverage_factor": calibration.reference_coverage_factor,
            "uncertainty_status": calibration.uncertainty_status,
            "expanded_uncertainty_status": calibration.expanded_uncertainty_status,
            "parallelism_max_relative_deviation": (
                calibration.parallelism_max_relative_deviation
            ),
            "parallelism_relative_tolerance": calibration.parallelism_relative_tolerance,
            "parallelism_check_passed": calibration.parallelism_check_passed,
            "q_min_overlap": calibration.q_min_overlap,
            "q_max_overlap": calibration.q_max_overlap,
            "points_used": calibration.points_used,
            "points_total": calibration.points_total,
            "standard_thickness_cm": calibration.standard_thickness_cm,
            "standard_thickness_source": calibration.standard_thickness_source,
            "norm_standard": calibration.norm_standard,
            "norm_background": calibration.norm_background,
            "bg_transmission_used": calibration.bg_transmission_used,
            "dark_exposure_s": dark_header.exposure_s,
            "mask_checksum_sha256": mask_info.checksum_sha256,
            "warnings": " | ".join(calibration.warnings),
        }
    ]
    _write_csv(out_root / "qc" / "standard_k_report.csv", standard_rows)

    valid_samples = [
        p
        for p in sample_paths
        if classify_sample_frame(
            read_tiff_header(p),
            beer_lambert_thickness=config.sample_thickness_cm is None,
            transmission_abs_uncertainty=config.transmission_abs_uncertainty,
        ).status
        == "ok"
    ]
    if config.max_frames is not None:
        valid_samples = valid_samples[: max(0, int(config.max_frames))]

    frame_qc_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    pydidas_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = list(rejected_scan)
    warning_rows: list[dict[str, Any]] = []
    processed = 0
    skipped = 0
    failed = 0
    instrument_ai: Any | None = None
    standard_instrument_header = standard_source.header
    background_uncertainty_header = background_source.header
    if not _is_finite_positive(background_uncertainty_header.exposure_s):
        raise ValueError("background frame requires Exposure_time for uncertainty propagation")

    for source in valid_samples:
        rel = source.relative_to(input_root)
        paths = build_output_paths(source, input_root=input_root, output_root=out_root)
        if (
            paths.h5.exists()
            and paths.edf.exists()
            and paths.metadata.exists()
            and not config.overwrite
        ):
            row = _frame_qc_row_from_metadata(
                source=source,
                rel=rel,
                paths=paths,
                expected_signature=processing_signature,
            )
            update_metadata_provenance(
                paths.metadata,
                provenance_paths=provenance_paths,
                software_versions=software_versions,
                code_state=code_state,
            )
            skipped += 1
            frame_qc_rows.append(row)
            manifest_row = {"raw_sample": str(source), **row}
            manifest_row["status"] = "skipped_existing"
            manifest_rows.append(manifest_row)
            pydidas_rows.append(
                _pydidas_index_row(
                    source=source,
                    paths=paths,
                    safe_poni_path=safe_poni,
                    mask_info=mask_info,
                )
            )
            if row.get("warnings"):
                warning_rows.append(row)
            continue
        if not config.overwrite:
            existing_targets = [path for path in (paths.h5, paths.edf, paths.metadata) if path.exists()]
            if existing_targets:
                existing_text = "; ".join(str(path) for path in existing_targets)
                raise ValueError(
                    "incomplete existing BL19B2 output set with overwrite=False for "
                    f"{rel}: {existing_text}"
                )

        try:
            source_snapshot = capture_detector_source(source)
            header = source_snapshot.header
            sample = source_snapshot.image
            frame_class = classify_sample_frame(
                header,
                beer_lambert_thickness=config.sample_thickness_cm is None,
                transmission_abs_uncertainty=config.transmission_abs_uncertainty,
            )
            if frame_class.status != "ok":
                rejected_rows.append(
                    {
                        "relative_path": str(rel),
                        "kind": "sample",
                        "status": frame_class.status,
                        "reason": frame_class.reason,
                    }
                )
                continue
            assert header.exposure_s is not None
            assert header.monitor is not None
            assert header.transmission is not None
            if config.sample_thickness_cm is not None:
                thickness = float(config.sample_thickness_cm)
            else:
                assert config.mu_cm_inv is not None
                thickness = float(
                    estimate_thickness_cm(
                        header.transmission,
                        config.mu_cm_inv,
                        transmission_abs_uncertainty=config.transmission_abs_uncertainty,
                    )
                )
            if sample.shape != dark.shape:
                raise ValueError(f"sample shape mismatch: {sample.shape} vs dark{dark.shape}")
            if instrument_ai is None:
                import pyFAI

                instrument_ai = pyFAI.load(str(safe_poni))
            instrument_warnings = validate_instrument_consistency(
                header,
                image_shape=sample.shape,
                integrator=instrument_ai,
                label=str(rel),
                reference_header=standard_instrument_header,
            )

            sample_normed, norm_s = normalize_dark_corrected_image(
                sample,
                dark,
                image_exposure_s=header.exposure_s,
                dark_exposure_s=dark_header.exposure_s,
                monitor=header.monitor,
                transmission=header.transmission,
                monitor_mode=config.monitor_mode,
            )
            image_abs = (sample_normed - config.alpha * bg_net) * (calibration.k_factor / thickness)
            assert dark_header.exposure_s is not None
            assert background_uncertainty_header.exposure_s is not None
            uncertainty_budget = compute_bl19b2_uncertainty_budget(
                image_abs,
                sample_raw=sample,
                background_raw=background,
                dark_raw=dark,
                sample_exposure_s=header.exposure_s,
                background_exposure_s=background_uncertainty_header.exposure_s,
                dark_exposure_s=dark_header.exposure_s,
                norm_sample=norm_s,
                norm_background=calibration.norm_background,
                alpha=config.alpha,
                k_factor=calibration.k_factor,
                thickness_cm=thickness,
                transmission=header.transmission,
                mu_cm_inv=config.mu_cm_inv,
                k_statistical_standard_uncertainty=(
                    calibration.k_statistical_standard_uncertainty
                ),
                k_standard_uncertainty=calibration.k_standard_uncertainty,
                standard_thickness_relative_standard_uncertainty=(
                    config.standard_thickness_relative_standard_uncertainty
                ),
                transmission_abs_uncertainty=config.transmission_abs_uncertainty,
                monitor_relative_standard_uncertainty=(
                    config.monitor_relative_standard_uncertainty
                ),
                thickness_relative_standard_uncertainty=(
                    config.sample_thickness_relative_standard_uncertainty
                ),
                mu_relative_standard_uncertainty=config.mu_relative_standard_uncertainty,
                alpha_standard_uncertainty=config.alpha_standard_uncertainty,
                coverage_factor=calibration.coverage_factor,
                k_independent_standard_uncertainty=(
                    calibration.k_independent_standard_uncertainty
                ),
                k_alpha_relative_sensitivity=(
                    calibration.k_alpha_relative_sensitivity
                ),
                k_calibration_background_monitor_relative_sensitivity=(
                    calibration.k_calibration_background_monitor_relative_sensitivity
                ),
                calibration_background_monitor_relative_standard_uncertainty=(
                    config.calibration_background_monitor_relative_standard_uncertainty
                ),
                detector_mask=mask_info.mask,
            )
            image_out = _coerce_output_dtype(image_abs, config.dtype, mask=mask_info.mask)
            qc = _qc_stats(image_out, detector_mask=mask_info.mask)
            warnings = [*calibration.warnings, *instrument_warnings]
            if qc["finite_fraction"] < 0.99:
                warnings.append(f"finite_fraction below 0.99: {qc['finite_fraction']:.6g}")
            if qc["negative_fraction"] > 0.2:
                warnings.append(f"negative_fraction above 0.2: {qc['negative_fraction']:.6g}")

            metadata = _frame_metadata(
                source=source,
                header=header,
                source_identity=source_snapshot.identity,
                norm_s=norm_s,
                thickness_cm=thickness,
                calibration=calibration,
                paths=paths,
                qc=qc,
                safe_poni_path=safe_poni,
                reference_paths=reference_paths,
                config=config,
                dark_header=dark_header,
                mask_info=mask_info,
                processing_signature=processing_signature,
                signature_payload=signature_payload,
                provenance_paths=provenance_paths,
                software_versions=software_versions,
                code_state=code_state,
                warnings=warnings,
                image=image_out,
                uncertainty_budget=uncertainty_budget,
                control_inputs=control_inputs,
            )
            write_hdf5_image(paths.h5, image_out, metadata, uncertainty_budget)
            write_edf_image(paths.edf, image_out, metadata)
            metadata["outputs"]["hdf5_sha256"] = _file_sha256(paths.h5)
            metadata["outputs"]["edf_sha256"] = _file_sha256(paths.edf)
            _write_json(paths.metadata, metadata)
            preview_written = False
            if config.write_preview:
                preview_written = write_preview_png(
                    paths.preview,
                    image_out,
                    detector_mask=mask_info.mask,
                )

            row = {
                "relative_path": str(rel),
                "status": "success",
                "hdf5": str(paths.h5),
                "edf": str(paths.edf),
                "metadata": str(paths.metadata),
                "preview": str(paths.preview) if preview_written else "",
                "processing_signature": processing_signature,
                "mask": str(mask_info.npy_path),
                "k_factor": calibration.k_factor,
                "thickness_cm": thickness,
                "norm_sample": norm_s,
                "transmission_abs": header.transmission,
                "uncertainty_status": metadata["uncertainty"]["status"],
                **qc,
                "warnings": " | ".join(warnings),
            }
            frame_qc_rows.append(row)
            manifest_rows.append({"raw_sample": str(source), **row})
            pydidas_rows.append(
                _pydidas_index_row(
                    source=source,
                    paths=paths,
                    safe_poni_path=safe_poni,
                    mask_info=mask_info,
                )
            )
            if warnings:
                warning_rows.append(row)
            processed += 1
        except Exception as exc:
            failed += 1
            row = {
                "relative_path": str(rel),
                "kind": "sample",
                "status": "failed",
                "reason": str(exc),
            }
            rejected_rows.append(row)
            manifest_rows.append({"raw_sample": str(source), **row})

    _write_csv(out_root / "qc" / "frame_qc.csv", frame_qc_rows)
    _write_csv(out_root / "qc" / "warning_frames.csv", warning_rows)
    _write_csv(out_root / "qc" / "rejected_frames.csv", rejected_rows)
    _write_csv(out_root / "manifests" / "processing_manifest.csv", manifest_rows)
    _write_csv(out_root / "manifests" / "pydidas_pyfai_index.csv", pydidas_rows)
    log_path = out_root / "logs" / "processing.log"
    log_path.write_text(
        "\n".join(
            [
                f"timestamp={_dt.datetime.now().isoformat(timespec='seconds')}",
                f"input_root={input_root}",
                f"output_root={out_root}",
                f"processed={processed}",
                f"skipped={skipped}",
                f"failed={failed}",
                f"rejected={len(rejected_rows)}",
                f"k_factor={calibration.k_factor:.10g}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    counts = {
        "sample_total": sample_total,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "rejected": len(rejected_rows),
        "successful_outputs": len(frame_qc_rows),
    }
    if len(frame_qc_rows) == 0:
        run_status = "failed"
    elif failed or rejected_rows:
        run_status = "partial"
    else:
        run_status = "complete"
    write_provenance_package(
        config=config,
        safe_poni_path=safe_poni,
        reference_paths=reference_paths,
        mask_info=mask_info,
        calibration=calibration,
        processing_signature=processing_signature,
        signature_payload=signature_payload,
        counts=counts,
        software_versions=software_versions,
        code_state=code_state,
        run_status=run_status,
        control_inputs=control_inputs,
    )
    return {
        "status": run_status,
        "output_root": str(out_root),
        "sample_total": sample_total,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "rejected": len(rejected_rows),
        "k_factor": calibration.k_factor,
        "k_std": calibration.k_std,
        "k_statistical_standard_uncertainty": (
            calibration.k_statistical_standard_uncertainty
        ),
        "k_standard_uncertainty": calibration.k_standard_uncertainty,
        "k_expanded_uncertainty": calibration.k_expanded_uncertainty,
        "coverage_factor": calibration.coverage_factor,
        "reference_coverage_factor": calibration.reference_coverage_factor,
        "uncertainty_status": calibration.uncertainty_status,
        "expanded_uncertainty_status": calibration.expanded_uncertainty_status,
        "parallelism_max_relative_deviation": calibration.parallelism_max_relative_deviation,
        "parallelism_relative_tolerance": calibration.parallelism_relative_tolerance,
        "parallelism_check_passed": calibration.parallelism_check_passed,
        "standard_k_report": str(out_root / "qc" / "standard_k_report.csv"),
        "processing_manifest": str(out_root / "manifests" / "processing_manifest.csv"),
        "provenance_summary": str(provenance_paths.provenance_summary),
    }
