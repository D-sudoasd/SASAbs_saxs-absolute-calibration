"""Immutable scientific context attached to an absolute K-factor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file without path-dependent state."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CalibrationContext:
    """Correction settings and standard provenance under which K was obtained."""

    formula_version: str
    monitor_mode: str
    poni_sha256: str
    mask_sha256: str | None
    flat_sha256: str | None
    correct_solid_angle: bool
    polarization_factor: float | None
    standard_key: str
    standard_thickness_cm: float

    def __post_init__(self) -> None:
        if self.monitor_mode not in {"rate", "integrated"}:
            raise ValueError("monitor_mode must be 'rate' or 'integrated'")
        if not str(self.formula_version).strip():
            raise ValueError("formula_version is required")
        if not str(self.poni_sha256).strip():
            raise ValueError("poni_sha256 is required")
        if not str(self.standard_key).strip():
            raise ValueError("standard_key is required")
        thickness = float(self.standard_thickness_cm)
        if not math.isfinite(thickness) or thickness <= 0:
            raise ValueError("standard_thickness_cm must be finite and > 0")
        if self.polarization_factor is not None:
            factor = float(self.polarization_factor)
            if not math.isfinite(factor) or factor < -1 or factor > 1:
                raise ValueError("polarization_factor must be finite and between -1 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CalibrationContext":
        return cls(**value)

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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

