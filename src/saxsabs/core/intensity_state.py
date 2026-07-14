"""Machine-readable intensity/correction state for 1-D SAXS profiles.

The workbench accepts external profiles and can apply absolute-scale operators.
Column-name heuristics alone are not sufficient to decide whether those
operators have already been applied.  This module keeps that decision small,
typed, and fail-closed so every UI/CLI path can share the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from collections.abc import Iterable, Mapping


class IntensityState(str, Enum):
    """Scientific state of a profile before a requested transformation."""

    RELATIVE = "relative"
    RAW_COUNTS = "raw_counts"
    ABSOLUTE_CM_INV = "absolute_cm^-1"
    AMBIGUOUS = "ambiguous"


ABSOLUTE_CORRECTIONS = frozenset({"thickness", "k"})
KNOWN_CORRECTIONS = frozenset(
    {
        "dark",
        "background",
        "monitor",
        "transmission",
        "thickness",
        "k",
        "solid_angle",
        "polarization",
        "flat_field",
        "buffer",
    }
)


@dataclass(frozen=True)
class IntensityStateAssessment:
    """Classification result with auditable evidence."""

    state: IntensityState
    corrections_applied: tuple[str, ...]
    evidence: tuple[str, ...]
    do_not_repeat: tuple[str, ...] = ()

    @property
    def is_absolute(self) -> bool:
        return self.state is IntensityState.ABSOLUTE_CM_INV

    @property
    def protected_corrections(self) -> tuple[str, ...]:
        """Corrections blocked from repetition, without treating guards as proof."""

        return tuple(sorted(set(self.corrections_applied) | set(self.do_not_repeat)))


def _normalized_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _canonical_correction(value: object) -> str:
    token = _normalized_token(value)
    aliases = {
        "dark": "dark",
        "darkfield": "dark",
        "background": "background",
        "bg": "background",
        "monitor": "monitor",
        "mon": "monitor",
        "transmission": "transmission",
        "trans": "transmission",
        "t": "transmission",
        "thickness": "thickness",
        "d": "thickness",
        "k": "k",
        "kfactor": "k",
        "solidangle": "solid_angle",
        "polarization": "polarization",
        "flat": "flat_field",
        "flatfield": "flat_field",
        "buffer": "buffer",
    }
    canonical = aliases.get(token)
    if canonical is None:
        raise ValueError(f"unknown correction ledger entry: {value!r}")
    return canonical


def parse_correction_ledger(value: object) -> tuple[str, ...]:
    """Parse a correction ledger without silently accepting unknown entries."""

    if value is None:
        return ()
    items: Iterable[object]
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"none", "null", "[]"}:
            return ()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid JSON correction ledger") from exc
            if not isinstance(decoded, list):
                raise ValueError("correction ledger JSON must be a list")
            items = decoded
        else:
            items = re.split(r"[,;|]+", text)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        items = value
    else:
        raise ValueError("correction ledger must be a list or delimited string")

    canonical = {_canonical_correction(item) for item in items if str(item).strip()}
    return tuple(sorted(canonical))


def serialize_correction_ledger(corrections: Iterable[object]) -> str:
    """Return a stable JSON representation suitable for text/HDF5 metadata."""

    return json.dumps(list(parse_correction_ledger(corrections)), separators=(",", ":"))


def _state_from_metadata(value: object) -> IntensityState | None:
    token = _normalized_token(value)
    aliases = {
        "relative": IntensityState.RELATIVE,
        "relativeintensity": IntensityState.RELATIVE,
        "raw": IntensityState.RAW_COUNTS,
        "rawcounts": IntensityState.RAW_COUNTS,
        "counts": IntensityState.RAW_COUNTS,
        "absolutecm1": IntensityState.ABSOLUTE_CM_INV,
        "absolute1cm": IntensityState.ABSOLUTE_CM_INV,
        "absolute": IntensityState.ABSOLUTE_CM_INV,
        "ambiguous": IntensityState.AMBIGUOUS,
        "unknown": IntensityState.AMBIGUOUS,
    }
    return aliases.get(token) if token else None


def assess_intensity_state(profile: Mapping[str, object]) -> IntensityStateAssessment:
    """Classify an external profile using metadata, units, and column semantics.

    Explicit metadata is strongest.  Conflicting evidence is never resolved by
    guessing; it yields ``AMBIGUOUS`` and must be handled by the caller.
    """

    provenance = profile.get("operator_provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    evidence: list[str] = []

    if "intensity_state" in provenance:
        explicit_state_value = provenance["intensity_state"]
    else:
        explicit_state_value = profile.get("intensity_state")
    explicit_state = _state_from_metadata(explicit_state_value)
    explicit_state_is_nonempty = (
        explicit_state_value is not None and bool(str(explicit_state_value).strip())
    )
    invalid_explicit_state = explicit_state_is_nonempty and explicit_state is None
    if explicit_state is not None:
        evidence.append(f"metadata:intensity_state={explicit_state.value}")
    elif invalid_explicit_state:
        evidence.append("invalid_metadata:intensity_state")

    corrections_present = (
        "corrections_applied" in provenance or "corrections_applied" in profile
    )
    do_not_repeat_present = "do_not_repeat" in provenance or "do_not_repeat" in profile
    correction_ledger = parse_correction_ledger(
        provenance.get("corrections_applied", profile.get("corrections_applied"))
    )
    repeat_ledger = parse_correction_ledger(
        provenance.get("do_not_repeat", profile.get("do_not_repeat"))
    )
    ledger_conflict = (
        corrections_present
        and do_not_repeat_present
        and set(correction_ledger) != set(repeat_ledger)
    )
    if correction_ledger:
        evidence.append("ledger:corrections_applied=" + ",".join(correction_ledger))
    if repeat_ledger:
        evidence.append("ledger:do_not_repeat=" + ",".join(repeat_ledger))
    if ledger_conflict:
        evidence.append("conflicting_correction_ledgers")

    semantic_states: set[IntensityState] = set()
    i_col = _normalized_token(profile.get("i_col", ""))
    if i_col.startswith("iabs") or "absolut" in i_col or "cm1" in i_col:
        semantic_states.add(IntensityState.ABSOLUTE_CM_INV)
        evidence.append(f"column:{profile.get('i_col')}")
    elif i_col.startswith("irel") or "relative" in i_col:
        semantic_states.add(IntensityState.RELATIVE)
        evidence.append(f"column:{profile.get('i_col')}")
    elif i_col in {"count", "counts", "signal", "rawintensity"}:
        semantic_states.add(IntensityState.RAW_COUNTS)
        evidence.append(f"column:{profile.get('i_col')}")

    unit = _normalized_token(
        profile.get("intensity_unit", provenance.get("intensity_unit", ""))
    )
    if unit in {"1cm", "cm1", "cminverse", "percm"}:
        semantic_states.add(IntensityState.ABSOLUTE_CM_INV)
        evidence.append(f"unit:{profile.get('intensity_unit', provenance.get('intensity_unit'))}")

    # ``corrections_applied`` is evidence about the physical state.  The
    # ``do_not_repeat`` ledger is an execution guard and may be stricter than
    # the recorded state, so it must not by itself relabel a relative profile
    # as absolute.  Both ledgers are still merged above for duplicate-operation
    # checks.
    if ABSOLUTE_CORRECTIONS.issubset(correction_ledger):
        semantic_states.add(IntensityState.ABSOLUTE_CM_INV)
    if explicit_state is not None:
        semantic_states.add(explicit_state)

    non_ambiguous = {state for state in semantic_states if state is not IntensityState.AMBIGUOUS}
    if (
        len(non_ambiguous) > 1
        or explicit_state is IntensityState.AMBIGUOUS
        or invalid_explicit_state
        or ledger_conflict
    ):
        state = IntensityState.AMBIGUOUS
        evidence.append("conflict_or_explicit_ambiguity")
    elif non_ambiguous:
        state = next(iter(non_ambiguous))
    else:
        state = IntensityState.AMBIGUOUS
        evidence.append("no_machine_readable_intensity_state")

    return IntensityStateAssessment(
        state=state,
        corrections_applied=correction_ledger,
        evidence=tuple(evidence),
        do_not_repeat=repeat_ledger,
    )


def require_relative_input_for_absolute_scaling(
    profile: Mapping[str, object],
    *,
    profile_name: str = "profile",
    corrections_to_apply: Iterable[object] = ABSOLUTE_CORRECTIONS,
    required_existing_corrections: Iterable[object] = (),
) -> IntensityStateAssessment:
    """Require a relative profile before applying K or K/d.

    Absolute and ambiguous profiles are rejected with distinct messages so the
    UI can explain whether the problem is duplicate correction or missing
    provenance.
    """

    assessment = assess_intensity_state(profile)
    if assessment.state is IntensityState.ABSOLUTE_CM_INV:
        raise ValueError(
            f"{profile_name}: input is already absolute intensity (cm^-1); "
            "refusing to apply K or thickness again"
        )
    if assessment.state is IntensityState.RAW_COUNTS:
        raise ValueError(
            f"{profile_name}: input contains raw counts, not a reduced relative profile; "
            "complete dark/background/monitor/transmission normalization before K or K/d"
        )
    if assessment.state is IntensityState.AMBIGUOUS:
        raise ValueError(
            f"{profile_name}: intensity state is ambiguous; provide machine-readable "
            "intensity_state=relative provenance before applying K or K/d"
        )
    requested = set(parse_correction_ledger(corrections_to_apply))
    required_existing = set(parse_correction_ledger(required_existing_corrections))
    overlap = set(assessment.protected_corrections) & requested
    if overlap:
        raise ValueError(
            f"{profile_name}: correction ledger already contains requested correction(s): "
            + ", ".join(sorted(overlap))
        )
    # Execution guards prevent duplication but are not evidence that a
    # correction was physically applied.  Required inherited corrections must
    # therefore come from corrections_applied only.
    missing = required_existing - set(assessment.corrections_applied)
    if missing:
        raise ValueError(
            f"{profile_name}: correction ledger is missing required existing correction(s): "
            + ", ".join(sorted(missing))
        )
    return assessment


def require_absolute_input_for_buffer_subtraction(
    profile: Mapping[str, object],
    *,
    profile_name: str = "buffer",
) -> IntensityStateAssessment:
    """Require a fully traceable absolute buffer before subtracting from cm^-1 data."""

    assessment = assess_intensity_state(profile)
    if assessment.state is not IntensityState.ABSOLUTE_CM_INV:
        raise ValueError(
            f"{profile_name}: buffer must be explicit absolute intensity in cm^-1"
        )
    provenance = profile.get("operator_provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    raw_unit = profile.get("intensity_unit", provenance.get("intensity_unit", ""))
    if _normalized_token(raw_unit) not in {"1cm", "cm1", "cminverse", "percm"}:
        raise ValueError(f"{profile_name}: buffer intensity_unit must be 1/cm")
    corrections = set(assessment.corrections_applied)
    missing = set(ABSOLUTE_CORRECTIONS) - corrections
    if missing:
        raise ValueError(
            f"{profile_name}: absolute buffer ledger is missing: "
            + ", ".join(sorted(missing))
        )
    if "buffer" in corrections:
        raise ValueError(f"{profile_name}: buffer profile is already buffer-subtracted")
    return assessment
