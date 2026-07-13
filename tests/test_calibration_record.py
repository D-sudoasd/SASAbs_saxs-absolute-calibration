import hashlib
import json
from pathlib import Path

import pytest

from saxsabs.core.calibration_context import CalibrationContext, sha256_file
from saxsabs.core.calibration_record import (
    CalibrationRecordLoadResult,
    build_calibration_uncertainty_payload,
    read_calibration_record,
    resolve_sample_thickness_config,
    write_calibration_record,
)


def _context(poni: Path) -> CalibrationContext:
    return CalibrationContext(
        formula_version="v3_nist_blank_exposure_matched",
        monitor_mode="rate",
        poni_sha256=sha256_file(poni),
        mask_sha256=None,
        flat_sha256=None,
        correct_solid_angle=True,
        polarization_factor=None,
        standard_key="SRM3600",
        standard_thickness_cm=0.1055,
    )


def test_core_uncertainty_and_thickness_policies_are_typed():
    uncertainty = build_calibration_uncertainty_payload(0.01, None, None, None)
    fixed = resolve_sample_thickness_config(
        mode="fixed",
        mu_value=None,
        fixed_thickness_mm=1.2,
    )

    assert uncertainty["standard_uncertainty_status"] == "unknown"
    assert uncertainty["k_standard_uncertainty"] is None
    assert fixed.mode == "fixed"
    assert fixed.mu_cm_inv is None
    assert fixed.fixed_thickness_cm == pytest.approx(0.12)


@pytest.mark.parametrize(
    ("values", "field_name"),
    [
        ((-0.01, None, None, None), "k_statistical_standard_uncertainty"),
        ((None, -0.02, None, None), "k_standard_uncertainty"),
        ((None, None, -0.04, None), "k_expanded_uncertainty"),
        ((float("inf"), None, None, None), "k_statistical_standard_uncertainty"),
        ((None, float("-inf"), None, None), "k_standard_uncertainty"),
        ((None, None, float("inf"), None), "k_expanded_uncertainty"),
        ((None, None, None, 0.0), "coverage_factor"),
        ((None, None, None, -2.0), "coverage_factor"),
        ((None, None, None, float("inf")), "coverage_factor"),
    ],
)
def test_core_uncertainty_rejects_invalid_values(values, field_name):
    with pytest.raises(ValueError, match=field_name):
        build_calibration_uncertainty_payload(*values)


def test_core_calibration_record_round_trip_returns_typed_result(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    context = _context(poni)
    record_path = tmp_path / "calibration_record.json"

    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=context,
        calibration_uncertainty=build_calibration_uncertainty_payload(
            0.01, 0.02, 0.04, 2.0
        ),
        poni_path=poni,
        mask_path=None,
        flat_path=None,
    )
    loaded = read_calibration_record(record_path)

    assert isinstance(loaded, CalibrationRecordLoadResult)
    assert loaded.k_factor == pytest.approx(2.5)
    assert loaded.calibration_context.fingerprint() == context.fingerprint()
    assert loaded.calibration_uncertainty is not None
    assert loaded.poni_path == poni.resolve()


def test_core_calibration_record_rejects_tampering_before_returning_state(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    record_path = tmp_path / "calibration_record.json"
    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=_context(poni),
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
    )
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["k_factor"] = 9.0
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="fingerprint"):
        read_calibration_record(record_path)


def test_core_calibration_record_write_rejects_negative_uncertainty(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")

    with pytest.raises(ValueError, match="k_standard_uncertainty"):
        write_calibration_record(
            tmp_path / "calibration_record.json",
            k_factor=2.5,
            calibration_context=_context(poni),
            calibration_uncertainty={"k_standard_uncertainty": -0.02},
            poni_path=poni,
            mask_path=None,
            flat_path=None,
        )


def test_core_calibration_record_rejects_validly_fingerprinted_negative_uncertainty(
    tmp_path: Path,
):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    record_path = tmp_path / "calibration_record.json"
    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=_context(poni),
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
    )
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["calibration_uncertainty"] = {
        "k_statistical_standard_uncertainty": 0.01,
        "k_standard_uncertainty": -0.02,
        "k_expanded_uncertainty": None,
        "coverage_factor": None,
    }
    canonical = dict(payload)
    canonical.pop("record_fingerprint")
    text = json.dumps(
        canonical,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    payload["record_fingerprint"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="k_standard_uncertainty"):
        read_calibration_record(record_path)
