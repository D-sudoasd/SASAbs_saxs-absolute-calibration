import numpy as np
import pytest

from saxsabs.core.calibration import estimate_k_factor_robust


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
