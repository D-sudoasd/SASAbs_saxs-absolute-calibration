import numpy as np
import pytest

from saxsabs.core.calibration import estimate_k_factor_robust
from saxsabs.constants import (
    STANDARD_REGISTRY,
    get_reference_data,
    water_dsdw,
)


def test_estimate_k_factor_robust_basic():
    q = np.array([0.01, 0.02, 0.05, 0.10, 0.15, 0.20], dtype=float)
    i_ref = np.array([34.2, 30.8, 26.8, 23.6, 15.8, 8.4], dtype=float)
    true_k = 2.5
    i_meas = i_ref / true_k

    out = estimate_k_factor_robust(q_meas=q, i_meas_per_cm=i_meas, q_ref=q, i_ref=i_ref)
    assert np.isclose(out.k_factor, true_k, rtol=1e-6)
    assert out.points_used >= 3


def test_estimate_k_factor_robust_with_outlier_still_stable():
    q = np.array([0.01, 0.02, 0.05, 0.10, 0.15, 0.20], dtype=float)
    i_ref = np.array([34.2, 30.8, 26.8, 23.6, 15.8, 8.4], dtype=float)
    true_k = 2.0
    i_meas = i_ref / true_k
    i_meas[2] = i_meas[2] * 0.1

    out = estimate_k_factor_robust(q_meas=q, i_meas_per_cm=i_meas, q_ref=q, i_ref=i_ref)
    assert np.isclose(out.k_factor, true_k, rtol=0.1)


def test_estimate_k_factor_overlap_insufficient_raises():
    q = np.array([0.30, 0.31, 0.32], dtype=float)
    i = np.array([1.0, 2.0, 3.0], dtype=float)
    with pytest.raises(ValueError, match="overlap"):
        estimate_k_factor_robust(q_meas=q, i_meas_per_cm=i)


def test_estimate_k_factor_non_positive_signal_raises():
    q = np.array([0.01, 0.02, 0.05, 0.10], dtype=float)
    i = np.array([-1.0, -2.0, -1.0, -3.0], dtype=float)
    with pytest.raises(ValueError, match="signal"):
        estimate_k_factor_robust(q_meas=q, i_meas_per_cm=i)


# ---------------------------------------------------------------------------
# Multi-standard support tests
# ---------------------------------------------------------------------------
class TestStandardRegistry:
    def test_srm3600_in_registry(self):
        assert "SRM3600" in STANDARD_REGISTRY
        ref = STANDARD_REGISTRY["SRM3600"]
        assert ref.standard_type == "primary"
        assert ref.q_data is not None
        assert len(ref.q_data) == 15

    def test_water_in_registry(self):
        assert "Water_20C" in STANDARD_REGISTRY
        ref = STANDARD_REGISTRY["Water_20C"]
        assert ref.is_q_independent is True
        assert np.isclose(ref.flat_value_cm_inv, 0.01632, rtol=1e-3)


class TestWaterDsdw:
    def test_20c(self):
        val = water_dsdw(20.0)
        assert np.isclose(val, 0.01632, rtol=0.01)

    def test_25c(self):
        val = water_dsdw(25.0)
        assert 0.0163 < val < 0.0170

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            water_dsdw(-10.0)


class TestGetReferenceData:
    def test_srm3600(self):
        q_ref, i_ref = get_reference_data("SRM3600")
        assert len(q_ref) == 15
        assert np.all(q_ref > 0)
        assert np.all(i_ref > 0)

    def test_water_flat(self):
        q_ref, i_ref = get_reference_data("Water_20C", q_range=(0.01, 0.30), n_points=50)
        assert len(q_ref) == 50
        assert np.allclose(i_ref, water_dsdw(20.0), rtol=0.01)

    def test_water_custom_temperature(self):
        q15, i15 = get_reference_data("Water_20C", temperature_C=15.0, q_range=(0.01, 0.20), n_points=20)
        q25, i25 = get_reference_data("Water_20C", temperature_C=25.0, q_range=(0.01, 0.20), n_points=20)
        # 25°C water scatters slightly more than 15°C
        assert i25[0] > i15[0]

    def test_custom_user_data(self):
        q_user = np.linspace(0.01, 0.2, 10)
        i_user = np.ones(10) * 42.0
        q_ref, i_ref = get_reference_data("Custom", q_user=q_user, i_user=i_user)
        np.testing.assert_array_equal(q_ref, q_user)
        np.testing.assert_array_equal(i_ref, i_user)
