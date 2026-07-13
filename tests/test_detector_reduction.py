import numpy as np
import pytest

from saxsabs.core.detector_reduction import (
    build_nist_net_image,
    normalize_detector_frame,
    validate_blank_transmission,
)


def test_normalize_detector_frame_scales_integrated_dark_by_exposure():
    image = np.array([[70.0]])  # 50 signal counts + 20 dark counts at 10 s
    dark = np.array([[2.0]])  # 2 dark counts at 1 s

    result = normalize_detector_frame(
        image,
        dark,
        image_exposure_s=10.0,
        dark_exposure_s=1.0,
        monitor=1.0,
        transmission=0.5,
        monitor_mode="rate",
    )

    assert result.dark_scale == 10.0
    assert result.normalization_factor == 5.0
    np.testing.assert_allclose(result.image, [[10.0]])


def test_build_nist_net_image_does_not_divide_blank_by_blank_transmission():
    sample = np.array([[70.0]])
    blank = np.array([[30.0]])
    dark = np.array([[2.0]])

    result = build_nist_net_image(
        sample,
        blank,
        dark,
        sample_exposure_s=10.0,
        background_exposure_s=10.0,
        dark_exposure_s=1.0,
        sample_monitor=1.0,
        background_monitor=1.0,
        sample_transmission=0.5,
        monitor_mode="rate",
        alpha=1.0,
    )

    # (70 - 20)/(10*1*0.5) - (30 - 20)/(10*1) = 10 - 1 = 9
    np.testing.assert_allclose(result.image, [[9.0]])
    assert result.norm_sample == 5.0
    assert result.norm_background == 10.0


@pytest.mark.parametrize(
    ("monitor_mode", "sample_monitor", "background_monitor"),
    [("rate", 2.0, 3.0), ("integrated", 40.0, 30.0)],
)
def test_nist_net_formula_handles_independent_exposures_and_monitor_modes(
    monitor_mode, sample_monitor, background_monitor
):
    result = build_nist_net_image(
        sample=np.array([[140.0]]),
        background=np.array([[50.0]]),
        dark=np.array([[4.0]]),
        sample_exposure_s=20.0,
        background_exposure_s=10.0,
        dark_exposure_s=2.0,
        sample_monitor=sample_monitor,
        background_monitor=background_monitor,
        sample_transmission=0.5,
        monitor_mode=monitor_mode,
        alpha=0.5,
    )

    # Sample: (140 - 4*10)/20 = 5; blank: (50 - 4*5)/30 = 1.
    np.testing.assert_allclose(result.image, [[4.5]])
    assert result.dark_scale_sample == pytest.approx(10.0)
    assert result.dark_scale_background == pytest.approx(5.0)
    assert result.norm_sample == pytest.approx(20.0)
    assert result.norm_background == pytest.approx(30.0)


@pytest.mark.parametrize(
    ("image", "dark"),
    [
        (np.array([[np.nan]]), np.zeros((1, 1))),
        (np.ones((1, 1)), np.array([[np.inf]])),
    ],
)
def test_normalize_detector_frame_rejects_nonfinite_detector_values(image, dark):
    with pytest.raises(ValueError, match="non-finite"):
        normalize_detector_frame(
            image,
            dark,
            image_exposure_s=1.0,
            dark_exposure_s=1.0,
            monitor=1.0,
            transmission=0.5,
            monitor_mode="rate",
        )


@pytest.mark.parametrize("alpha", [0.0, -1.0, float("nan")])
def test_build_nist_net_image_rejects_nonpositive_or_nonfinite_alpha(alpha):
    with pytest.raises(ValueError, match="alpha"):
        build_nist_net_image(
            np.ones((1, 1)),
            np.ones((1, 1)),
            np.zeros((1, 1)),
            sample_exposure_s=1.0,
            background_exposure_s=1.0,
            dark_exposure_s=1.0,
            sample_monitor=1.0,
            background_monitor=1.0,
            sample_transmission=0.5,
            monitor_mode="rate",
            alpha=alpha,
        )


def test_validate_blank_transmission_is_fail_closed():
    assert validate_blank_transmission(1.01, tolerance=0.02) == pytest.approx(1.01)
    with pytest.raises(ValueError, match="blank transmission"):
        validate_blank_transmission(0.95, tolerance=0.02)
    with pytest.raises(ValueError, match="blank transmission"):
        validate_blank_transmission(None, tolerance=0.02)
