"""Tests for the universal μ calculator (xraydb-backed)."""

import numpy as np
import pytest

from saxsabs.core.mu_calculator import (
    MATERIAL_PRESETS,
    XRAYDB_VERSION,
    MuResult,
    calculate_mu,
    mu_rho_single,
    parse_composition_string,
)


def test_xraydb_version_is_exposed_for_diagnostic_provenance():
    import xraydb

    assert XRAYDB_VERSION == str(xraydb.__version__)


# ---------------------------------------------------------------------------
# parse_composition_string
# ---------------------------------------------------------------------------
class TestParseCompositionString:
    def test_weight_fraction_format(self):
        comp = parse_composition_string("Fe:0.69, Cr:0.19, Ni:0.12")
        assert set(comp.keys()) == {"Fe", "Cr", "Ni"}
        assert np.isclose(comp["Fe"], 0.69)
        assert np.isclose(comp["Cr"], 0.19)
        assert np.isclose(comp["Ni"], 0.12)

    def test_percent_format_auto_normalised(self):
        comp = parse_composition_string("Fe:69, Cr:19, Ni:12")
        total = sum(comp.values())
        assert np.isclose(total, 1.0, atol=0.02)
        assert np.isclose(comp["Fe"], 0.69, atol=0.01)

    def test_mixed_percent_format_auto_normalised(self):
        comp = parse_composition_string("Fe:99, C:1")
        assert np.isclose(sum(comp.values()), 1.0)
        assert np.isclose(comp["Fe"], 0.99)
        assert np.isclose(comp["C"], 0.01)

    @pytest.mark.parametrize(
        ("text", "expected_fe"),
        [
            ("Fe:0.80, Cr:0.18", 0.80 / 0.98),
            ("Fe:80, Cr:18", 80.0 / 98.0),
            ("Fe:82, Cr:20", 82.0 / 102.0),
        ],
    )
    def test_accepted_fraction_and_percent_boundaries_are_normalized(self, text, expected_fe):
        comp = parse_composition_string(text)
        assert sum(comp.values()) == 1.0
        assert comp["Fe"] == pytest.approx(expected_fe)

    @pytest.mark.parametrize("text", ["Fe:95", "Fe:0.8", "Fe:1.2", "Fe:94, Cr:1"])
    def test_rejects_incomplete_or_ambiguous_scale(self, text):
        with pytest.raises(ValueError, match="sum to approximately"):
            parse_composition_string(text)

    def test_scientific_notation_format(self):
        comp = parse_composition_string("Fe:6.9e-1, Cr:1.9e-1, Ni:1.2e-1")
        assert np.isclose(comp["Fe"], 0.69)
        assert np.isclose(comp["Cr"], 0.19)
        assert np.isclose(comp["Ni"], 0.12)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_composition_string("")

    def test_bad_format_raises(self):
        with pytest.raises(ValueError):
            parse_composition_string("Fe-0.5-Cr-0.5")

    @pytest.mark.parametrize("text", ["Fe:0.5 garbage", "Fe:0.5, XX"])
    def test_unmatched_garbage_raises(self, text):
        with pytest.raises(ValueError):
            parse_composition_string(text)

    def test_duplicate_element_raises(self):
        with pytest.raises(ValueError, match="Duplicate element"):
            parse_composition_string("Fe:50, Fe:50")


# ---------------------------------------------------------------------------
# mu_rho_single
# ---------------------------------------------------------------------------
class TestMuRhoSingle:
    def test_fe_at_8kev(self):
        """Fe mass attenuation at 8 keV should be roughly 300-400 cm²/g."""
        val = mu_rho_single("Fe", 8.0)
        assert 200 < val < 500

    def test_cu_positive(self):
        val = mu_rho_single("Cu", 30.0)
        assert val > 0

    def test_unknown_element_raises(self):
        with pytest.raises(Exception):
            mu_rho_single("Xx", 10.0)

    @pytest.mark.parametrize("bad_energy", [0.0, -1.0, float("nan"), float("inf")])
    def test_non_positive_or_non_finite_energy_raises(self, bad_energy):
        with pytest.raises(ValueError, match="(?i)energy"):
            mu_rho_single("Fe", bad_energy)


# ---------------------------------------------------------------------------
# calculate_mu
# ---------------------------------------------------------------------------
class TestCalculateMu:
    def test_pure_fe_30kev(self):
        """Pure Fe at 30 keV: μ/ρ from xraydb ≈ 8.18 cm²/g, ρ=7.874."""
        result = calculate_mu({"Fe": 1.0}, density_g_cm3=7.874, energy_keV=30.0)
        assert isinstance(result, MuResult)
        # μ/ρ should be ~8 cm²/g  (NOT the old XCOM_30KEV value of 2.26)
        assert 6.0 < result.mu_rho_cm2_g < 12.0
        # μ_linear = ρ * μ/ρ ≈ 7.874 * 8.18 ≈ 64
        assert result.mu_linear_cm_inv > 30

    def test_water_8kev(self):
        """Water (H₂O) at 8 keV."""
        result = calculate_mu(
            {"H": 0.1119, "O": 0.8881},
            density_g_cm3=1.0,
            energy_keV=8.0,
        )
        assert result.mu_rho_cm2_g > 0
        assert result.mu_linear_cm_inv > 0
        assert len(result.element_contributions) == 2

    def test_preset_ti6al4v(self):
        _name, composition, density = MATERIAL_PRESETS["Ti-6Al-4V"]
        result = calculate_mu(
            composition,
            density_g_cm3=density,
            energy_keV=30.0,
        )
        assert result.mu_rho_cm2_g > 0
        assert np.isclose(result.density_g_cm3, 4.43)

    def test_direct_percent_composition_is_converted(self):
        percent = calculate_mu(
            {"Fe": 69, "Cr": 19, "Ni": 12},
            density_g_cm3=7.874,
            energy_keV=30.0,
        )
        fraction = calculate_mu(
            {"Fe": 0.69, "Cr": 0.19, "Ni": 0.12},
            density_g_cm3=7.874,
            energy_keV=30.0,
        )
        assert percent.composition == fraction.composition
        assert percent.mu_rho_cm2_g == pytest.approx(fraction.mu_rho_cm2_g)

    def test_direct_incomplete_percent_composition_raises(self):
        with pytest.raises(ValueError, match="sum to approximately"):
            calculate_mu({"Fe": 95}, density_g_cm3=7.874, energy_keV=30.0)

    def test_tolerated_fraction_and_percent_totals_do_not_scale_mu(self):
        fraction = calculate_mu(
            {"Fe": 0.80, "Cr": 0.18},
            density_g_cm3=7.874,
            energy_keV=30.0,
        )
        percent = calculate_mu(
            {"Fe": 80.0, "Cr": 18.0},
            density_g_cm3=7.874,
            energy_keV=30.0,
        )
        canonical = calculate_mu(
            {"Fe": 0.80 / 0.98, "Cr": 0.18 / 0.98},
            density_g_cm3=7.874,
            energy_keV=30.0,
        )

        assert sum(fraction.composition.values()) == 1.0
        assert sum(percent.composition.values()) == 1.0
        assert fraction.mu_linear_cm_inv == pytest.approx(canonical.mu_linear_cm_inv)
        assert percent.mu_linear_cm_inv == pytest.approx(canonical.mu_linear_cm_inv)

    def test_negative_energy_raises(self):
        with pytest.raises(ValueError, match="(?i)energy"):
            calculate_mu({"Fe": 1.0}, density_g_cm3=7.874, energy_keV=-1.0)

    def test_zero_density_raises(self):
        with pytest.raises(ValueError, match="(?i)density"):
            calculate_mu({"Fe": 1.0}, density_g_cm3=0.0, energy_keV=30.0)

    def test_negative_weight_fraction_raises(self):
        with pytest.raises(ValueError, match="negative"):
            calculate_mu({"Fe": 1.1, "Cr": -0.1}, density_g_cm3=7.874, energy_keV=30.0)

    @pytest.mark.parametrize("bad_fraction", [float("nan"), float("inf")])
    def test_non_finite_weight_fraction_raises(self, bad_fraction):
        with pytest.raises(ValueError, match="finite"):
            calculate_mu({"Fe": bad_fraction}, density_g_cm3=7.874, energy_keV=30.0)

    def test_weight_sum_deviation_raises_instead_of_calculating(self):
        with pytest.raises(ValueError, match="sum to approximately"):
            calculate_mu({"Fe": 0.8}, density_g_cm3=7.874, energy_keV=30.0)
