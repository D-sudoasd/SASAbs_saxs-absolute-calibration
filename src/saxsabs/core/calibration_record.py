"""Typed persistence helpers for workbench absolute-calibration records."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import TypedDict

from .calibration_context import CalibrationContext, sha256_file


CALIBRATION_RECORD_SCHEMA = "saxsabs.workbench_calibration_record.v1"


class CalibrationUncertaintyPayload(TypedDict):
    """Known K-factor uncertainty terms plus explicitly unquantified components."""

    status: str
    standard_uncertainty_status: str
    k_statistical_standard_uncertainty: float | None
    k_standard_uncertainty: float | None
    k_expanded_uncertainty: float | None
    coverage_factor: float | None
    unknown_components: list[str]


@dataclass(frozen=True)
class SampleThicknessConfig:
    """One explicit and mutually exclusive sample-thickness policy."""

    mode: str
    mu_cm_inv: float | None
    fixed_thickness_cm: float | None

    def to_dict(self) -> dict[str, float | str | None]:
        return {
            "mode": self.mode,
            "mu_cm_inv": self.mu_cm_inv,
            "fixed_thickness_cm": self.fixed_thickness_cm,
        }


@dataclass(frozen=True)
class CalibrationRecordLoadResult:
    """A fully validated calibration record, safe for a caller to apply to UI state."""

    record_path: Path
    k_factor: float
    calibration_context: CalibrationContext
    calibration_uncertainty: CalibrationUncertaintyPayload | None
    poni_path: Path
    mask_path: Path | None
    flat_path: Path | None


def _optional_uncertainty(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field_name} must be finite and >= 0, or null when unknown")
    return number


def _optional_coverage_factor(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("coverage_factor must be finite and > 0, or null when unknown")
    return number


def build_calibration_uncertainty_payload(
    k_statistical_standard_uncertainty: object,
    k_standard_uncertainty: object,
    k_expanded_uncertainty: object,
    coverage_factor: object,
) -> CalibrationUncertaintyPayload:
    """Normalize optional K uncertainties without serializing ``None`` as text."""

    statistical = _optional_uncertainty(
        k_statistical_standard_uncertainty,
        field_name="k_statistical_standard_uncertainty",
    )
    standard = _optional_uncertainty(
        k_standard_uncertainty,
        field_name="k_standard_uncertainty",
    )
    expanded = _optional_uncertainty(
        k_expanded_uncertainty,
        field_name="k_expanded_uncertainty",
    )
    coverage = _optional_coverage_factor(coverage_factor)
    standard_status = "available" if standard is not None else "unknown"
    unknown_components = [
        "transmission",
        "monitor",
        "standard_thickness",
        "background_alpha",
    ]
    if standard is None:
        unknown_components.append("reference_standard")
    return {
        "status": "partial",
        "standard_uncertainty_status": standard_status,
        "k_statistical_standard_uncertainty": statistical,
        "k_standard_uncertainty": standard,
        "k_expanded_uncertainty": expanded,
        "coverage_factor": coverage,
        "unknown_components": unknown_components,
    }


def resolve_sample_thickness_config(
    *,
    mode: object,
    mu_value: object,
    fixed_thickness_mm: object,
) -> SampleThicknessConfig:
    """Resolve fixed or Beer-Lambert thickness without a hidden attenuation default."""

    mode_name = str(mode or "").strip().lower()
    if mode_name == "fixed":
        thickness_mm = float(fixed_thickness_mm)
        if not math.isfinite(thickness_mm) or thickness_mm <= 0:
            raise ValueError("固定样品厚度必须为有限正数")
        return SampleThicknessConfig(
            mode="fixed",
            mu_cm_inv=None,
            fixed_thickness_cm=thickness_mm / 10.0,
        )
    if mode_name == "auto":
        text = str(mu_value if mu_value is not None else "").strip()
        if not text:
            raise ValueError("Beer-Lambert 模式要求显式输入 mu 衰减系数")
        mu = float(text)
        if not math.isfinite(mu) or mu <= 0:
            raise ValueError("Beer-Lambert mu 衰减系数必须为有限正数")
        return SampleThicknessConfig(
            mode="auto",
            mu_cm_inv=mu,
            fixed_thickness_cm=None,
        )
    raise ValueError("样品厚度模式仅支持 fixed 或 auto")


def _calibration_record_fingerprint(payload: dict[str, object]) -> str:
    canonical = dict(payload)
    canonical.pop("record_fingerprint", None)
    text = json.dumps(
        canonical,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_operator_file(path: object, *, required: bool) -> Path | None:
    text = str(path or "").strip()
    if not text:
        if required:
            raise ValueError("calibration record operator files are incomplete")
        return None
    resolved = Path(text).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"calibration context file not found: {resolved}")
    return resolved


def _validate_context_file_hashes(
    calibration_context: CalibrationContext,
    *,
    poni_path: Path,
    mask_path: Path | None,
    flat_path: Path | None,
    error_prefix: str,
) -> None:
    actual_hashes = {
        "poni_sha256": sha256_file(poni_path),
        "mask_sha256": sha256_file(mask_path) if mask_path is not None else None,
        "flat_sha256": sha256_file(flat_path) if flat_path is not None else None,
    }
    for field, actual in actual_hashes.items():
        if getattr(calibration_context, field) != actual:
            raise ValueError(f"{error_prefix} {field} does not match the recorded file")


def write_calibration_record(
    path: str | Path,
    *,
    k_factor: object,
    calibration_context: CalibrationContext,
    calibration_uncertainty: CalibrationUncertaintyPayload | dict[str, object] | None,
    poni_path: str | Path,
    mask_path: str | Path | None,
    flat_path: str | Path | None,
) -> Path:
    """Persist a complete K plus calibration context with an integrity fingerprint."""

    if not isinstance(calibration_context, CalibrationContext):
        raise ValueError("a valid CalibrationContext is required")
    k_value = float(k_factor)
    if not math.isfinite(k_value) or k_value <= 0:
        raise ValueError("k_factor must be finite and > 0")

    poni = _resolve_operator_file(poni_path, required=True)
    mask = _resolve_operator_file(mask_path, required=False)
    flat = _resolve_operator_file(flat_path, required=False)
    assert poni is not None
    _validate_context_file_hashes(
        calibration_context,
        poni_path=poni,
        mask_path=mask,
        flat_path=flat,
        error_prefix="CalibrationContext",
    )

    uncertainty = None
    if calibration_uncertainty is not None:
        if not isinstance(calibration_uncertainty, dict):
            raise ValueError("calibration_uncertainty must be an object or null")
        uncertainty = build_calibration_uncertainty_payload(
            calibration_uncertainty.get("k_statistical_standard_uncertainty"),
            calibration_uncertainty.get("k_standard_uncertainty"),
            calibration_uncertainty.get("k_expanded_uncertainty"),
            calibration_uncertainty.get("coverage_factor"),
        )
    payload: dict[str, object] = {
        "schema": CALIBRATION_RECORD_SCHEMA,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "k_factor": k_value,
        "calibration_context": calibration_context.to_dict(),
        "calibration_context_fingerprint": calibration_context.fingerprint(),
        "calibration_uncertainty": uncertainty,
        "operator_files": {
            "poni": str(poni),
            "mask": str(mask) if mask is not None else "",
            "flat": str(flat) if flat is not None else "",
        },
    }
    payload["record_fingerprint"] = _calibration_record_fingerprint(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def read_calibration_record(path: str | Path) -> CalibrationRecordLoadResult:
    """Validate a complete record and return state only after every check succeeds."""

    record_path = Path(path)
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"calibration record is unreadable: {record_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != CALIBRATION_RECORD_SCHEMA:
        raise ValueError("calibration record schema mismatch")
    context_data = payload.get("calibration_context")
    if not isinstance(context_data, dict):
        raise ValueError("calibration record is missing CalibrationContext")
    if payload.get("record_fingerprint") != _calibration_record_fingerprint(payload):
        raise ValueError("calibration record fingerprint integrity check failed")
    try:
        context = CalibrationContext.from_dict(context_data)
    except Exception as exc:
        raise ValueError("calibration record contains an invalid CalibrationContext") from exc
    if payload.get("calibration_context_fingerprint") != context.fingerprint():
        raise ValueError("CalibrationContext fingerprint mismatch")

    try:
        k_value = float(payload.get("k_factor"))
    except (TypeError, ValueError) as exc:
        raise ValueError("calibration record k_factor must be finite and > 0") from exc
    if not math.isfinite(k_value) or k_value <= 0:
        raise ValueError("calibration record k_factor must be finite and > 0")

    operator_files = payload.get("operator_files")
    if not isinstance(operator_files, dict):
        raise ValueError("calibration record operator files are incomplete")
    poni = _resolve_operator_file(operator_files.get("poni"), required=True)
    mask = _resolve_operator_file(operator_files.get("mask"), required=False)
    flat = _resolve_operator_file(operator_files.get("flat"), required=False)
    assert poni is not None
    _validate_context_file_hashes(
        context,
        poni_path=poni,
        mask_path=mask,
        flat_path=flat,
        error_prefix="calibration record",
    )

    raw_uncertainty = payload.get("calibration_uncertainty")
    uncertainty = None
    if raw_uncertainty is not None:
        if not isinstance(raw_uncertainty, dict):
            raise ValueError("calibration record uncertainty must be an object or null")
        uncertainty = build_calibration_uncertainty_payload(
            raw_uncertainty.get("k_statistical_standard_uncertainty"),
            raw_uncertainty.get("k_standard_uncertainty"),
            raw_uncertainty.get("k_expanded_uncertainty"),
            raw_uncertainty.get("coverage_factor"),
        )

    return CalibrationRecordLoadResult(
        record_path=record_path,
        k_factor=k_value,
        calibration_context=context,
        calibration_uncertainty=uncertainty,
        poni_path=poni,
        mask_path=mask,
        flat_path=flat,
    )
