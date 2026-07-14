from pathlib import Path

import pytest

from saxsabs.core.workbench_preflight_gate import (
    approve_preflight,
    choose_initial_window_geometry,
    configuration_fingerprint,
    format_mu_for_batch,
    require_current_preflight,
)


def test_window_geometry_fits_1024_by_700_viewport():
    geometry = choose_initial_window_geometry(1024, 700)

    assert geometry.width == 960
    assert geometry.height == 620
    assert geometry.x == 32
    assert geometry.y == 40
    assert geometry.tk_geometry == "960x620+32+40"


def test_window_geometry_keeps_preferred_size_on_large_screen():
    geometry = choose_initial_window_geometry(1920, 1080)

    assert (geometry.width, geometry.height) == (1280, 900)
    assert (geometry.x, geometry.y) == (320, 90)


@pytest.mark.parametrize("screen", [(0, 700), (1024, 0), (-1, 700)])
def test_window_geometry_rejects_invalid_screen_size(screen):
    with pytest.raises(ValueError):
        choose_initial_window_geometry(*screen)


def test_configuration_fingerprint_is_canonical_and_change_sensitive(tmp_path):
    first = {
        "mode": "fixed",
        "files": [Path(tmp_path / "a.tif")],
        "values": {"thickness_mm": 1.0, "transmission": 0.5},
    }
    reordered = {
        "values": {"transmission": 0.5, "thickness_mm": 1.0},
        "files": [str(tmp_path / "a.tif")],
        "mode": "fixed",
    }

    assert configuration_fingerprint(first) == configuration_fingerprint(reordered)
    changed = {**first, "mode": "auto"}
    assert configuration_fingerprint(first) != configuration_fingerprint(changed)


def test_preflight_approval_fails_closed_without_current_nonblocked_check():
    config = {"mode": "fixed", "thickness_mm": 1.0}

    with pytest.raises(RuntimeError, match="Dry Check"):
        require_current_preflight(None, config)

    blocked = approve_preflight(config, "BLOCKED")
    assert blocked.allows_run is False
    with pytest.raises(RuntimeError, match="BLOCKED"):
        require_current_preflight(blocked, config)

    ready = approve_preflight(config, "READY")
    assert require_current_preflight(ready, config) is ready
    with pytest.raises(RuntimeError, match="configuration changed"):
        require_current_preflight(ready, {**config, "thickness_mm": 1.1})


def test_mu_batch_format_preserves_precision_and_rejects_invalid_values():
    text = format_mu_for_batch(20.989980123456)

    assert text == "20.9899801235"
    assert float(text) == pytest.approx(20.989980123456, rel=1e-11)
    for invalid in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            format_mu_for_batch(invalid)
