from __future__ import annotations

import pytest

from saxsabs.core.intensity_state import (
    IntensityState,
    assess_intensity_state,
    parse_correction_ledger,
    require_absolute_input_for_buffer_subtraction,
    require_relative_input_for_absolute_scaling,
    serialize_correction_ledger,
)


def test_absolute_column_is_rejected_before_k_or_thickness_is_reapplied():
    profile = {"i_col": "I_abs_cm^-1", "operator_provenance": {}}

    assessment = assess_intensity_state(profile)

    assert assessment.state is IntensityState.ABSOLUTE_CM_INV
    with pytest.raises(ValueError, match="already absolute intensity"):
        require_relative_input_for_absolute_scaling(profile, profile_name="sample.dat")


def test_absolute_unit_is_detected_even_with_generic_i_column():
    assessment = assess_intensity_state({"i_col": "I", "intensity_unit": "1/cm"})

    assert assessment.state is IntensityState.ABSOLUTE_CM_INV


def test_invalid_explicit_state_is_ambiguous_even_with_absolute_unit_evidence():
    assessment = assess_intensity_state(
        {
            "i_col": "I",
            "intensity_unit": "1/cm",
            "operator_provenance": {"intensity_state": "not-a-state"},
        }
    )

    assert assessment.state is IntensityState.AMBIGUOUS
    assert "invalid_metadata:intensity_state" in assessment.evidence

def test_relative_provenance_allows_absolute_scaling():
    profile = {
        "i_col": "I",
        "operator_provenance": {
            "intensity_state": "relative",
            "corrections_applied": '["dark","monitor","transmission"]',
        },
    }

    assessment = require_relative_input_for_absolute_scaling(profile)

    assert assessment.state is IntensityState.RELATIVE
    assert assessment.corrections_applied == ("dark", "monitor", "transmission")


def test_raw_counts_are_not_eligible_for_k_or_k_over_d_scaling():
    profile = {
        "i_col": "raw_intensity",
        "intensity_unit": "counts",
        "operator_provenance": {
            "intensity_state": "raw",
            "corrections_applied": "[]",
        },
    }

    assessment = assess_intensity_state(profile)

    assert assessment.state is IntensityState.RAW_COUNTS
    with pytest.raises(ValueError, match="raw counts, not a reduced relative profile"):
        require_relative_input_for_absolute_scaling(profile)


def test_generic_intensity_without_state_is_fail_closed():
    with pytest.raises(ValueError, match="intensity state is ambiguous"):
        require_relative_input_for_absolute_scaling({"i_col": "I"})


def test_conflicting_relative_metadata_and_absolute_column_is_ambiguous():
    assessment = assess_intensity_state(
        {
            "i_col": "I_abs_cm^-1",
            "operator_provenance": {"intensity_state": "relative"},
        }
    )

    assert assessment.state is IntensityState.AMBIGUOUS


def test_correction_ledger_roundtrip_is_stable_and_rejects_unknown_entries():
    encoded = serialize_correction_ledger(["T", "MON", "dark", "dark"])

    assert encoded == '["dark","monitor","transmission"]'
    assert parse_correction_ledger(encoded) == ("dark", "monitor", "transmission")
    with pytest.raises(ValueError, match="unknown correction"):
        parse_correction_ledger("dark,magic")


def test_do_not_repeat_only_is_enforced_and_conflicts_are_ambiguous():
    profile = {
        "i_col": "I_rel",
        "operator_provenance": {
            "intensity_state": "relative",
            "do_not_repeat": '["k","thickness"]',
        },
    }
    with pytest.raises(ValueError, match="requested correction"):
        require_relative_input_for_absolute_scaling(profile)

    conflicting = {
        "i_col": "I_rel",
        "operator_provenance": {
            "intensity_state": "relative",
            "corrections_applied": '["thickness"]',
            "do_not_repeat": '["monitor"]',
        },
    }
    assert assess_intensity_state(conflicting).state is IntensityState.AMBIGUOUS


def test_k_only_requires_existing_thickness_but_does_not_reapply_it():
    valid = {
        "i_col": "I_rel",
        "operator_provenance": {
            "intensity_state": "relative",
            "corrections_applied": '["monitor","transmission","thickness"]',
        },
    }
    assessment = require_relative_input_for_absolute_scaling(
        valid,
        corrections_to_apply=["k"],
        required_existing_corrections=["thickness"],
    )
    assert assessment.corrections_applied == ("monitor", "thickness", "transmission")

    without_thickness = {
        "i_col": "I_rel",
        "operator_provenance": {"intensity_state": "relative"},
    }
    with pytest.raises(ValueError, match="missing required existing.*thickness"):
        require_relative_input_for_absolute_scaling(
            without_thickness,
            corrections_to_apply=["k"],
            required_existing_corrections=["thickness"],
        )

    guard_only = {
        "i_col": "I_rel",
        "operator_provenance": {
            "intensity_state": "relative",
            "do_not_repeat": '["thickness"]',
        },
    }
    with pytest.raises(ValueError, match="missing required existing.*thickness"):
        require_relative_input_for_absolute_scaling(
            guard_only,
            corrections_to_apply=["k"],
            required_existing_corrections=["thickness"],
        )


def test_absolute_buffer_requires_unit_complete_ledger_and_no_prior_buffer():
    valid = {
        "i_col": "I_abs_cm^-1",
        "intensity_unit": "1/cm",
        "operator_provenance": {
            "intensity_state": "absolute_cm^-1",
            "corrections_applied": '["k","thickness"]',
        },
    }
    assert require_absolute_input_for_buffer_subtraction(valid).is_absolute

    relative = {
        "i_col": "I_rel",
        "operator_provenance": {"intensity_state": "relative"},
    }
    with pytest.raises(ValueError, match="must be explicit absolute"):
        require_absolute_input_for_buffer_subtraction(relative)

    missing_unit = {**valid, "intensity_unit": ""}
    with pytest.raises(ValueError, match="intensity_unit"):
        require_absolute_input_for_buffer_subtraction(missing_unit)

    repeated = {
        **valid,
        "operator_provenance": {
            "intensity_state": "absolute_cm^-1",
            "corrections_applied": '["buffer","k","thickness"]',
        },
    }
    with pytest.raises(ValueError, match="already buffer-subtracted"):
        require_absolute_input_for_buffer_subtraction(repeated)

    guard_only = {
        "i_col": "I_abs_cm^-1",
        "intensity_unit": "1/cm",
        "operator_provenance": {
            "intensity_state": "absolute_cm^-1",
            "do_not_repeat": '["k","thickness"]',
        },
    }
    with pytest.raises(ValueError, match="absolute buffer ledger is missing"):
        require_absolute_input_for_buffer_subtraction(guard_only)
