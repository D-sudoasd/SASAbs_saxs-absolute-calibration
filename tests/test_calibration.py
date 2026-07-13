import hashlib

import numpy as np
import pytest

from saxsabs.core.calibration import estimate_k_factor_robust
from saxsabs.constants import (
    NIST_SRM3600_COVERAGE_FACTOR,
    NIST_SRM3600_DATA,
    NIST_SRM3600_UNCERTAINTY,
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


def test_default_nist_calibration_reports_certificate_aware_k_uncertainty():
    true_k = 2.5
    q = NIST_SRM3600_DATA[:, 0]
    i_meas = NIST_SRM3600_DATA[:, 1] / true_k

    out = estimate_k_factor_robust(
        q_meas=q,
        i_meas_per_cm=i_meas,
        q_window=(0.008, 0.25),
    )

    assert out.k_factor == pytest.approx(true_k)
    assert out.k_std == pytest.approx(0.0, abs=1e-12)
    assert out.k_statistical_standard_uncertainty == pytest.approx(0.0, abs=1e-12)
    assert out.k_standard_uncertainty == pytest.approx(true_k * 0.0258, rel=3e-4)
    assert out.k_expanded_uncertainty is None
    assert out.coverage_factor is None
    assert out.reference_coverage_factor == pytest.approx(NIST_SRM3600_COVERAGE_FACTOR)


def test_custom_reference_does_not_treat_unknown_systematic_uncertainty_as_zero():
    q = np.array([0.01, 0.02, 0.03, 0.04], dtype=float)
    i_ref = np.array([10.0, 8.0, 6.0, 4.0], dtype=float)
    out = estimate_k_factor_robust(q, i_ref / 2.0, q_ref=q, i_ref=i_ref)

    assert out.k_statistical_standard_uncertainty == pytest.approx(0.0, abs=1e-12)
    assert out.k_standard_uncertainty is None
    assert out.k_expanded_uncertainty is None
    assert out.coverage_factor is None


def test_k_statistical_uncertainty_matches_median_estimator_not_mean_estimator():
    q = np.array([0.01, 0.02, 0.03, 0.04], dtype=float)
    i_ref = np.full(4, 12.0)
    ratio = np.array([1.0, 2.0, 3.0, 4.0])

    out = estimate_k_factor_robust(q, i_ref / ratio, q_ref=q, i_ref=i_ref)

    # Normal-approximation SE(median) = 1.253314 * population_sigma / sqrt(n).
    assert out.k_statistical_standard_uncertainty == pytest.approx(0.700623902, rel=1e-7)


def test_custom_reference_uncertainty_and_coverage_are_propagated():
    q = np.array([0.01, 0.02, 0.03, 0.04], dtype=float)
    i_ref = np.array([10.0, 8.0, 6.0, 4.0], dtype=float)
    out = estimate_k_factor_robust(
        q,
        i_ref / 2.0,
        q_ref=q,
        i_ref=i_ref,
        i_ref_standard_uncertainty=i_ref * 0.03,
        coverage_factor=2.0,
    )

    assert out.k_standard_uncertainty == pytest.approx(0.06)
    assert out.k_expanded_uncertainty == pytest.approx(0.12)
    assert out.coverage_factor == pytest.approx(2.0)
    assert out.reference_coverage_factor is None


def test_estimate_k_factor_robust_with_outlier_still_stable():
    q = np.array([0.01, 0.02, 0.05, 0.10, 0.15, 0.20], dtype=float)
    i_ref = np.array([34.2, 30.8, 26.8, 23.6, 15.8, 8.4], dtype=float)
    true_k = 2.0
    i_meas = i_ref / true_k
    i_meas[2] = i_meas[2] * 0.1

    out = estimate_k_factor_robust(q_meas=q, i_meas_per_cm=i_meas, q_ref=q, i_ref=i_ref)
    assert np.isclose(out.k_factor, true_k, rtol=0.1)


def test_estimate_k_factor_zero_mad_still_rejects_nonmedian_outlier():
    q = np.array([0.01, 0.02, 0.05, 0.10, 0.15, 0.20], dtype=float)
    i_ref = np.array([34.2, 30.8, 26.8, 23.6, 15.8, 8.4], dtype=float)
    i_meas = i_ref / 2.0
    i_meas[2] /= 10.0

    out = estimate_k_factor_robust(q_meas=q, i_meas_per_cm=i_meas, q_ref=q, i_ref=i_ref)

    assert out.k_factor == pytest.approx(2.0)
    assert out.points_used == 5
    assert out.k_std == pytest.approx(0.0)


@pytest.mark.parametrize(
    "ratio",
    [
        np.array([1.0, 1.0, 100.0]),
        np.array([1.0, 2.0, 100.0]),
    ],
)
def test_estimate_k_factor_fails_when_outlier_rejection_leaves_too_few_points(ratio):
    q = np.array([0.01, 0.02, 0.03])
    i_ref = np.full(3, 12.0)

    with pytest.raises(ValueError, match="inlier"):
        estimate_k_factor_robust(q, i_ref / ratio, q_ref=q, i_ref=i_ref)


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


@pytest.mark.parametrize(
    ("q_ref", "i_ref"),
    [
        (np.array([0.01, 0.02, 0.03], dtype=float), None),
        (None, np.array([1.0, 2.0, 3.0], dtype=float)),
    ],
)
def test_estimate_k_factor_requires_complete_reference_pair(q_ref, i_ref):
    q = np.array([0.01, 0.02, 0.03], dtype=float)
    i = np.array([1.0, 2.0, 3.0], dtype=float)

    with pytest.raises(ValueError, match="q_ref.*i_ref|i_ref.*q_ref"):
        estimate_k_factor_robust(q_meas=q, i_meas_per_cm=i, q_ref=q_ref, i_ref=i_ref)


def test_estimate_k_factor_rejects_non_1d_measured_profiles():
    with pytest.raises(ValueError, match="1-D"):
        estimate_k_factor_robust(
            q_meas=np.array([[0.01, 0.02, 0.03]]),
            i_meas_per_cm=np.ones((1, 3)),
            q_ref=np.array([0.01, 0.02, 0.03]),
            i_ref=np.ones(3),
        )


@pytest.mark.parametrize(
    "i_ref",
    [
        np.array([1.0, 1.0, np.nan, 1.0]),
        np.array([1.0, 1.0, -1.0, 1.0]),
    ],
)
def test_estimate_k_factor_rejects_invalid_reference_intensity(i_ref):
    q = np.array([0.01, 0.02, 0.03, 0.04])
    with pytest.raises(ValueError, match="reference intensity"):
        estimate_k_factor_robust(q, np.ones(4), q_ref=q, i_ref=i_ref)


# ---------------------------------------------------------------------------
# Multi-standard support tests
# ---------------------------------------------------------------------------
class TestStandardRegistry:
    def test_srm3600_in_registry(self):
        assert "SRM3600" in STANDARD_REGISTRY
        ref = STANDARD_REGISTRY["SRM3600"]
        assert ref.standard_type == "primary"
        assert ref.q_data is not None
        assert len(ref.q_data) == 59

    def test_srm3600_certificate_table_and_uncertainty_are_preserved(self):
        assert NIST_SRM3600_DATA.shape == (59, 2)
        assert NIST_SRM3600_UNCERTAINTY.shape == (59, 2)
        np.testing.assert_allclose(
            NIST_SRM3600_DATA[[0, -1]],
            [[0.00827568, 34.933380], [0.24740200, 4.463604]],
            rtol=0,
            atol=5e-9,
        )
        np.testing.assert_allclose(
            NIST_SRM3600_UNCERTAINTY[[0, -1]],
            [[0.901092, 2.183336], [0.115137, 0.278975]],
            rtol=0,
            atol=5e-7,
        )
        assert NIST_SRM3600_COVERAGE_FACTOR == pytest.approx(2.4231)
        certificate_bytes = np.column_stack(
            (NIST_SRM3600_DATA, NIST_SRM3600_UNCERTAINTY)
        ).astype("<f8").tobytes()
        assert hashlib.sha256(certificate_bytes).hexdigest() == (
            "b128fbbd04c2a66fd9aa04c90a7f238f45092f6253d4960dc12b560e5b0ef471"
        )

        ref = STANDARD_REGISTRY["SRM3600"]
        np.testing.assert_array_equal(
            ref.standard_uncertainty_data, NIST_SRM3600_UNCERTAINTY[:, 0]
        )
        np.testing.assert_array_equal(
            ref.expanded_uncertainty_data, NIST_SRM3600_UNCERTAINTY[:, 1]
        )
        assert ref.coverage_factor == pytest.approx(2.4231)

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

    @pytest.mark.parametrize(
        ("temperature_c", "expected_cm_inv"),
        [
            (4.0, 0.016636024148),
            (15.0, 0.016335815876),
            (25.0, 0.016365023897),
            (40.0, 0.016805192483),
        ],
    )
    def test_iapws95_golden_values(self, temperature_c, expected_cm_inv):
        assert water_dsdw(temperature_c) == pytest.approx(expected_cm_inv, rel=2e-9)

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            water_dsdw(-10.0)

    @pytest.mark.parametrize("temperature_c", [np.nan, np.inf, -np.inf, "not-a-number"])
    def test_nonfinite_or_non_numeric_temperature_raises(self, temperature_c):
        with pytest.raises(ValueError, match="temperature"):
            water_dsdw(temperature_c)


class TestGetReferenceData:
    def test_srm3600(self):
        q_ref, i_ref = get_reference_data("SRM3600")
        assert len(q_ref) == 59
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

    def test_custom_user_data_shape_mismatch_raises(self):
        q_user = np.linspace(0.01, 0.2, 10)
        i_user = np.ones(9) * 42.0
        with pytest.raises(ValueError, match="same shape"):
            get_reference_data("Custom", q_user=q_user, i_user=i_user)

    def test_custom_user_data_non_finite_raises(self):
        q_user = np.array([0.01, 0.02, np.nan], dtype=float)
        i_user = np.array([1.0, 2.0, 3.0], dtype=float)
        with pytest.raises(ValueError, match="non-finite"):
            get_reference_data("Custom", q_user=q_user, i_user=i_user)

    def test_custom_user_data_too_short_raises(self):
        q_user = np.array([0.01, 0.02], dtype=float)
        i_user = np.array([1.0, 2.0], dtype=float)
        with pytest.raises(ValueError, match="at least 3 points"):
            get_reference_data("Custom", q_user=q_user, i_user=i_user)

    def test_water_invalid_q_range_raises(self):
        with pytest.raises(ValueError, match="q_range"):
            get_reference_data("Water_20C", q_range=(0.30, 0.01), n_points=50)

    def test_water_invalid_n_points_raises(self):
        with pytest.raises(ValueError, match="n_points"):
            get_reference_data("Water_20C", q_range=(0.01, 0.30), n_points=1)


def test_estimate_k_factor_preserves_legacy_positional_argument_order():
    q = np.array([0.01, 0.02, 0.03, 0.04], dtype=float)
    i_ref = np.array([10.0, 8.0, 6.0, 4.0], dtype=float)

    out = estimate_k_factor_robust(
        q,
        i_ref / 2.0,
        q,
        i_ref,
        (0.015, 0.04),
        1e-10,
        3,
    )

    assert out.k_factor == pytest.approx(2.0)
    assert out.q_min_overlap == pytest.approx(0.02)


def test_builtin_nist_records_certified_thickness_and_parallelism_qc():
    q = NIST_SRM3600_DATA[:, 0]
    out = estimate_k_factor_robust(q, NIST_SRM3600_DATA[:, 1] / 2.0)

    assert out.standard_thickness_cm == pytest.approx(0.1055)
    assert out.parallelism_max_relative_deviation == pytest.approx(0.0, abs=1e-12)
    assert out.parallelism_relative_tolerance == pytest.approx(0.0625, rel=3e-6)
    assert out.parallelism_check_passed is True


def test_builtin_nist_rejects_noncertified_standard_thickness():
    q = NIST_SRM3600_DATA[:, 0]

    with pytest.raises(ValueError, match="SRM 3600.*0.1055"):
        estimate_k_factor_robust(
            q,
            NIST_SRM3600_DATA[:, 1] / 2.0,
            standard_thickness_cm=0.1,
        )


def test_builtin_nist_parallelism_qc_fails_closed_with_observed_and_limit():
    q = NIST_SRM3600_DATA[:, 0]
    ratios = np.linspace(1.0, 1.2, q.size)

    with pytest.raises(
        ValueError,
        match=r"parallelism QC failed.*observed=.*tolerance=0\.0625",
    ):
        estimate_k_factor_robust(q, NIST_SRM3600_DATA[:, 1] / ratios)


def test_builtin_nist_parallelism_qc_accepts_explicit_stricter_tolerance():
    q = NIST_SRM3600_DATA[:, 0]
    ratios = np.linspace(1.0, 1.01, q.size)

    out = estimate_k_factor_robust(
        q,
        NIST_SRM3600_DATA[:, 1] / ratios,
        parallelism_relative_tolerance=0.01,
    )

    assert out.parallelism_max_relative_deviation <= 0.01
    assert out.parallelism_relative_tolerance == pytest.approx(0.01)
    assert out.parallelism_check_passed is True


def test_estimate_k_factor_rejects_duplicate_reference_q_values():
    q_ref = np.array([0.01, 0.02, 0.02, 0.03], dtype=float)

    with pytest.raises(ValueError, match="reference q.*unique"):
        estimate_k_factor_robust(
            np.array([0.01, 0.02, 0.03]),
            np.ones(3),
            q_ref=q_ref,
            i_ref=np.ones(4),
        )


def test_estimate_k_factor_rejects_nonfinite_derived_statistics():
    q = np.array([0.01, 0.02, 0.03, 0.04], dtype=float)
    i_ref = np.full(4, np.finfo(np.float64).max)
    i_meas = np.full(4, np.finfo(np.float64).tiny)

    with pytest.raises(ValueError, match="finite"):
        estimate_k_factor_robust(
            q,
            i_meas,
            q_ref=q,
            i_ref=i_ref,
            positive_floor=0.0,
        )

def test_builtin_nist_rejects_parallelism_tolerance_looser_than_certificate():
    q = NIST_SRM3600_DATA[:, 0]

    with pytest.raises(ValueError, match="cannot exceed.*certificate-derived"):
        estimate_k_factor_robust(
            q,
            NIST_SRM3600_DATA[:, 1],
            parallelism_relative_tolerance=0.1,
        )
