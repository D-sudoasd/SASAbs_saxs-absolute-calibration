"""Preflight risk scoring helpers for SAXS batch workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightGateSummary:
    """Summary of preflight quality gate outcome."""

    level: str
    score: int
    total_files: int
    failed_files: int
    warning_count: int
    risky_files: int

    @property
    def is_blocked(self) -> bool:
        return self.level == "BLOCKED"


def evaluate_preflight_gate(
    total_files: int,
    failed_files: int,
    warning_count: int,
    risky_files: int = 0,
) -> PreflightGateSummary:
    """Evaluate preflight gate level from lightweight run-readiness signals.

    Scoring is intentionally conservative for beamline operations:

    - failed file contributes 5 points
    - risky file contributes 2 points
    - warning contributes 1 point
    """
    total = max(0, int(total_files))
    failed = max(0, int(failed_files))
    warnings = max(0, int(warning_count))
    risky = max(0, int(risky_files))

    score = failed * 5 + risky * 2 + warnings

    if total <= 0 or failed > 0:
        level = "BLOCKED"
    elif score >= 8 or warnings >= 6 or risky >= max(2, total // 2):
        level = "CAUTION"
    elif score > 0:
        level = "CAUTION"
    else:
        level = "READY"

    return PreflightGateSummary(
        level=level,
        score=score,
        total_files=total,
        failed_files=failed,
        warning_count=warnings,
        risky_files=risky,
    )
