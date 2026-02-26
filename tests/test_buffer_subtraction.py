"""Tests for buffer / solvent subtraction."""

import numpy as np

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
        result = subtract_buffer(q, i_s, e_s, q, i_b, e_b, alpha=alpha)
        expected_err = np.sqrt(e_s**2 + alpha**2 * e_b**2)
        np.testing.assert_allclose(result.err_subtracted, expected_err, rtol=1e-10)

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

    def test_alpha_negative_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            validate_alpha(-0.1)
        assert "far from 1.0" in caplog.text
