"""Typed persistence helpers for workbench absolute-calibration records."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable, TypedDict
import uuid

from .calibration_context import (
    CalibrationContext,
    canonical_reference_sha256,
    sha256_file,
)


CALIBRATION_RECORD_SCHEMA_V1 = "saxsabs.workbench_calibration_record.v1"
CALIBRATION_RECORD_SCHEMA_V2 = "saxsabs.workbench_calibration_record.v2"
CALIBRATION_RECORD_SCHEMA = CALIBRATION_RECORD_SCHEMA_V2


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
    schema: str = CALIBRATION_RECORD_SCHEMA_V2
    provenance_complete: bool = False
    provenance_missing: tuple[str, ...] = ()
    standard_data_path: Path | None = None
    background_data_paths: tuple[Path, ...] = ()
    dark_data_paths: tuple[Path, ...] = ()
    reference_curve_path: Path | None = None


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


def _validate_uncertainty_invariants(
    statistical: float | None,
    standard: float | None,
    expanded: float | None,
    coverage: float | None,
) -> None:
    if standard is None:
        if expanded is not None:
            raise ValueError("expanded uncertainty requires k_standard_uncertainty")
        if coverage is not None:
            raise ValueError("coverage_factor requires k_standard_uncertainty")
        return
    if statistical is not None and statistical > standard and not math.isclose(
        statistical,
        standard,
        rel_tol=1e-12,
        abs_tol=0.0,
    ):
        raise ValueError(
            "k_standard_uncertainty cannot be smaller than its statistical component"
        )
    if coverage is None:
        if expanded is not None:
            raise ValueError("expanded uncertainty requires coverage_factor")
        return
    if expanded is None:
        raise ValueError("coverage_factor requires k_expanded_uncertainty")
    expected = coverage * standard
    if not math.isclose(expanded, expected, rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError("k_expanded_uncertainty must equal coverage_factor * k_standard_uncertainty")


def build_calibration_uncertainty_payload(
    k_statistical_standard_uncertainty: object,
    k_standard_uncertainty: object,
    k_expanded_uncertainty: object,
    coverage_factor: object,
) -> CalibrationUncertaintyPayload:
    """Normalize optional K uncertainties and enforce their physical invariants."""

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
    _validate_uncertainty_invariants(statistical, standard, expanded, coverage)

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


def _context_payload_fingerprint(payload: dict[str, object]) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_operator_file(
    path: object,
    *,
    required: bool,
    base_dir: Path | None = None,
) -> Path | None:
    text = str(path or "").strip()
    if not text:
        if required:
            raise ValueError("calibration record operator files are incomplete")
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    resolved = candidate.resolve()
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


def _resolve_source_path(
    path: object,
    *,
    field_name: str,
    base_dir: Path | None = None,
) -> Path | None:
    text = str(path or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"calibration provenance {field_name} file not found: {resolved}")
    return resolved


def _normalize_path_sequence(values: object) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, Path)):
        return (values,)
    try:
        return tuple(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("calibration source paths must be a sequence") from exc


def _resolve_source_sequence(
    values: object,
    *,
    field_name: str,
    base_dir: Path | None = None,
) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for index, value in enumerate(_normalize_path_sequence(values)):
        path = _resolve_source_path(
            value,
            field_name=f"{field_name}[{index}]",
            base_dir=base_dir,
        )
        if path is None:
            raise ValueError(f"{field_name}[{index}] must not be empty")
        resolved.append(path)
    return tuple(resolved)


def _validate_source_files(
    context: CalibrationContext,
    *,
    standard: Path | None,
    backgrounds: tuple[Path, ...],
    darks: tuple[Path, ...],
    reference: Path | None,
) -> tuple[str, ...]:
    missing: list[str] = []

    def validate_single(
        path: Path | None,
        expected_hash: str | None,
        *,
        path_field: str,
        hash_field: str,
    ) -> None:
        if path is None:
            missing.append(path_field)
            return
        if expected_hash is None:
            raise ValueError(f"{path_field} was supplied without {hash_field}")
        if sha256_file(path) != expected_hash:
            raise ValueError(f"{hash_field} does not match {path_field}")

    validate_single(
        standard,
        context.standard_data_sha256,
        path_field="source_files.standard",
        hash_field="standard_data_sha256",
    )

    def validate_sequence(
        paths: tuple[Path, ...],
        expected_hashes: tuple[str, ...],
        *,
        path_field: str,
        hash_field: str,
    ) -> None:
        if not paths:
            missing.append(path_field)
            return
        if len(paths) != len(expected_hashes):
            raise ValueError(
                f"{path_field} must have one ordered path per {hash_field} entry"
            )
        for index, (path, expected_hash) in enumerate(zip(paths, expected_hashes)):
            if sha256_file(path) != expected_hash:
                raise ValueError(
                    f"{hash_field}[{index}] does not match {path_field}[{index}]"
                )

    validate_sequence(
        backgrounds,
        context.background_data_sha256,
        path_field="source_files.background",
        hash_field="background_data_sha256",
    )
    validate_sequence(
        darks,
        context.dark_data_sha256,
        path_field="source_files.dark",
        hash_field="dark_data_sha256",
    )

    if context.standard_key not in {"SRM3600", "Water_20C"}:
        validate_single(
            reference,
            context.reference_curve_sha256,
            path_field="source_files.reference",
            hash_field="reference_curve_sha256",
        )
    elif reference is not None:
        raise ValueError(
            "source_files.reference is only valid for a user-provided reference curve"
        )
    return tuple(missing)


def _reference_curve_payload(
    q: Iterable[object] | None,
    intensity: Iterable[object] | None,
    standard_uncertainty: Iterable[object] | None,
    expanded_uncertainty: Iterable[object] | None,
) -> dict[str, object] | None:
    if q is None and intensity is None:
        if standard_uncertainty is not None or expanded_uncertainty is not None:
            raise ValueError("reference uncertainty requires reference q and intensity")
        return None
    if q is None or intensity is None:
        raise ValueError("reference q and intensity must be supplied together")
    q_values = [float(value) for value in q]
    intensity_values = [float(value) for value in intensity]
    standard_values = (
        None
        if standard_uncertainty is None
        else [float(value) for value in standard_uncertainty]
    )
    expanded_values = (
        None
        if expanded_uncertainty is None
        else [float(value) for value in expanded_uncertainty]
    )
    canonical_reference_sha256(
        q_values,
        intensity_values,
        standard_values,
        expanded_values,
    )
    return {
        "q": q_values,
        "intensity": intensity_values,
        "standard_uncertainty": standard_values,
        "expanded_uncertainty": expanded_values,
    }


def _validate_reference_curve_payload(
    context: CalibrationContext,
    payload: object,
) -> tuple[str, ...]:
    custom_reference = context.standard_key not in {"SRM3600", "Water_20C"}
    if payload is None:
        return ("reference_curve.canonical_values",) if custom_reference else ()
    if not isinstance(payload, dict):
        raise ValueError("reference_curve must be an object or null")
    try:
        digest = canonical_reference_sha256(
            payload.get("q", ()),
            payload.get("intensity", ()),
            payload.get("standard_uncertainty"),
            payload.get("expanded_uncertainty"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("reference_curve contains invalid canonical values") from exc
    if digest != context.reference_canonical_sha256:
        raise ValueError(
            "reference_canonical_sha256 does not match the serialized canonical curve"
        )
    return ()


def _merge_missing_fields(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(field for group in groups for field in group))

def _payload_path_list(value: object, *, field_name: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an ordered array")
    return tuple(value)

def _relative_path_for_record(path: Path | None, *, record_dir: Path) -> str:
    if path is None:
        return ""
    try:
        return os.path.relpath(path, start=record_dir)
    except ValueError:
        # Windows paths on different drives cannot be relativized.
        return str(path)


def _atomic_write_new_text(target: Path, text: str) -> None:
    """Atomically publish a new record without replacing any existing history."""
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing calibration record: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise FileExistsError(
                f"refusing to overwrite existing calibration record: {target}"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def write_calibration_record(
    path: str | Path,
    *,
    k_factor: object,
    calibration_context: CalibrationContext,
    calibration_uncertainty: CalibrationUncertaintyPayload | dict[str, object] | None,
    poni_path: str | Path,
    mask_path: str | Path | None,
    flat_path: str | Path | None,
    standard_data_path: str | Path | None = None,
    background_data_paths: Iterable[str | Path] | None = None,
    dark_data_paths: Iterable[str | Path] | None = None,
    reference_curve_path: str | Path | None = None,
    reference_q: Iterable[object] | None = None,
    reference_i: Iterable[object] | None = None,
    reference_standard_uncertainty: Iterable[object] | None = None,
    reference_expanded_uncertainty: Iterable[object] | None = None,
) -> Path:
    """Persist a v2 K record with provenance status and an integrity fingerprint."""

    if not isinstance(calibration_context, CalibrationContext):
        raise ValueError("a valid CalibrationContext is required")
    k_value = float(k_factor)
    if not math.isfinite(k_value) or k_value <= 0:
        raise ValueError("k_factor must be finite and > 0")

    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing calibration record: {target}")

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
    standard_source = _resolve_source_path(
        standard_data_path,
        field_name="standard",
    )
    background_sources = _resolve_source_sequence(
        background_data_paths,
        field_name="background",
    )
    dark_sources = _resolve_source_sequence(
        dark_data_paths,
        field_name="dark",
    )
    reference_source = _resolve_source_path(
        reference_curve_path,
        field_name="reference",
    )
    source_missing = _validate_source_files(
        calibration_context,
        standard=standard_source,
        backgrounds=background_sources,
        darks=dark_sources,
        reference=reference_source,
    )
    reference_curve = _reference_curve_payload(
        reference_q,
        reference_i,
        reference_standard_uncertainty,
        reference_expanded_uncertainty,
    )
    reference_missing = _validate_reference_curve_payload(
        calibration_context,
        reference_curve,
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

    missing = _merge_missing_fields(
        calibration_context.provenance_missing_fields(),
        source_missing,
        reference_missing,
    )
    payload: dict[str, object] = {
        "schema": CALIBRATION_RECORD_SCHEMA_V2,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "k_factor": k_value,
        "calibration_context": calibration_context.to_dict(),
        "calibration_context_fingerprint": calibration_context.fingerprint(),
        "calibration_uncertainty": uncertainty,
        "provenance": {
            "status": "complete" if not missing else "incomplete",
            "missing_fields": list(missing),
        },
        "operator_files": {
            "poni": _relative_path_for_record(poni, record_dir=target.parent),
            "mask": _relative_path_for_record(mask, record_dir=target.parent),
            "flat": _relative_path_for_record(flat, record_dir=target.parent),
        },
        "source_files": {
            "standard": _relative_path_for_record(
                standard_source,
                record_dir=target.parent,
            ),
            "background": [
                _relative_path_for_record(source, record_dir=target.parent)
                for source in background_sources
            ],
            "dark": [
                _relative_path_for_record(source, record_dir=target.parent)
                for source in dark_sources
            ],
            "reference": _relative_path_for_record(
                reference_source,
                record_dir=target.parent,
            ),
        },
        "reference_curve": reference_curve,
    }
    payload["record_fingerprint"] = _calibration_record_fingerprint(payload)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    _atomic_write_new_text(target, serialized)
    return target


def read_calibration_record(path: str | Path) -> CalibrationRecordLoadResult:
    """Validate a v1/v2 record and return state only after every check succeeds."""

    record_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"calibration record is unreadable: {record_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("calibration record schema mismatch")
    schema = payload.get("schema")
    if schema not in {CALIBRATION_RECORD_SCHEMA_V1, CALIBRATION_RECORD_SCHEMA_V2}:
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
    expected_context_fingerprint = (
        _context_payload_fingerprint(context_data)
        if schema == CALIBRATION_RECORD_SCHEMA_V1
        else context.fingerprint()
    )
    if payload.get("calibration_context_fingerprint") != expected_context_fingerprint:
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
    poni = _resolve_operator_file(
        operator_files.get("poni"),
        required=True,
        base_dir=record_path.parent,
    )
    mask = _resolve_operator_file(
        operator_files.get("mask"),
        required=False,
        base_dir=record_path.parent,
    )
    flat = _resolve_operator_file(
        operator_files.get("flat"),
        required=False,
        base_dir=record_path.parent,
    )
    assert poni is not None
    _validate_context_file_hashes(
        context,
        poni_path=poni,
        mask_path=mask,
        flat_path=flat,
        error_prefix="calibration record",
    )

    standard_source: Path | None = None
    background_sources: tuple[Path, ...] = ()
    dark_sources: tuple[Path, ...] = ()
    reference_source: Path | None = None
    source_missing: tuple[str, ...] = ()
    reference_missing: tuple[str, ...] = ()
    if schema == CALIBRATION_RECORD_SCHEMA_V2:
        source_files = payload.get("source_files")
        if source_files is None:
            source_files = {
                "standard": "",
                "background": [],
                "dark": [],
                "reference": "",
            }
        if not isinstance(source_files, dict):
            raise ValueError("calibration record source_files must be an object")
        standard_source = _resolve_source_path(
            source_files.get("standard"),
            field_name="standard",
            base_dir=record_path.parent,
        )
        background_sources = _resolve_source_sequence(
            _payload_path_list(
                source_files.get("background"),
                field_name="source_files.background",
            ),
            field_name="background",
            base_dir=record_path.parent,
        )
        dark_sources = _resolve_source_sequence(
            _payload_path_list(
                source_files.get("dark"),
                field_name="source_files.dark",
            ),
            field_name="dark",
            base_dir=record_path.parent,
        )
        reference_source = _resolve_source_path(
            source_files.get("reference"),
            field_name="reference",
            base_dir=record_path.parent,
        )
        source_missing = _validate_source_files(
            context,
            standard=standard_source,
            backgrounds=background_sources,
            darks=dark_sources,
            reference=reference_source,
        )
        reference_missing = _validate_reference_curve_payload(
            context,
            payload.get("reference_curve"),
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

    context_missing = context.provenance_missing_fields()
    if schema == CALIBRATION_RECORD_SCHEMA_V1:
        provenance_missing = ("legacy_schema_v1", *context_missing)
    else:
        provenance_missing = _merge_missing_fields(
            context_missing,
            source_missing,
            reference_missing,
        )
        provenance = payload.get("provenance")
        expected_provenance = {
            "status": "complete" if not provenance_missing else "incomplete",
            "missing_fields": list(provenance_missing),
        }
        if provenance != expected_provenance:
            raise ValueError("calibration record provenance status does not match its context")

    return CalibrationRecordLoadResult(
        record_path=record_path,
        k_factor=k_value,
        calibration_context=context,
        calibration_uncertainty=uncertainty,
        poni_path=poni,
        mask_path=mask,
        flat_path=flat,
        schema=str(schema),
        provenance_complete=not provenance_missing,
        provenance_missing=provenance_missing,
        standard_data_path=standard_source,
        background_data_paths=background_sources,
        dark_data_paths=dark_sources,
        reference_curve_path=reference_source,
    )
