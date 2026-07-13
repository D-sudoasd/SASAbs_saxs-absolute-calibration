"""Immutable scientific context attached to an absolute K-factor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from saxsabs.constants import (
    NIST_SRM3600_DATA,
    NIST_SRM3600_UNCERTAINTY,
    get_reference_data,
)

from .calibration import SRM3600_CERTIFIED_THICKNESS_CM


SRM3600_REFERENCE_MODEL_ID = "NIST_SRM3600_CERTIFICATE_TABLE_1"
SRM3600_REFERENCE_MODEL_VERSION = "NIST-SRM-3600-certificate-2016-table1"
WATER_REFERENCE_MODEL_ID = "WATER_IAPWS95_ORTHABER2000"
WATER_REFERENCE_MODEL_VERSION = "Orthaber2000-IAPWS95-saxsabs-v1"


@dataclass(frozen=True)
class ReferenceModelIdentity:
    """Stable identity and canonical data hash for a built-in reference model."""

    model_id: str
    model_version: str
    canonical_sha256: str


def normalize_standard_key(value: object) -> str:
    """Return the canonical key used for calibration-standard invariants."""
    if value is None:
        raise ValueError("standard_key is required")
    text = str(value).strip()
    if not text:
        raise ValueError("standard_key is required")
    compact = "".join(character for character in text.casefold() if character.isalnum())
    if compact in {"srm3600", "nistsrm3600"}:
        return "SRM3600"
    if compact in {"water", "water20c", "waterh2o20c", "h2o"}:
        return "Water_20C"
    return text


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file without path-dependent state."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_float_vector(values: Iterable[object], *, field_name: str) -> list[str]:
    result: list[str] = []
    for value in values:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{field_name} must contain only finite values")
        result.append(number.hex())
    return result


def canonical_reference_sha256(
    q: Iterable[object],
    intensity: Iterable[object],
    standard_uncertainty: Iterable[object] | None = None,
    expanded_uncertainty: Iterable[object] | None = None,
) -> str:
    """Hash canonical parsed q/I(/u/U) values independent of file formatting."""
    q_values = _canonical_float_vector(q, field_name="reference q")
    i_values = _canonical_float_vector(intensity, field_name="reference intensity")
    if not q_values or len(q_values) != len(i_values):
        raise ValueError("reference q and intensity must be non-empty and have equal length")
    standard_values = (
        None
        if standard_uncertainty is None
        else _canonical_float_vector(
            standard_uncertainty,
            field_name="reference standard uncertainty",
        )
    )
    expanded_values = (
        None
        if expanded_uncertainty is None
        else _canonical_float_vector(
            expanded_uncertainty,
            field_name="reference expanded uncertainty",
        )
    )
    if standard_values is not None and len(standard_values) != len(q_values):
        raise ValueError("reference standard uncertainty must match q shape")
    if expanded_values is not None and len(expanded_values) != len(q_values):
        raise ValueError("reference expanded uncertainty must match q shape")
    payload = {
        "schema": "saxsabs.canonical_reference.v1",
        "q_float64_hex": q_values,
        "intensity_float64_hex": i_values,
        "standard_uncertainty_float64_hex": standard_values,
        "expanded_uncertainty_float64_hex": expanded_values,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def builtin_reference_identity(
    standard_key: object,
    *,
    water_temperature_C: float | None = None,
) -> ReferenceModelIdentity:
    """Return the verified model identity for a built-in reference standard."""
    key = normalize_standard_key(standard_key)
    if key == "SRM3600":
        digest = canonical_reference_sha256(
            NIST_SRM3600_DATA[:, 0],
            NIST_SRM3600_DATA[:, 1],
            NIST_SRM3600_UNCERTAINTY[:, 0],
            NIST_SRM3600_UNCERTAINTY[:, 1],
        )
        return ReferenceModelIdentity(
            model_id=SRM3600_REFERENCE_MODEL_ID,
            model_version=SRM3600_REFERENCE_MODEL_VERSION,
            canonical_sha256=digest,
        )
    if key == "Water_20C":
        temperature = 20.0 if water_temperature_C is None else float(water_temperature_C)
        q_ref, i_ref = get_reference_data(key, temperature_C=temperature)
        return ReferenceModelIdentity(
            model_id=WATER_REFERENCE_MODEL_ID,
            model_version=WATER_REFERENCE_MODEL_VERSION,
            canonical_sha256=canonical_reference_sha256(q_ref, i_ref),
        )
    raise ValueError(f"standard {key!r} does not have a built-in reference model")


def _validate_optional_sha256(value: str | None, *, field_name: str) -> None:
    if value is None:
        return
    text = str(value).strip().lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field_name} must be a 64-character SHA-256 digest or null")


def _validate_positive(value: float | None, *, field_name: str) -> None:
    if value is None:
        return
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field_name} must be finite and > 0, or null when unavailable")


def _validate_non_negative(value: float | None, *, field_name: str) -> None:
    if value is None:
        return
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field_name} must be finite and >= 0, or null when unavailable")


def _validate_transmission(value: float | None, *, field_name: str) -> None:
    if value is None:
        return
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > 1:
        raise ValueError(f"{field_name} must be finite and in (0, 1], or null when unavailable")


def _validate_optional_text(value: str | None, *, field_name: str) -> None:
    if value is not None and not str(value).strip():
        raise ValueError(f"{field_name} must be non-empty or null")


@dataclass(frozen=True)
class CalibrationContext:
    """Correction settings and provenance under which an absolute K was obtained.

    The first ten fields form the legacy v1 context.  All later fields are
    optional for construction compatibility, but a v2 record is explicitly
    incomplete until source identity, reference model, and algorithm inputs are
    present and independently verifiable.
    """

    formula_version: str
    monitor_mode: str
    poni_sha256: str
    mask_sha256: str | None
    flat_sha256: str | None
    correct_solid_angle: bool
    polarization_factor: float | None
    standard_key: str
    standard_thickness_cm: float
    standard_data_sha256: str | None = None
    background_data_sha256: tuple[str, ...] = ()
    dark_data_sha256: tuple[str, ...] = ()
    standard_monitor: float | None = None
    standard_transmission: float | None = None
    standard_exposure_s: float | None = None
    background_monitors: tuple[float, ...] = ()
    background_transmissions: tuple[float, ...] = ()
    background_exposure_s: tuple[float, ...] = ()
    dark_exposure_s: tuple[float, ...] = ()
    water_temperature_C: float | None = None
    reference_curve_sha256: str | None = None
    q_window: tuple[float, float] | None = None
    reference_model_id: str | None = None
    reference_model_version: str | None = None
    reference_canonical_sha256: str | None = None
    background_scale_alpha: float | None = None
    background_composition_rule: str | None = None
    integration_unit: str | None = None
    integration_method: str | None = None
    integration_engine_version: str | None = None
    integration_npt: int | None = None
    robust_estimator: str | None = None
    robust_mad_multiplier: float | None = None
    robust_positive_floor: float | None = None
    robust_min_points: int | None = None
    robust_zero_mad_relative_tolerance: float | None = None

    def __post_init__(self) -> None:
        if self.monitor_mode not in {"rate", "integrated"}:
            raise ValueError("monitor_mode must be 'rate' or 'integrated'")
        if not str(self.formula_version).strip():
            raise ValueError("formula_version is required")
        if not str(self.poni_sha256).strip():
            raise ValueError("poni_sha256 is required")
        standard_key = normalize_standard_key(self.standard_key)
        object.__setattr__(self, "standard_key", standard_key)
        thickness = float(self.standard_thickness_cm)
        object.__setattr__(self, "standard_thickness_cm", thickness)
        if not math.isfinite(thickness) or thickness <= 0:
            raise ValueError("standard_thickness_cm must be finite and > 0")
        if standard_key == "SRM3600" and not math.isclose(
            thickness,
            SRM3600_CERTIFIED_THICKNESS_CM,
            rel_tol=0.0,
            abs_tol=math.ulp(SRM3600_CERTIFIED_THICKNESS_CM),
        ):
            raise ValueError(
                "SRM 3600 standard_thickness_cm must equal the certified 0.1055 cm"
            )
        if self.polarization_factor is not None:
            factor = float(self.polarization_factor)
            if not math.isfinite(factor) or factor < -1 or factor > 1:
                raise ValueError("polarization_factor must be finite and between -1 and 1")

        sequence_fields = (
            "background_data_sha256",
            "dark_data_sha256",
            "background_monitors",
            "background_transmissions",
            "background_exposure_s",
            "dark_exposure_s",
        )
        for field_name in sequence_fields:
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        if self.q_window is not None:
            object.__setattr__(self, "q_window", tuple(self.q_window))

        _validate_optional_sha256(
            self.standard_data_sha256,
            field_name="standard_data_sha256",
        )
        _validate_optional_sha256(
            self.reference_curve_sha256,
            field_name="reference_curve_sha256",
        )
        _validate_optional_sha256(
            self.reference_canonical_sha256,
            field_name="reference_canonical_sha256",
        )
        for field_name, values in (
            ("background_data_sha256", self.background_data_sha256),
            ("dark_data_sha256", self.dark_data_sha256),
        ):
            for value in values:
                _validate_optional_sha256(value, field_name=field_name)

        _validate_positive(self.standard_monitor, field_name="standard_monitor")
        _validate_positive(self.standard_exposure_s, field_name="standard_exposure_s")
        _validate_transmission(
            self.standard_transmission,
            field_name="standard_transmission",
        )
        for field_name, values, validator in (
            ("background_monitors", self.background_monitors, _validate_positive),
            (
                "background_transmissions",
                self.background_transmissions,
                _validate_transmission,
            ),
            ("background_exposure_s", self.background_exposure_s, _validate_positive),
            ("dark_exposure_s", self.dark_exposure_s, _validate_positive),
        ):
            for value in values:
                validator(value, field_name=field_name)

        background_count = len(self.background_data_sha256)
        for field_name, values in (
            ("background_monitors", self.background_monitors),
            ("background_transmissions", self.background_transmissions),
            ("background_exposure_s", self.background_exposure_s),
        ):
            if values and len(values) != background_count:
                raise ValueError(
                    f"{field_name} must have one value per background_data_sha256 entry"
                )
        if self.dark_exposure_s and len(self.dark_exposure_s) != len(self.dark_data_sha256):
            raise ValueError("dark_exposure_s must have one value per dark_data_sha256 entry")

        if self.water_temperature_C is not None:
            temperature = float(self.water_temperature_C)
            if not math.isfinite(temperature) or temperature < 4 or temperature > 40:
                raise ValueError("water_temperature_C must be finite and in [4, 40] degC")
            object.__setattr__(self, "water_temperature_C", temperature)
        if self.q_window is not None:
            if len(self.q_window) != 2:
                raise ValueError("q_window must contain exactly two values")
            q_min, q_max = (float(value) for value in self.q_window)
            if (
                not math.isfinite(q_min)
                or not math.isfinite(q_max)
                or q_min < 0
                or q_min >= q_max
            ):
                raise ValueError("q_window must contain finite increasing non-negative values")
            object.__setattr__(self, "q_window", (q_min, q_max))

        for field_name in (
            "reference_model_id",
            "reference_model_version",
            "background_composition_rule",
            "integration_unit",
            "integration_method",
            "integration_engine_version",
            "robust_estimator",
        ):
            _validate_optional_text(getattr(self, field_name), field_name=field_name)
        _validate_non_negative(
            self.background_scale_alpha,
            field_name="background_scale_alpha",
        )
        _validate_positive(self.robust_mad_multiplier, field_name="robust_mad_multiplier")
        _validate_non_negative(self.robust_positive_floor, field_name="robust_positive_floor")
        _validate_positive(
            self.robust_zero_mad_relative_tolerance,
            field_name="robust_zero_mad_relative_tolerance",
        )
        if self.integration_npt is not None:
            npt = int(self.integration_npt)
            if isinstance(self.integration_npt, bool) or npt != self.integration_npt or npt < 3:
                raise ValueError("integration_npt must be an integer >= 3, or null")
            object.__setattr__(self, "integration_npt", npt)
        if self.robust_min_points is not None:
            points = int(self.robust_min_points)
            if (
                isinstance(self.robust_min_points, bool)
                or points != self.robust_min_points
                or points < 3
            ):
                raise ValueError("robust_min_points must be an integer >= 3, or null")
            object.__setattr__(self, "robust_min_points", points)

        if standard_key in {"SRM3600", "Water_20C"}:
            expected = builtin_reference_identity(
                standard_key,
                water_temperature_C=self.water_temperature_C,
            )
            for field_name, expected_value in (
                ("reference_model_id", expected.model_id),
                ("reference_model_version", expected.model_version),
                ("reference_canonical_sha256", expected.canonical_sha256),
            ):
                actual = getattr(self, field_name)
                if actual is not None and actual != expected_value:
                    raise ValueError(
                        f"{field_name} does not match the built-in {standard_key} model"
                    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CalibrationContext":
        normalized = dict(value)
        for field_name in (
            "background_data_sha256",
            "dark_data_sha256",
            "background_monitors",
            "background_transmissions",
            "background_exposure_s",
            "dark_exposure_s",
            "q_window",
        ):
            if field_name in normalized and normalized[field_name] is not None:
                normalized[field_name] = tuple(normalized[field_name])
        return cls(**normalized)

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def provenance_missing_fields(self) -> tuple[str, ...]:
        """Return absent fields required to reproduce K independently."""
        missing: list[str] = []
        required_scalars = (
            "standard_data_sha256",
            "standard_monitor",
            "standard_transmission",
            "standard_exposure_s",
            "q_window",
            "reference_model_id",
            "reference_model_version",
            "reference_canonical_sha256",
            "background_scale_alpha",
            "background_composition_rule",
            "integration_unit",
            "integration_method",
            "integration_engine_version",
            "integration_npt",
            "robust_estimator",
            "robust_mad_multiplier",
            "robust_positive_floor",
            "robust_min_points",
            "robust_zero_mad_relative_tolerance",
        )
        for field_name in required_scalars:
            if getattr(self, field_name) is None:
                missing.append(field_name)
        required_sequences = (
            "background_data_sha256",
            "dark_data_sha256",
            "background_monitors",
            "background_transmissions",
            "background_exposure_s",
            "dark_exposure_s",
        )
        for field_name in required_sequences:
            if not getattr(self, field_name):
                missing.append(field_name)

        method = str(self.integration_method or "").strip().casefold()
        if method.endswith(":auto") or method.endswith(":default"):
            missing.append("integration_method_resolved")

        if self.standard_key == "Water_20C":
            if self.water_temperature_C is None:
                missing.append("water_temperature_C")
        elif self.standard_key != "SRM3600":
            if self.reference_curve_sha256 is None:
                missing.append("reference_curve_sha256")
        return tuple(missing)

    def operator_payload(self) -> dict[str, Any]:
        """Return settings that must match when K is applied to a sample."""
        return {
            "formula_version": self.formula_version,
            "monitor_mode": self.monitor_mode,
            "poni_sha256": self.poni_sha256,
            "mask_sha256": self.mask_sha256,
            "flat_sha256": self.flat_sha256,
            "correct_solid_angle": self.correct_solid_angle,
            "polarization_factor": self.polarization_factor,
        }

    def operator_compatibility_issues(self, current: "CalibrationContext") -> list[str]:
        expected = self.operator_payload()
        actual = current.operator_payload()
        return [name for name, value in expected.items() if actual.get(name) != value]

    def assert_operator_compatible(self, current: "CalibrationContext") -> None:
        issues = self.operator_compatibility_issues(current)
        if issues:
            raise ValueError(
                "K-factor calibration context mismatch: " + ", ".join(sorted(issues))
            )
