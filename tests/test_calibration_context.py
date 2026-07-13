from pathlib import Path

import pytest

from saxsabs.core.calibration_context import CalibrationContext, sha256_file


def _context(**overrides):
    values = {
        "formula_version": "v3_nist_blank",
        "monitor_mode": "rate",
        "poni_sha256": "poni-sha",
        "mask_sha256": "mask-sha",
        "flat_sha256": None,
        "correct_solid_angle": True,
        "polarization_factor": None,
        "standard_key": "SRM3600",
        "standard_thickness_cm": 0.1055,
    }
    values.update(overrides)
    return CalibrationContext(**values)


def test_calibration_context_fingerprint_includes_standard_provenance():
    first = _context(standard_thickness_cm=0.1055)
    second = _context(standard_thickness_cm=0.1)
    assert first.fingerprint() != second.fingerprint()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("monitor_mode", "integrated"),
        ("poni_sha256", "other-poni"),
        ("mask_sha256", "other-mask"),
        ("flat_sha256", "flat-sha"),
        ("correct_solid_angle", False),
        ("polarization_factor", 0.95),
    ],
)
def test_calibration_context_blocks_operator_mismatch(field, value):
    calibrated = _context()
    current = _context(**{field: value})

    with pytest.raises(ValueError, match=field):
        calibrated.assert_operator_compatible(current)


def test_sha256_file_is_content_based(tmp_path: Path):
    path = tmp_path / "geometry.poni"
    path.write_text("poni-v1", encoding="utf-8")
    first = sha256_file(path)
    path.write_text("poni-v2", encoding="utf-8")
    assert sha256_file(path) != first

