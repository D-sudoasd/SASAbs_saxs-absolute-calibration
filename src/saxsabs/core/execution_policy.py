"""Execution policy helpers for batch-style workflows.

Centralizes resume/overwrite semantics so GUI and CLI orchestration paths can
apply identical behavior when existing output files are present.
"""

from __future__ import annotations

from dataclasses import dataclass


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
