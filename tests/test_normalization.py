import math

from saxsabs.core.normalization import compute_norm_factor, monitor_norm_formula


def test_monitor_norm_formula():
    assert monitor_norm_formula("rate") == "exp * I0 * T"
    assert monitor_norm_formula("integrated") == "I0 * T"


def test_compute_norm_factor_rate_ok():
    out = compute_norm_factor(exp=2.0, mon=100.0, trans=0.8, mode="rate")
    assert out == 160.0


def test_compute_norm_factor_integrated_ok():
    out = compute_norm_factor(exp=None, mon=100.0, trans=0.8, mode="integrated")
    assert out == 80.0


def test_compute_norm_factor_invalid_inputs_return_nan():
    out1 = compute_norm_factor(exp=1.0, mon=-1.0, trans=0.8, mode="rate")
    out2 = compute_norm_factor(exp=1.0, mon=1.0, trans=0.0, mode="rate")
    out3 = compute_norm_factor(exp=None, mon=1.0, trans=0.8, mode="rate")
    assert math.isnan(out1)
    assert math.isnan(out2)
    assert math.isnan(out3)
