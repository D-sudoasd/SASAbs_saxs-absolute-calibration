"""Tests for the universal μ calculator (xraydb-backed)."""

import numpy as np
import pytest

from saxsabs.core.mu_calculator import (
    MATERIAL_PRESETS,
    MuResult,
    calculate_mu,
    mu_rho_single,
    parse_composition_string,
)


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

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_composition_string("")

    def test_bad_format_raises(self):
        with pytest.raises(ValueError):
            parse_composition_string("Fe-0.5-Cr-0.5")


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

    def test_negative_energy_raises(self):
        with pytest.raises(ValueError, match="(?i)energy"):
            calculate_mu({"Fe": 1.0}, density_g_cm3=7.874, energy_keV=-1.0)

    def test_zero_density_raises(self):
        with pytest.raises(ValueError, match="(?i)density"):
            calculate_mu({"Fe": 1.0}, density_g_cm3=0.0, energy_keV=30.0)
