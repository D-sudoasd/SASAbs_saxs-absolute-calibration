"""Tests for buffer / solvent subtraction."""

import numpy as np
import pytest

from saxsabs.core.buffer_subtraction import (
    BufferSubtractionResult,
    subtract_buffer,
    validate_alpha,
)


class TestSubtractBuffer:
    def _make_data(self, n=100):
        q = np.linspace(0.01, 0.30, n)
        i_sample = 50.0 / q + 5.0  # signal + buffer
        i_buffer = np.full(n, 5.0)
        err_s = np.full(n, 0.1)
        err_b = np.full(n, 0.05)
        return q, i_sample, err_s, i_buffer, err_b

    def test_basic_subtraction(self):
        q, i_s, e_s, i_b, e_b = self._make_data()
        result = subtract_buffer(q, i_s, e_s, q, i_b, e_b, alpha=1.0)
        assert isinstance(result, BufferSubtractionResult)
        expected = i_s - i_b
        np.testing.assert_allclose(result.i_subtracted, expected, rtol=1e-10)

    def test_alpha_scaling(self):
        q, i_s, e_s, i_b, e_b = self._make_data()
        alpha = 0.9
        result = subtract_buffer(q, i_s, e_s, q, i_b, e_b, alpha=alpha)
        expected = i_s - alpha * i_b
        np.testing.assert_allclose(result.i_subtracted, expected, rtol=1e-10)

    def test_error_propagation(self):
        q, i_s, e_s, i_b, e_b = self._make_data()
        alpha = 1.0
        result = subtract_buffer(
            q,
            i_s,
            e_s,
            q,
            i_b,
            e_b,
            alpha=alpha,
            alpha_uncertainty=0.0,
        )
        expected_err = np.sqrt(e_s**2 + alpha**2 * e_b**2)
        np.testing.assert_allclose(result.err_statistical, expected_err, rtol=1e-10)
        np.testing.assert_allclose(result.err_subtracted, expected_err, rtol=1e-10)

    def test_missing_alpha_uncertainty_keeps_combined_uncertainty_unknown(self):
        q, i_s, e_s, i_b, e_b = self._make_data(n=5)

        result = subtract_buffer(q, i_s, e_s, q, i_b, e_b)

        assert result.alpha_uncertainty is None
        expected_statistical = np.sqrt(e_s**2 + e_b**2)
        np.testing.assert_allclose(result.err_statistical, expected_statistical)
        assert np.all(np.isnan(result.err_subtracted))

    @pytest.mark.parametrize("missing", ["sample", "buffer"])
    def test_missing_input_uncertainty_remains_unknown(self, missing):
        q, i_s, e_s, i_b, e_b = self._make_data(n=5)
        if missing == "sample":
            e_s = None
        else:
            e_b = None

        result = subtract_buffer(
            q, i_s, e_s, q, i_b, e_b, alpha_uncertainty=0.0
        )

        assert np.all(np.isnan(result.err_subtracted))

    def test_partial_unknown_input_uncertainty_is_not_replaced_by_zero(self):
        q, i_s, e_s, i_b, e_b = self._make_data(n=5)
        e_s[2] = np.nan

        result = subtract_buffer(
            q, i_s, e_s, q, i_b, e_b, alpha_uncertainty=0.0
        )

        assert np.isnan(result.err_subtracted[2])
        assert np.all(np.isfinite(result.err_subtracted[[0, 1, 3, 4]]))

    def test_interpolated_error_propagates_variance_with_squared_weights(self):
        q_s = np.array([1.0])
        q_b = np.array([0.0, 2.0])
        result = subtract_buffer(
            q_s,
            np.array([10.0]),
            np.array([0.4]),
            q_b,
            np.array([2.0, 4.0]),
            np.array([1.0, 3.0]),
            alpha_uncertainty=0.0,
        )

        # At the midpoint, Var(buffer) = 0.5²*1² + 0.5²*3² = 2.5.
        assert result.err_subtracted[0] == pytest.approx(np.sqrt(0.4**2 + 2.5))

    def test_alpha_uncertainty_is_propagated_from_buffer_intensity(self):
        q = np.array([0.01, 0.02, 0.03])
        result = subtract_buffer(
            q,
            np.full(3, 10.0),
            np.full(3, 0.1),
            q,
            np.full(3, 3.0),
            np.full(3, 0.2),
            alpha=2.0,
            alpha_uncertainty=0.05,
        )

        expected_statistical = np.sqrt(0.1**2 + (2.0 * 0.2) ** 2)
        expected_combined = np.sqrt(expected_statistical**2 + (3.0 * 0.05) ** 2)
        np.testing.assert_allclose(result.err_statistical, expected_statistical)
        np.testing.assert_allclose(result.err_subtracted, expected_combined)

    @pytest.mark.parametrize("alpha_uncertainty", [-0.1, np.inf, np.nan])
    def test_invalid_alpha_uncertainty_raises(self, alpha_uncertainty):
        q, i_s, e_s, i_b, e_b = self._make_data(n=5)
        with pytest.raises(ValueError, match="alpha_uncertainty"):
            subtract_buffer(
                q,
                i_s,
                e_s,
                q,
                i_b,
                e_b,
                alpha_uncertainty=alpha_uncertainty,
            )

    def test_interpolation_different_grids(self):
        n = 100
        q_s = np.linspace(0.01, 0.30, n)
        q_b = np.linspace(0.005, 0.35, 200)
        i_s = np.ones(n) * 10.0
        i_b = np.ones(200) * 3.0
        err_s = np.full(n, 0.1)
        err_b = np.full(200, 0.05)
        result = subtract_buffer(q_s, i_s, err_s, q_b, i_b, err_b, alpha=1.0)
        assert result.q.shape == q_s.shape
        np.testing.assert_allclose(result.i_subtracted, 7.0, atol=0.1)

    def test_close_but_distinct_q_grids_are_still_interpolated(self):
        q_s = np.array([0.1, 0.2, 0.3])
        q_b = np.array([0.099999, 0.200001, 0.300001])
        i_b = 1.0e9 * q_b

        result = subtract_buffer(
            q_s,
            np.zeros(3),
            np.zeros(3),
            q_b,
            i_b,
            np.zeros(3),
            alpha_uncertainty=0.0,
        )

        np.testing.assert_allclose(result.i_subtracted, -1.0e9 * q_s, rtol=0, atol=1e-6)

    def test_interpolation_outside_buffer_range_raises(self):
        q_s = np.array([0.01, 0.20, 0.40], dtype=float)
        q_b = np.array([0.05, 0.10, 0.30], dtype=float)
        i_s = np.ones(3) * 10.0
        i_b = np.ones(3) * 2.0
        err_s = np.full(3, 0.1)
        err_b = np.full(3, 0.05)

        try:
            subtract_buffer(q_s, i_s, err_s, q_b, i_b, err_b, alpha=1.0)
        except ValueError as exc:
            assert "outside buffer q range" in str(exc)
        else:
            raise AssertionError("Expected ValueError for non-overlapping q range")

    @pytest.mark.parametrize(
        ("err_sample", "err_buffer", "message"),
        [
            (np.array([0.1, -0.2, np.nan]), np.full(3, 0.05), "err_sample"),
            (np.full(3, 0.1), np.array([0.05, -0.02, np.nan]), "err_buffer"),
        ],
    )
    def test_negative_finite_errors_raise_before_non_finite_replacement(
        self, err_sample, err_buffer, message
    ):
        q = np.array([0.01, 0.02, 0.03], dtype=float)
        i_s = np.ones(3) * 10.0
        i_b = np.ones(3) * 2.0

        with pytest.raises(ValueError, match=message):
            subtract_buffer(q, i_s, err_sample, q, i_b, err_buffer, alpha=1.0)


class TestValidateAlpha:
    def test_valid_alpha(self):
        # Should not raise or log warnings
        validate_alpha(1.0)
        validate_alpha(0.95)

    def test_alpha_out_of_range_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            validate_alpha(0.5)
        assert "far from 1.0" in caplog.text

    def test_alpha_negative_raises(self):
        try:
            validate_alpha(-0.1)
        except ValueError as exc:
            assert "must be finite and > 0" in str(exc)
        else:
            raise AssertionError("Expected ValueError for negative alpha")


def test_subtract_buffer_preserves_legacy_positional_high_q_window():
    q = np.array([0.10, 0.20, 0.30], dtype=float)
    result = subtract_buffer(
        q,
        np.array([3.0, 3.0, 3.0]),
        np.zeros(3),
        q,
        np.array([1.0, 1.0, 1.0]),
        np.zeros(3),
        1.0,
        (0.09, 0.31),
    )

    assert result.high_q_residual_mean == pytest.approx(2.0)


@pytest.mark.parametrize("field", ["err_sample", "err_buffer"])
def test_subtract_buffer_rejects_infinite_uncertainty(field):
    q = np.array([0.01, 0.02, 0.03], dtype=float)
    kwargs = {
        "q_sample": q,
        "i_sample": np.ones(3) * 10.0,
        "err_sample": np.full(3, 0.1),
        "q_buffer": q,
        "i_buffer": np.ones(3) * 2.0,
        "err_buffer": np.full(3, 0.05),
    }
    kwargs[field][1] = np.inf

    with pytest.raises(ValueError, match=field):
        subtract_buffer(**kwargs)
