"""Execution policy helpers for batch-style workflows.

Centralizes resume/overwrite semantics so GUI and CLI orchestration paths can
apply identical behavior when existing output files are present.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunPolicy:
    """Policy controlling behavior when output targets already exist.

    Parameters
    ----------
    resume_enabled : bool
        If ``True``, existing outputs can be skipped.
    overwrite_existing : bool
        If ``True``, existing outputs are always regenerated.
    """

    resume_enabled: bool = True
    overwrite_existing: bool = False

    @property
    def mode(self) -> str:
        """Return normalized mode string.

        Returns
        -------
        str
            One of ``"overwrite"``, ``"resume-skip"``, ``"always-run"``.
        """
        if self.overwrite_existing:
            return "overwrite"
        if self.resume_enabled:
            return "resume-skip"
        return "always-run"

    def should_skip_existing(self, exists: bool) -> bool:
        """Return whether an existing output should be skipped."""
        return bool(exists) and self.resume_enabled and (not self.overwrite_existing)


def parse_run_policy(resume_enabled: bool, overwrite_existing: bool) -> RunPolicy:
    """Build a :class:`RunPolicy` from raw flags."""
    return RunPolicy(
        resume_enabled=bool(resume_enabled),
        overwrite_existing=bool(overwrite_existing),
    )


def should_skip_all_existing(existing_flags: list[bool], policy: RunPolicy) -> bool:
    """Return ``True`` when all expected outputs already exist and should skip."""
    if not existing_flags:
        return False
    return all(policy.should_skip_existing(flag) for flag in existing_flags)


def resolve_output_path_for_write(path: str | Path, policy: RunPolicy) -> Path:
    """Return the safe path to use for a write under ``policy``.

    This is the final guard before scientific output is written. Callers may
    still pre-skip existing files for performance, but this helper prevents a
    missed skip check from silently overwriting data.
    """
    target = Path(path)
    if not target.exists():
        return target
    if policy.overwrite_existing:
        return target
    if policy.resume_enabled:
        raise FileExistsError(f"resume-skip policy blocks writing existing output: {target}")

    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    for index in range(1, 10_000):
        candidate = parent / f"{stem}_rerun{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"could not allocate rerun output path for: {target}")
