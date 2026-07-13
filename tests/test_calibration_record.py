import hashlib
import json
from pathlib import Path

import pytest

from saxsabs.core.calibration_context import (
    CalibrationContext,
    builtin_reference_identity,
    canonical_reference_sha256,
    sha256_file,
)
from saxsabs.core.calibration_record import (
    CALIBRATION_RECORD_SCHEMA_V1,
    CALIBRATION_RECORD_SCHEMA_V2,
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
    assert loaded.schema == CALIBRATION_RECORD_SCHEMA_V2
    assert loaded.provenance_complete is False
    assert "standard_data_sha256" in loaded.provenance_missing

    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["operator_files"]["poni"] == "geometry.poni"
    assert payload["provenance"]["status"] == "incomplete"


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


@pytest.mark.parametrize(
    "values",
    [
        (0.03, 0.02, None, None),
        (0.01, None, 0.04, 2.0),
        (0.01, 0.02, None, 2.0),
        (0.01, 0.02, 0.05, 2.0),
    ],
)
def test_core_uncertainty_rejects_internally_inconsistent_budgets(values):
    with pytest.raises(ValueError, match="uncertainty|coverage_factor|expanded"):
        build_calibration_uncertainty_payload(*values)


def test_core_calibration_record_reads_v1_as_explicitly_incomplete(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    context = _context(poni)
    old_context = {
        key: value
        for key, value in context.to_dict().items()
        if key
        in {
            "formula_version",
            "monitor_mode",
            "poni_sha256",
            "mask_sha256",
            "flat_sha256",
            "correct_solid_angle",
            "polarization_factor",
            "standard_key",
            "standard_thickness_cm",
        }
    }
    payload = {
        "schema": CALIBRATION_RECORD_SCHEMA_V1,
        "created_at": "2026-07-13T00:00:00",
        "k_factor": 2.5,
        "calibration_context": old_context,
        "calibration_context_fingerprint": hashlib.sha256(
            json.dumps(old_context, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "calibration_uncertainty": None,
        "operator_files": {"poni": str(poni.resolve()), "mask": "", "flat": ""},
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    payload["record_fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    record_path = tmp_path / "legacy-v1.json"
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = read_calibration_record(record_path)

    assert loaded.schema == CALIBRATION_RECORD_SCHEMA_V1
    assert loaded.provenance_complete is False
    assert loaded.provenance_missing[0] == "legacy_schema_v1"
    assert loaded.poni_path == poni.resolve()


def test_core_calibration_record_does_not_overwrite_damaged_history(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    record_path = tmp_path / "calibration_record.json"
    record_path.write_text("{damaged historical record", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_calibration_record(
            record_path,
            k_factor=2.5,
            calibration_context=_context(poni),
            calibration_uncertainty=None,
            poni_path=poni,
            mask_path=None,
            flat_path=None,
        )

    assert record_path.read_text(encoding="utf-8") == "{damaged historical record"


def test_core_calibration_record_atomic_failure_leaves_no_partial_target(
    tmp_path: Path, monkeypatch
):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    record_path = tmp_path / "calibration_record.json"

    def fail_link(_source, _target):
        raise OSError("injected atomic publish failure")

    monkeypatch.setattr("saxsabs.core.calibration_record.os.link", fail_link)

    with pytest.raises(OSError, match="injected"):
        write_calibration_record(
            record_path,
            k_factor=2.5,
            calibration_context=_context(poni),
            calibration_uncertainty=None,
            poni_path=poni,
            mask_path=None,
            flat_path=None,
        )

    assert not record_path.exists()
    assert not list(tmp_path.glob(".calibration_record.json.*.tmp"))

def test_core_v2_record_with_unverifiable_hashes_is_explicitly_incomplete(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    values = _context(poni).to_dict()
    values.update(
        standard_data_sha256="a" * 64,
        background_data_sha256=("b" * 64,),
        dark_data_sha256=("c" * 64,),
        standard_monitor=1000.0,
        standard_transmission=0.82,
        standard_exposure_s=10.0,
        background_monitors=(900.0,),
        background_transmissions=(0.91,),
        background_exposure_s=(10.0,),
        dark_exposure_s=(10.0,),
        q_window=(0.01, 0.2),
    )
    record_path = tmp_path / "complete.json"

    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=CalibrationContext.from_dict(values),
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
    )
    loaded = read_calibration_record(record_path)

    assert loaded.provenance_complete is False
    assert "source_files.standard" in loaded.provenance_missing
    assert "source_files.background" in loaded.provenance_missing
    assert "source_files.dark" in loaded.provenance_missing
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["provenance"]["status"] == "incomplete"

def _complete_source_context(
    poni: Path,
    standard: Path,
    backgrounds: tuple[Path, ...],
    darks: tuple[Path, ...],
) -> CalibrationContext:
    identity = builtin_reference_identity("SRM3600")
    values = _context(poni).to_dict()
    values.update(
        standard_data_sha256=sha256_file(standard),
        background_data_sha256=tuple(sha256_file(path) for path in backgrounds),
        dark_data_sha256=tuple(sha256_file(path) for path in darks),
        standard_monitor=1000.0,
        standard_transmission=0.82,
        standard_exposure_s=10.0,
        background_monitors=tuple(900.0 + index for index, _ in enumerate(backgrounds)),
        background_transmissions=tuple(0.91 for _ in backgrounds),
        background_exposure_s=tuple(10.0 for _ in backgrounds),
        dark_exposure_s=tuple(10.0 for _ in darks),
        q_window=(0.01, 0.2),
        reference_model_id=identity.model_id,
        reference_model_version=identity.model_version,
        reference_canonical_sha256=identity.canonical_sha256,
        background_scale_alpha=1.0,
        background_composition_rule="arithmetic_mean_after_individual_normalization",
        integration_unit="q_A^-1",
        integration_method="pyFAI.integrate1d:csr",
        integration_engine_version="test-pyFAI",
        integration_npt=1000,
        robust_estimator="median_mad",
        robust_mad_multiplier=3.0,
        robust_positive_floor=1e-9,
        robust_min_points=3,
        robust_zero_mad_relative_tolerance=1e-12,
    )
    return CalibrationContext.from_dict(values)


def test_v2_complete_record_verifies_ordered_portable_source_files(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    standard = tmp_path / "standard.tif"
    backgrounds = (tmp_path / "background-1.tif", tmp_path / "background-2.tif")
    darks = (tmp_path / "dark.tif",)
    for path, content in (
        (poni, b"poni"),
        (standard, b"standard"),
        (backgrounds[0], b"background-1"),
        (backgrounds[1], b"background-2"),
        (darks[0], b"dark"),
    ):
        path.write_bytes(content)
    record_path = tmp_path / "complete.json"

    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=_complete_source_context(poni, standard, backgrounds, darks),
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
        standard_data_path=standard,
        background_data_paths=backgrounds,
        dark_data_paths=darks,
    )
    loaded = read_calibration_record(record_path)

    assert loaded.provenance_complete is True
    assert loaded.standard_data_path == standard.resolve()
    assert loaded.background_data_paths == tuple(path.resolve() for path in backgrounds)
    assert loaded.dark_data_paths == tuple(path.resolve() for path in darks)
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["source_files"] == {
        "standard": "standard.tif",
        "background": ["background-1.tif", "background-2.tif"],
        "dark": ["dark.tif"],
        "reference": "",
    }


def test_v2_record_rejects_reordered_sources_even_when_all_hashes_are_valid(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    standard = tmp_path / "standard.tif"
    backgrounds = (tmp_path / "background-1.tif", tmp_path / "background-2.tif")
    darks = (tmp_path / "dark.tif",)
    for index, path in enumerate((poni, standard, *backgrounds, *darks)):
        path.write_bytes(f"source-{index}".encode())

    with pytest.raises(ValueError, match=r"background_data_sha256\[0\]"):
        write_calibration_record(
            tmp_path / "reordered.json",
            k_factor=2.5,
            calibration_context=_complete_source_context(poni, standard, backgrounds, darks),
            calibration_uncertainty=None,
            poni_path=poni,
            mask_path=None,
            flat_path=None,
            standard_data_path=standard,
            background_data_paths=tuple(reversed(backgrounds)),
            dark_data_paths=darks,
        )


def test_v2_complete_record_fails_closed_after_source_tampering(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    standard = tmp_path / "standard.tif"
    background = tmp_path / "background.tif"
    dark = tmp_path / "dark.tif"
    for index, path in enumerate((poni, standard, background, dark)):
        path.write_bytes(f"source-{index}".encode())
    record_path = tmp_path / "complete.json"
    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=_complete_source_context(
            poni, standard, (background,), (dark,)
        ),
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
        standard_data_path=standard,
        background_data_paths=(background,),
        dark_data_paths=(dark,),
    )
    background.write_bytes(b"tampered")

    with pytest.raises(ValueError, match=r"background_data_sha256\[0\]"):
        read_calibration_record(record_path)


def test_arbitrary_context_hashes_without_source_files_never_report_complete(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    identity = builtin_reference_identity("SRM3600")
    values = _context(poni).to_dict()
    values.update(
        standard_data_sha256="a" * 64,
        background_data_sha256=("b" * 64,),
        dark_data_sha256=("c" * 64,),
        standard_monitor=1000.0,
        standard_transmission=0.82,
        standard_exposure_s=10.0,
        background_monitors=(900.0,),
        background_transmissions=(0.91,),
        background_exposure_s=(10.0,),
        dark_exposure_s=(10.0,),
        q_window=(0.01, 0.2),
        reference_model_id=identity.model_id,
        reference_model_version=identity.model_version,
        reference_canonical_sha256=identity.canonical_sha256,
        background_scale_alpha=1.0,
        background_composition_rule="mean",
        integration_unit="q_A^-1",
        integration_method="csr",
        integration_engine_version="test-pyFAI",
        integration_npt=1000,
        robust_estimator="median_mad",
        robust_mad_multiplier=3.0,
        robust_positive_floor=1e-9,
        robust_min_points=3,
        robust_zero_mad_relative_tolerance=1e-12,
    )
    record_path = tmp_path / "fake-hashes.json"

    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=CalibrationContext.from_dict(values),
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
    )
    loaded = read_calibration_record(record_path)

    assert loaded.provenance_complete is False
    assert "source_files.standard" in loaded.provenance_missing
    assert "source_files.background" in loaded.provenance_missing
    assert "source_files.dark" in loaded.provenance_missing


def test_custom_reference_binds_raw_file_and_serialized_canonical_curve(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    standard = tmp_path / "standard.tif"
    background = tmp_path / "background.tif"
    dark = tmp_path / "dark.tif"
    reference = tmp_path / "reference.dat"
    for index, path in enumerate((poni, standard, background, dark, reference)):
        path.write_bytes(f"source-{index}".encode())
    q_ref = [0.01, 0.02, 0.03]
    i_ref = [10.0, 9.0, 8.0]
    values = _complete_source_context(
        poni, standard, (background,), (dark,)
    ).to_dict()
    values.update(
        standard_key="Custom",
        standard_thickness_cm=0.1,
        reference_curve_sha256=sha256_file(reference),
        reference_model_id="CUSTOM_REFERENCE_FILE",
        reference_model_version="parsed-q-i-v1",
        reference_canonical_sha256=canonical_reference_sha256(q_ref, i_ref),
    )
    record_path = tmp_path / "custom.json"

    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=CalibrationContext.from_dict(values),
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
        standard_data_path=standard,
        background_data_paths=(background,),
        dark_data_paths=(dark,),
        reference_curve_path=reference,
        reference_q=q_ref,
        reference_i=i_ref,
    )
    loaded = read_calibration_record(record_path)

    assert loaded.provenance_complete is True
    assert loaded.reference_curve_path == reference.resolve()


def test_custom_reference_rejects_canonical_curve_hash_mismatch(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    standard = tmp_path / "standard.tif"
    background = tmp_path / "background.tif"
    dark = tmp_path / "dark.tif"
    reference = tmp_path / "reference.dat"
    for index, path in enumerate((poni, standard, background, dark, reference)):
        path.write_bytes(f"source-{index}".encode())
    values = _complete_source_context(
        poni, standard, (background,), (dark,)
    ).to_dict()
    values.update(
        standard_key="Custom",
        standard_thickness_cm=0.1,
        reference_curve_sha256=sha256_file(reference),
        reference_model_id="CUSTOM_REFERENCE_FILE",
        reference_model_version="parsed-q-i-v1",
        reference_canonical_sha256="f" * 64,
    )

    with pytest.raises(ValueError, match="reference_canonical_sha256"):
        write_calibration_record(
            tmp_path / "custom.json",
            k_factor=2.5,
            calibration_context=CalibrationContext.from_dict(values),
            calibration_uncertainty=None,
            poni_path=poni,
            mask_path=None,
            flat_path=None,
            standard_data_path=standard,
            background_data_paths=(background,),
            dark_data_paths=(dark,),
            reference_curve_path=reference,
            reference_q=[0.01, 0.02, 0.03],
            reference_i=[10.0, 9.0, 8.0],
        )

def test_v2_complete_record_fails_closed_when_a_recorded_source_is_missing(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    standard = tmp_path / "standard.tif"
    background = tmp_path / "background.tif"
    dark = tmp_path / "dark.tif"
    for index, path in enumerate((poni, standard, background, dark)):
        path.write_bytes(f"source-{index}".encode())
    record_path = tmp_path / "complete.json"
    write_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=_complete_source_context(
            poni, standard, (background,), (dark,)
        ),
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
        standard_data_path=standard,
        background_data_paths=(background,),
        dark_data_paths=(dark,),
    )
    dark.unlink()

    with pytest.raises(FileNotFoundError, match=r"dark\[0\].*not found"):
        read_calibration_record(record_path)
