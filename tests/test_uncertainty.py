"""Tests for absolute-intensity uncertainty budgets."""

import numpy as np
import pytest

from saxsabs.core.uncertainty import (
    AbsoluteUncertaintyBudget,
    propagate_absolute_uncertainty,
)


def test_complete_budget_keeps_components_and_combines_independent_variances():
    budget = propagate_absolute_uncertainty(
        intensity=np.array([10.0, 20.0]),
        statistical_standard_uncertainty=np.array([1.0, 2.0]),
        k_relative_standard_uncertainty=0.10,
        standard_relative_standard_uncertainty=0.02,
        transmission_relative_standard_uncertainty=0.03,
        monitor_relative_standard_uncertainty=0.04,
        thickness_relative_standard_uncertainty=0.05,
        mu_relative_standard_uncertainty=0.06,
        alpha_standard_uncertainty=0.20,
        buffer_intensity=np.array([3.0, 4.0]),
        coverage_factor=2.0,
    )

    assert isinstance(budget, AbsoluteUncertaintyBudget)
    np.testing.assert_allclose(budget.statistical, [1.0, 2.0])
    np.testing.assert_allclose(budget.k, [1.0, 2.0])
    np.testing.assert_allclose(budget.standard, [0.2, 0.4])
    np.testing.assert_allclose(budget.transmission, [0.3, 0.6])
    np.testing.assert_allclose(budget.monitor, [0.4, 0.8])
    np.testing.assert_allclose(budget.thickness, [0.5, 1.0])
    np.testing.assert_allclose(budget.mu, [0.6, 1.2])
    np.testing.assert_allclose(budget.alpha, [0.6, 0.8])
    np.testing.assert_allclose(
        budget.combined_standard_uncertainty,
        [1.805547008526779, 3.49857113690718],
    )
    np.testing.assert_allclose(
        budget.expanded_uncertainty,
        [3.611094017053558, 6.99714227381436],
    )
    assert budget.coverage_factor == 2.0
    assert budget.unknown_components == ()


def test_missing_component_stays_unknown_and_prevents_optimistic_combination():
    budget = propagate_absolute_uncertainty(
        intensity=np.array([10.0, 20.0]),
        statistical_standard_uncertainty=np.array([1.0, 2.0]),
        k_relative_standard_uncertainty=0.1,
        standard_relative_standard_uncertainty=0.0,
        transmission_relative_standard_uncertainty=0.0,
        monitor_relative_standard_uncertainty=None,
        thickness_relative_standard_uncertainty=0.0,
        mu_relative_standard_uncertainty=0.0,
        alpha_standard_uncertainty=0.0,
    )

    assert np.all(np.isnan(budget.monitor))
    assert np.all(np.isnan(budget.combined_standard_uncertainty))
    assert np.all(np.isnan(budget.expanded_uncertainty))
    assert budget.unknown_components == ("monitor",)


def test_pointwise_unknown_uncertainty_only_invalidates_affected_bins():
    budget = propagate_absolute_uncertainty(
        intensity=np.array([10.0, 20.0]),
        statistical_standard_uncertainty=np.array([1.0, np.nan]),
        k_relative_standard_uncertainty=0.0,
        standard_relative_standard_uncertainty=0.0,
        transmission_relative_standard_uncertainty=0.0,
        monitor_relative_standard_uncertainty=0.0,
        thickness_relative_standard_uncertainty=0.0,
        mu_relative_standard_uncertainty=0.0,
        alpha_standard_uncertainty=0.0,
    )

    assert budget.combined_standard_uncertainty[0] == pytest.approx(1.0)
    assert np.isnan(budget.combined_standard_uncertainty[1])
    assert budget.unknown_components == ("statistical",)


def test_missing_coverage_factor_keeps_expanded_uncertainty_unknown():
    budget = propagate_absolute_uncertainty(
        intensity=np.array([10.0]),
        statistical_standard_uncertainty=np.array([1.0]),
        k_relative_standard_uncertainty=0.0,
        standard_relative_standard_uncertainty=0.0,
        transmission_relative_standard_uncertainty=0.0,
        monitor_relative_standard_uncertainty=0.0,
        thickness_relative_standard_uncertainty=0.0,
        mu_relative_standard_uncertainty=0.0,
        alpha_standard_uncertainty=0.0,
        coverage_factor=None,
    )

    np.testing.assert_allclose(budget.combined_standard_uncertainty, [1.0])
    assert np.all(np.isnan(budget.expanded_uncertainty))
    assert budget.coverage_factor is None


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("statistical_standard_uncertainty", -0.1),
        ("k_relative_standard_uncertainty", np.inf),
        ("transmission_relative_standard_uncertainty", np.inf),
        ("alpha_standard_uncertainty", -0.01),
    ],
)
def test_invalid_uncertainty_component_raises(keyword, value):
    kwargs = {
        "intensity": np.array([10.0]),
        "statistical_standard_uncertainty": 0.0,
        "k_relative_standard_uncertainty": 0.0,
        "standard_relative_standard_uncertainty": 0.0,
        "transmission_relative_standard_uncertainty": 0.0,
        "monitor_relative_standard_uncertainty": 0.0,
        "thickness_relative_standard_uncertainty": 0.0,
        "mu_relative_standard_uncertainty": 0.0,
        "alpha_standard_uncertainty": 0.0,
    }
    kwargs[keyword] = value

    with pytest.raises(ValueError, match=keyword):
        propagate_absolute_uncertainty(**kwargs)


def test_alpha_uncertainty_requires_matching_buffer_intensity():
    with pytest.raises(ValueError, match="buffer_intensity"):
        propagate_absolute_uncertainty(
            intensity=np.array([10.0, 20.0]),
            statistical_standard_uncertainty=0.0,
            k_relative_standard_uncertainty=0.0,
            standard_relative_standard_uncertainty=0.0,
            transmission_relative_standard_uncertainty=0.0,
            monitor_relative_standard_uncertainty=0.0,
            thickness_relative_standard_uncertainty=0.0,
            mu_relative_standard_uncertainty=0.0,
            alpha_standard_uncertainty=0.1,
            buffer_intensity=np.array([3.0, 4.0, 5.0]),
        )
