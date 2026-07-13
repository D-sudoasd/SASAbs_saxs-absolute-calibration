from pathlib import Path

import pytest

from saxsabs.core.calibration_context import (
    CalibrationContext,
    builtin_reference_identity,
    canonical_reference_sha256,
    sha256_file,
)


def _context(**overrides):
    values = {
        "formula_version": "v3_nist_blank",
        "monitor_mode": "rate",
        "poni_sha256": "poni-sha",
        "mask_sha256": "mask-sha",
        "flat_sha256": None,
        "correct_solid_angle": True,
        "polarization_factor": None,
        "standard_key": "SRM3600",
        "standard_thickness_cm": 0.1055,
    }
    values.update(overrides)
    return CalibrationContext(**values)


def test_calibration_context_fingerprint_includes_standard_provenance():
    first = _context(standard_key="Custom", standard_thickness_cm=0.1055)
    second = _context(standard_key="Custom", standard_thickness_cm=0.1)
    assert first.fingerprint() != second.fingerprint()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("monitor_mode", "integrated"),
        ("poni_sha256", "other-poni"),
        ("mask_sha256", "other-mask"),
        ("flat_sha256", "flat-sha"),
        ("correct_solid_angle", False),
        ("polarization_factor", 0.95),
    ],
)
def test_calibration_context_blocks_operator_mismatch(field, value):
    calibrated = _context()
    current = _context(**{field: value})

    with pytest.raises(ValueError, match=field):
        calibrated.assert_operator_compatible(current)


def test_sha256_file_is_content_based(tmp_path: Path):
    path = tmp_path / "geometry.poni"
    path.write_text("poni-v1", encoding="utf-8")
    first = sha256_file(path)
    path.write_text("poni-v2", encoding="utf-8")
    assert sha256_file(path) != first



def test_calibration_context_v2_fingerprint_binds_complete_k_source_provenance():
    values = {
        "standard_data_sha256": "a" * 64,
        "background_data_sha256": ("b" * 64,),
        "dark_data_sha256": ("c" * 64,),
        "standard_monitor": 1000.0,
        "standard_transmission": 0.82,
        "standard_exposure_s": 10.0,
        "background_monitors": (900.0,),
        "background_transmissions": (0.91,),
        "background_exposure_s": (10.0,),
        "dark_exposure_s": (10.0,),
        "q_window": (0.01, 0.2),
    }
    identity = builtin_reference_identity("SRM3600")
    values.update(
        reference_model_id=identity.model_id,
        reference_model_version=identity.model_version,
        reference_canonical_sha256=identity.canonical_sha256,
        background_scale_alpha=1.0,
        background_composition_rule="arithmetic_mean_after_individual_normalization",
        integration_unit="q_A^-1",
        integration_method="pyFAI.integrate1d:csr",
        integration_engine_version="test-pyFAI",
        integration_npt=1000,
        robust_estimator="median_mad",
        robust_mad_multiplier=3.0,
        robust_positive_floor=1e-9,
        robust_min_points=3,
        robust_zero_mad_relative_tolerance=1e-12,
    )
    complete = _context(**values)
    changed_monitor = _context(**{**values, "standard_monitor": 1001.0})

    assert complete.provenance_missing_fields() == ()
    assert complete.fingerprint() != changed_monitor.fingerprint()
    assert CalibrationContext.from_dict(complete.to_dict()) == complete


def test_custom_and_water_contexts_identify_their_reference_source():
    common = {
        "standard_data_sha256": "a" * 64,
        "background_data_sha256": ("b" * 64,),
        "dark_data_sha256": ("c" * 64,),
        "standard_monitor": 1000.0,
        "standard_transmission": 0.82,
        "standard_exposure_s": 10.0,
        "background_monitors": (900.0,),
        "background_transmissions": (0.91,),
        "background_exposure_s": (10.0,),
        "dark_exposure_s": (10.0,),
        "q_window": (0.01, 0.2),
    }

    common.update(
        background_scale_alpha=1.0,
        background_composition_rule="arithmetic_mean_after_individual_normalization",
        integration_unit="q_A^-1",
        integration_method="pyFAI.integrate1d:csr",
        integration_engine_version="test-pyFAI",
        integration_npt=1000,
        robust_estimator="median_mad",
        robust_mad_multiplier=3.0,
        robust_positive_floor=1e-9,
        robust_min_points=3,
        robust_zero_mad_relative_tolerance=1e-12,
    )
    water_identity = builtin_reference_identity("Water_20C", water_temperature_C=20.0)
    custom = _context(
        standard_key="Custom",
        reference_model_id="CUSTOM_REFERENCE_FILE",
        reference_model_version="parsed-q-i-v1",
        reference_canonical_sha256="d" * 64,
        **common,
    )
    water = _context(
        standard_key="Water",
        reference_model_id=water_identity.model_id,
        reference_model_version=water_identity.model_version,
        reference_canonical_sha256=water_identity.canonical_sha256,
        **common,
    )

    assert custom.provenance_missing_fields() == ("reference_curve_sha256",)
    assert water.provenance_missing_fields() == ("water_temperature_C",)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("standard_monitor", 0.0, "standard_monitor"),
        ("standard_transmission", 1.1, "standard_transmission"),
        ("water_temperature_C", float("nan"), "water_temperature_C"),
        ("q_window", (0.2, 0.01), "q_window"),
        ("background_data_sha256", ("not-a-sha",), "background_data_sha256"),
    ],
)
def test_calibration_context_rejects_invalid_source_provenance(field, value, message):
    with pytest.raises(ValueError, match=message):
        _context(**{field: value})

@pytest.mark.parametrize(
    "alias",
    [
        "SRM3600",
        "srm3600",
        "nist_srm3600",
        "NIST SRM 3600",
        "nist-srm-3600",
    ],
)
def test_calibration_context_normalizes_srm3600_aliases(alias):
    context = _context(standard_key=alias, standard_thickness_cm=0.1055)

    assert context.standard_key == "SRM3600"


@pytest.mark.parametrize(
    "alias",
    ["SRM3600", "srm3600", "nist_srm3600", "nist srm 3600"],
)
def test_calibration_context_rejects_wrong_srm3600_alias_thickness(alias):
    with pytest.raises(ValueError, match="SRM 3600.*0.1055"):
        _context(standard_key=alias, standard_thickness_cm=0.1)


def test_calibration_context_from_dict_rejects_alias_with_wrong_srm3600_thickness():
    payload = _context().to_dict()
    payload["standard_key"] = "nist_srm3600"
    payload["standard_thickness_cm"] = 0.1

    with pytest.raises(ValueError, match="SRM 3600.*0.1055"):
        CalibrationContext.from_dict(payload)


def test_calibration_context_aliases_have_one_canonical_fingerprint():
    direct = _context(standard_key="SRM3600")
    alias = _context(standard_key="nist srm 3600")

    assert alias == direct
    assert alias.fingerprint() == direct.fingerprint()

def test_builtin_reference_identity_binds_actual_srm_and_temperature_dependent_water():
    srm = builtin_reference_identity("SRM3600")
    water_20 = builtin_reference_identity("Water_20C", water_temperature_C=20.0)
    water_25 = builtin_reference_identity("Water_20C", water_temperature_C=25.0)

    assert srm.model_id == "NIST_SRM3600_CERTIFICATE_TABLE_1"
    assert len(srm.canonical_sha256) == 64
    assert water_20.model_id == "WATER_IAPWS95_ORTHABER2000"
    assert water_20.canonical_sha256 != water_25.canonical_sha256


def test_canonical_reference_hash_binds_q_i_and_uncertainty_values():
    first = canonical_reference_sha256([0.01, 0.02], [10.0, 9.0], [0.1, 0.2])
    changed_i = canonical_reference_sha256([0.01, 0.02], [10.0, 8.9], [0.1, 0.2])
    changed_u = canonical_reference_sha256([0.01, 0.02], [10.0, 9.0], [0.1, 0.3])

    assert first != changed_i
    assert first != changed_u


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("reference_model_id", "ANOTHER_MODEL"),
        ("reference_model_version", "another-version"),
        ("reference_canonical_sha256", "f" * 64),
    ],
)
def test_builtin_reference_context_rejects_wrong_model_identity(field_name, bad_value):
    identity = builtin_reference_identity("SRM3600")
    values = {
        "reference_model_id": identity.model_id,
        "reference_model_version": identity.model_version,
        "reference_canonical_sha256": identity.canonical_sha256,
    }
    values[field_name] = bad_value

    with pytest.raises(ValueError, match=field_name):
        _context(**values)


def test_algorithm_inputs_are_required_before_provenance_can_be_complete():
    values = {
        "standard_data_sha256": "a" * 64,
        "background_data_sha256": ("b" * 64,),
        "dark_data_sha256": ("c" * 64,),
        "standard_monitor": 1000.0,
        "standard_transmission": 0.82,
        "standard_exposure_s": 10.0,
        "background_monitors": (900.0,),
        "background_transmissions": (0.91,),
        "background_exposure_s": (10.0,),
        "dark_exposure_s": (10.0,),
        "q_window": (0.01, 0.2),
    }

    missing = _context(**values).provenance_missing_fields()

    assert "reference_model_id" in missing
    assert "background_scale_alpha" in missing
    assert "integration_method" in missing
    assert "robust_estimator" in missing

def test_source_hashes_and_acquisition_metadata_must_be_one_to_one_and_ordered():
    with pytest.raises(ValueError, match="background_monitors"):
        _context(
            background_data_sha256=("a" * 64, "b" * 64),
            background_monitors=(100.0,),
        )
    with pytest.raises(ValueError, match="dark_exposure_s"):
        _context(
            dark_data_sha256=("a" * 64, "b" * 64),
            dark_exposure_s=(10.0,),
        )

def test_unresolved_auto_integration_method_downgrades_provenance():
    identity = builtin_reference_identity("SRM3600")
    values = {
        "standard_data_sha256": "a" * 64,
        "background_data_sha256": ("b" * 64,),
        "dark_data_sha256": ("c" * 64,),
        "standard_monitor": 1000.0,
        "standard_transmission": 0.82,
        "standard_exposure_s": 10.0,
        "background_monitors": (900.0,),
        "background_transmissions": (0.91,),
        "background_exposure_s": (10.0,),
        "dark_exposure_s": (10.0,),
        "q_window": (0.01, 0.2),
        "reference_model_id": identity.model_id,
        "reference_model_version": identity.model_version,
        "reference_canonical_sha256": identity.canonical_sha256,
        "background_scale_alpha": 1.0,
        "background_composition_rule": "mean",
        "integration_unit": "q_A^-1",
        "integration_method": "pyFAI.integrate1d:auto",
        "integration_engine_version": "2026.1",
        "integration_npt": 1000,
        "robust_estimator": "median_mad",
        "robust_mad_multiplier": 3.0,
        "robust_positive_floor": 1e-9,
        "robust_min_points": 3,
        "robust_zero_mad_relative_tolerance": 1e-12,
    }

    assert _context(**values).provenance_missing_fields() == (
        "integration_method_resolved",
    )
