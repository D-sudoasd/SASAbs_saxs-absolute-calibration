from dataclasses import replace
import json
import math

import pytest

import saxsabs.core as core
from saxsabs.core.material_attenuation import (
    FIXED_THICKNESS_DERIVATION_SCHEMA,
    MATERIAL_ATTENUATION_SCHEMA,
    NIST_30_KEV_TABLE,
    NOMINAL_MATERIALS,
    PARTIAL_UNCERTAINTY_STATUS,
    WT_FRACTION_BASIS,
    calculate_material_attenuation,
    calculate_nominal_material_attenuation,
    derive_fixed_thickness,
    identify_nominal_material,
    parse_weight_composition_string,
    robust_transmission_statistics,
    verify_provenance_fingerprint,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ti:0.90, Al:0.06, V:0.04", {"Ti": 0.90, "Al": 0.06, "V": 0.04}),
        ("Ti:90, Al:6, V:4", {"Ti": 0.90, "Al": 0.06, "V": 0.04}),
    ],
)
def test_parse_weight_composition_string_is_scale_explicit(text, expected):
    assert parse_weight_composition_string(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    ["", "Ti:90, Al:6", "Ti:0.9, Al:0.06", "Ti:50, Ti:50", "Ti=90, Al=10"],
)
def test_parse_weight_composition_string_fails_closed(text):
    with pytest.raises(ValueError):
        parse_weight_composition_string(text)


def test_nominal_material_identity_is_attached_only_to_matching_composition():
    exact = parse_weight_composition_string("Ti:90, Al:6, V:4")
    assert identify_nominal_material(exact).key == "ti6al4v"

    edited = parse_weight_composition_string("Ti:89, Al:7, V:4")
    assert identify_nominal_material(edited) is None


def test_material_attenuation_api_is_exported_from_core_namespace():
    assert core.NIST_30_KEV_TABLE is NIST_30_KEV_TABLE
    assert core.calculate_material_attenuation is calculate_material_attenuation
    assert core.derive_fixed_thickness is derive_fixed_thickness


@pytest.mark.parametrize(
    ("material_key", "expected_mu", "expected_mu_rho", "expected_density"),
    (
        ("ti2448", 74.550355, 13.87128, 5.374439517341046),
        ("ti6al4v", 20.989980, 4.76504, 4.404995535676305),
        ("zr2p5nb", 162.949617, 24.89525, 6.545409936138242),
    ),
)
def test_three_nominal_materials_lock_nist_30kev_golden_values(
    material_key,
    expected_mu,
    expected_mu_rho,
    expected_density,
):
    result = calculate_nominal_material_attenuation(material_key)

    assert round(result.linear_attenuation_cm_inv, 6) == expected_mu
    assert result.regression_golden_mu_cm_inv == expected_mu
    assert result.mixture_mass_attenuation_cm2_g == pytest.approx(expected_mu_rho)
    assert result.ideal_mixture_density_g_cm3 == pytest.approx(expected_density)
    assert result.composition_basis == WT_FRACTION_BASIS
    assert result.uncertainty_status == PARTIAL_UNCERTAINTY_STATUS
    assert result.parameter_source == "composition_model_derived"


def test_nist_snapshot_records_identity_energy_sources_and_element_rows():
    payload = NIST_30_KEV_TABLE.to_dict()

    assert payload["identity"] == (
        "NIST_PML_XRAY_MASS_ATTENUATION_COEFFICIENTS_TABLES_1_AND_3"
    )
    assert payload["snapshot_id"] == "saxsabs.nist_xraymasscoef.30kev.20260713.v1"
    assert payload["energy_kev"] == 30.0
    assert payload["composition_basis"] == "wt_fraction"
    assert payload["mass_attenuation_source"]["url"].endswith("/tab3.html")
    assert payload["density_source"]["url"].endswith("/tab1.html")
    assert payload["elements"]["Ti"] == {
        "mass_attenuation_cm2_g": 4.972,
        "density_g_cm3": 4.54,
    }
    assert payload["elements"]["Sn"]["mass_attenuation_cm2_g"] == 41.21
    verify_provenance_fingerprint(payload)


def test_material_payload_exposes_each_element_input_and_full_precision():
    result = calculate_nominal_material_attenuation("ti2448")
    payload = result.to_dict()

    assert payload["schema"] == MATERIAL_ATTENUATION_SCHEMA
    assert payload["composition_wt_fraction"] == {
        "Nb": 0.24,
        "Sn": 0.08,
        "Ti": 0.64,
        "Zr": 0.04,
    }
    assert payload["element_inputs"]["Nb"] == {
        "wt_fraction": 0.24,
        "mass_attenuation_cm2_g": 26.66,
        "density_g_cm3": 8.57,
        "mass_attenuation_contribution_cm2_g": 0.24 * 26.66,
    }
    text = result.to_json()
    assert "74.55035538810252" in text
    assert json.loads(text)["linear_attenuation_cm_inv"] == (
        result.linear_attenuation_cm_inv
    )
    verify_provenance_fingerprint(payload)


@pytest.mark.parametrize("basis", ["wt_percent", "at_fraction", "", "WT_FRACTION"])
def test_composition_basis_is_explicit_and_never_guessed(basis):
    with pytest.raises(ValueError, match="composition_basis"):
        calculate_material_attenuation(
            {"Ti": 1.0},
            composition_basis=basis,
        )


@pytest.mark.parametrize(
    ("composition", "message"),
    (
        ({}, "non-empty"),
        ({"Ti": 0.99}, "sum to 1"),
        ({"Ti": 1.0000001}, "sum to 1"),
        ({"Ti": 1.1, "Al": -0.1}, "negative"),
        ({"Ti": math.nan}, "finite"),
        ({"Ti": math.inf}, "finite"),
        ({"Ti": True}, "not bool"),
        ({"Fe": 1.0}, "unknown element"),
        ({"ti": 1.0}, "invalid element symbol"),
    ),
)
def test_material_calculation_fails_closed_for_invalid_composition(composition, message):
    with pytest.raises(ValueError, match=message):
        calculate_material_attenuation(
            composition,
            composition_basis="wt_fraction",
        )


def test_material_fingerprint_is_order_independent_and_value_sensitive():
    first = calculate_material_attenuation(
        {"Ti": 0.9, "Al": 0.06, "V": 0.04},
        composition_basis="wt_fraction",
    )
    reordered = calculate_material_attenuation(
        {"V": 0.04, "Ti": 0.9, "Al": 0.06},
        composition_basis="wt_fraction",
    )
    changed = calculate_material_attenuation(
        {"Ti": 0.9, "Al": 0.05, "V": 0.05},
        composition_basis="wt_fraction",
    )

    assert first.fingerprint() == reordered.fingerprint()
    assert first.fingerprint() != changed.fingerprint()


def test_material_result_container_rejects_internally_inconsistent_values():
    result = calculate_nominal_material_attenuation("ti2448")

    with pytest.raises(ValueError, match="linear attenuation"):
        replace(result, linear_attenuation_cm_inv=result.linear_attenuation_cm_inv * 1.01)
    with pytest.raises(ValueError, match="contribution mismatch"):
        replace(
            result,
            element_contributions_cm2_g=(
                *result.element_contributions_cm2_g[:-1],
                (
                    result.element_contributions_cm2_g[-1][0],
                    result.element_contributions_cm2_g[-1][1] * 1.01,
                ),
            ),
        )


def test_robust_transmission_statistics_match_median_mad_and_linear_percentiles():
    stats = robust_transmission_statistics(
        [0.2, 0.4, 0.6, 0.8, 1.0],
        anchor_scope="numeric_ok_use_and_review",
    )

    assert stats.count == 5
    assert stats.median == pytest.approx(0.6)
    assert stats.mad == pytest.approx(0.2)
    assert stats.p5 == pytest.approx(0.24)
    assert stats.p95 == pytest.approx(0.96)
    assert stats.minimum == 0.2
    assert stats.maximum == 1.0
    assert stats.relative_p5_p95_span == pytest.approx(1.2)
    assert stats.to_dict()["percentile_method"] == "linear"
    assert stats.warnings == ("transmission_p5_p95_relative_span_exceeds_threshold",)


@pytest.mark.parametrize(
    "transmissions",
    (
        [],
        [0.0],
        [-0.1],
        [1.0000001],
        [math.nan],
        [math.inf],
        [True],
        "0.5",
    ),
)
def test_transmission_statistics_fail_closed_for_invalid_values(transmissions):
    with pytest.raises(ValueError):
        robust_transmission_statistics(transmissions)


@pytest.mark.parametrize("threshold", [-0.1, math.nan, math.inf, True])
def test_transmission_statistics_reject_invalid_drift_threshold(threshold):
    with pytest.raises(ValueError):
        robust_transmission_statistics([0.5], drift_warning_relative_span=threshold)


def test_fixed_thickness_uses_robust_median_and_keeps_partial_uncertainty():
    material = calculate_nominal_material_attenuation("ti6al4v")
    derivation = derive_fixed_thickness(
        material,
        [0.49, 0.50, 0.51, 0.99],
        anchor_scope="use_review_numeric_ok",
    )

    expected_median = 0.505
    expected_thickness = -math.log(expected_median) / material.linear_attenuation_cm_inv
    assert derivation.representative_transmission == pytest.approx(expected_median)
    assert derivation.fixed_thickness_cm == pytest.approx(expected_thickness)
    assert derivation.uncertainty_status == "partial"
    assert "ideal_mixture_density_is_not_measured_bulk_density" in derivation.warnings
    assert derivation.to_dict()["mu_cm_inv_used"] == material.linear_attenuation_cm_inv


def test_porosity_risk_is_explicit_in_material_and_fixed_thickness_provenance():
    material = calculate_nominal_material_attenuation("ti2448", porosity_risk=True)
    derivation = derive_fixed_thickness(material, [0.52, 0.53])
    payload = derivation.to_dict()

    assert material.porosity_warning is not None
    assert payload["porosity_warning"] == material.porosity_warning
    assert material.porosity_warning in payload["warnings"]
    assert payload["material_attenuation"]["uncertainty_status"] == "partial"


def test_fixed_thickness_json_has_nested_and_top_level_valid_fingerprints():
    derivation = derive_fixed_thickness(
        calculate_nominal_material_attenuation("zr2p5nb"),
        [0.077, 0.078, 0.079],
    )
    payload = json.loads(derivation.to_json())

    assert payload["schema"] == FIXED_THICKNESS_DERIVATION_SCHEMA
    verify_provenance_fingerprint(payload)
    verify_provenance_fingerprint(payload["material_attenuation"])
    verify_provenance_fingerprint(payload["material_attenuation"]["attenuation_table"])

    payload["fixed_thickness_cm"] *= 1.01
    with pytest.raises(ValueError, match="integrity"):
        verify_provenance_fingerprint(payload)


def test_fixed_thickness_fingerprint_changes_with_transmission():
    material = calculate_nominal_material_attenuation("ti2448")
    first = derive_fixed_thickness(material, [0.5, 0.6])
    second = derive_fixed_thickness(material, [0.5, 0.7])

    assert first.fingerprint() != second.fingerprint()


def test_unity_transmission_is_in_range_and_records_zero_effective_thickness_warning():
    derivation = derive_fixed_thickness(
        calculate_nominal_material_attenuation("ti6al4v"),
        [1.0],
    )

    assert derivation.fixed_thickness_cm == 0.0
    assert "representative_transmission_is_one_zero_effective_thickness" in (
        derivation.warnings
    )


def test_nominal_material_lookup_rejects_unknown_key():
    assert set(NOMINAL_MATERIALS) == {"ti2448", "ti6al4v", "zr2p5nb"}
    with pytest.raises(ValueError, match="unknown nominal material"):
        calculate_nominal_material_attenuation("unknown")
