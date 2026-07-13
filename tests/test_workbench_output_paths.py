import csv
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from saxsabs.core.execution_policy import RunPolicy


def _load_workbench_module():
    pytest.importorskip("fabio")
    pytest.importorskip("pyFAI")

    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "SASAbs.py"
    spec = importlib.util.spec_from_file_location("saxsabs_workbench_output_path_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_workbench_resolves_actual_profile_output_paths(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    base = tmp_path / "sample.dat"

    assert app.resolve_profile_output_path(base, "tsv") == base
    assert app.resolve_profile_output_path(base, "csv") == tmp_path / "sample.csv"
    assert app.resolve_profile_output_path(base, "cansas_xml") == tmp_path / "sample.xml"
    assert app.resolve_profile_output_path(base, "nxcansas_h5") == tmp_path / "sample.h5"


def test_workbench_batch_targets_use_actual_format_suffixes(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    sector_each = tmp_path / "sector_each"
    sector_sum = tmp_path / "sector_sum"
    context = {
        "selected_modes": ["1d_full", "1d_sector"],
        "save_dirs": {
            "1d_full": tmp_path / "full",
            "1d_sector": tmp_path / "sector",
        },
        "sector_specs": [{"key": "sector_001", "label": "_001"}],
        "sector_save_each": True,
        "sector_save_combined": True,
        "sector_save_dirs": {"sector_001": sector_each},
        "sector_combined_dir": sector_sum,
        "output_format": "nxcansas_h5",
    }

    targets = app.build_sample_output_targets(context, "sample001")

    assert {tag for tag, _path in targets} == {"1d_full", "1d_sector_001", "1d_sector_sum"}
    assert all(path.suffix == ".h5" for _tag, path in targets)


def test_workbench_save_profile_table_returns_actual_xml_path(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)

    written = app.save_profile_table(
        tmp_path / "absolute.dat",
        np.array([0.01, 0.02, 0.03]),
        np.array([10.0, 9.0, 8.0]),
        np.array([0.1, 0.1, 0.1]),
        "Q_A^-1",
        output_format="cansas_xml",
    )

    assert written == tmp_path / "absolute.xml"
    assert written.exists()


def test_workbench_save_profile_table_uses_rerun_suffix_policy(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    original = tmp_path / "absolute.dat"
    original.write_text("old result", encoding="utf-8")

    written = app.save_profile_table(
        original,
        np.array([0.01, 0.02, 0.03]),
        np.array([10.0, 9.0, 8.0]),
        np.array([0.1, 0.1, 0.1]),
        "Q_A^-1",
        output_format="tsv",
        run_policy=RunPolicy(resume_enabled=False, overwrite_existing=False),
    )

    assert written == tmp_path / "absolute_rerun1.dat"
    assert written.exists()
    assert original.read_text(encoding="utf-8") == "old result"


@pytest.mark.parametrize(
    ("output_format", "suffix", "delimiter"),
    [("tsv", ".dat", "\t"), ("csv", ".csv", ",")],
)
def test_workbench_text_profile_labels_statistical_and_unknown_combined_errors(
    tmp_path,
    output_format,
    suffix,
    delimiter,
):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)

    written = app.save_profile_table(
        tmp_path / "absolute.dat",
        np.array([0.01, 0.02]),
        np.array([10.0, 9.0]),
        np.array([0.1, 0.2]),
        "Q_A^-1",
        output_format=output_format,
    )

    assert written.suffix == suffix
    with written.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=delimiter))
    assert rows[0]["Error_cm^-1"] == rows[0]["Error_Statistical_cm^-1"] == "0.1"
    assert rows[1]["Error_cm^-1"] == rows[1]["Error_Statistical_cm^-1"] == "0.2"
    assert all(row["Error_CombinedStandard_cm^-1"] == "NaN" for row in rows)


def test_workbench_cal2d_export_uses_explicit_overwrite_policy(tmp_path, monkeypatch):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    sample = tmp_path / "sample001.tif"
    sample.write_text("placeholder", encoding="utf-8")
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni_version: 2\nDetector: Detector\n", encoding="utf-8")
    captured = {}

    class FakeFabioImage:
        data = np.ones((2, 2), dtype=np.float64)
        header = {}

    def fake_write_package(config):
        captured["overwrite"] = config.overwrite
        return SimpleNamespace(
            image_path=tmp_path / "cal2d" / "images" / "sample001_cal2d.edf",
            metadata_path=tmp_path / "cal2d" / "metadata" / "sample001_cal2d.json",
            poni_path=tmp_path / "cal2d" / "geometry" / "sample001.poni",
            mask_npy_path=tmp_path / "cal2d" / "masks" / "sample001_mask.npy",
        )

    monkeypatch.setattr(module.fabio, "open", lambda _path: FakeFabioImage())
    monkeypatch.setattr(module, "write_calibrated2d_package", fake_write_package)
    app.parse_header = lambda _path, header_dict=None: (1.0, 10.0, 0.5)

    context = {
        "selected_modes": [],
        "parallel": False,
        "image_cache": {},
        "cache_lock": SimpleNamespace(__enter__=lambda self: self, __exit__=lambda *args: None),
        "ai_shared": SimpleNamespace(),
        "run_policy": RunPolicy(resume_enabled=False, overwrite_existing=False),
        "resume": False,
        "overwrite": False,
        "export_cal2d": True,
        "cal2d_root": tmp_path / "cal2d",
        "cal2d_apply_flat": True,
        "cal2d_dtype": "float32",
        "poni_path": poni,
        "ref_mode": "fixed",
        "fixed_dark_data": np.zeros((2, 2), dtype=np.float64),
        "fixed_dark_exposure_s": 1.0,
        "fixed_bg_norm": 1.0,
        "fixed_bg_net": np.zeros((2, 2), dtype=np.float64),
        "fixed_bg_path": "bg.tif",
        "fixed_dark_path": "dark.tif",
        "mask_arr": None,
        "flat_arr": None,
        "calc_mode": "fixed",
        "fixed_thk_cm": 0.1,
        "monitor_mode": "integrated",
        "k_factor": 2.0,
        "apply_solid_angle": False,
        "error_model": "none",
        "polarization_applied": False,
        "polarization": None,
        "bg_alpha": 1.0,
    }

    result = app.process_sample_task(1, str(sample), "sample001", context)

    assert result["row"]["Cal2D_Status"]
    assert captured["overwrite"] is False


def test_workbench_tab2_polarization_default_is_disabled_not_zero():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.t2_polarization = SimpleNamespace(get=lambda: 0.0)

    applied, factor = app.resolve_t2_polarization()

    assert applied is False
    assert factor is None


def test_workbench_k_history_uses_calibration_output_directory(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    std = tmp_path / "std001.tif"
    std.write_text("placeholder", encoding="utf-8")
    calibration_check = tmp_path / "saxsabs_calibration_outputs" / "calibration_check_run001.csv"

    app.append_k_history(
        files={"std": str(std), "bg": "bg.tif", "dark": "dark.tif", "poni": "geom.poni"},
        params={"std_exp": 1.0, "std_i0": 10.0, "std_t": 0.5, "std_thk": 1.0, "bg_exp": 1.0, "bg_i0": 8.0, "bg_t": 1.0},
        monitor_mode="integrated",
        apply_solid_angle=True,
        k_val=2.5,
        k_std=0.1,
        points_used=12,
        q_min=0.01,
        q_max=0.2,
        output_dir=tmp_path / "saxsabs_calibration_outputs",
        run_id="run001",
        calibration_check_path=calibration_check,
        calibration_record_path=tmp_path / "saxsabs_calibration_outputs" / "calibration_record_run001.json",
        calibration_uncertainty={
            "standard_uncertainty_status": "unknown",
            "k_statistical_standard_uncertainty": 0.01,
            "k_standard_uncertainty": None,
            "k_expanded_uncertainty": None,
            "coverage_factor": None,
        },
    )

    history = tmp_path / "saxsabs_calibration_outputs" / "k_factor_history.csv"
    assert history.exists()
    text = history.read_text(encoding="utf-8-sig")
    assert "run001" in text
    assert "calibration_check_run001.csv" in text
    assert "CalibrationRecordFile" in text
    assert "calibration_record_run001.json" in text
    assert "K_StandardUncertaintyStatus" in text
    assert "unknown" in text
    assert "None" not in text


def _cal2d_resume_contract(sample_id):
    return {
        "calibration_context_fingerprint": "ctx-current",
        "normalization": {
            "mode": "rate",
            "formula": "exp * I0 * T",
            "k_factor": 2.5,
            "thickness_cm": 0.1,
        },
        "background": {"alpha": 1.0, "bg_norm": 4.0},
        "integration_policy": {
            "correctSolidAngle": True,
            "polarization_factor": 0.95,
            "flat_applied_in_image": False,
        },
        "flat_path": "flat.edf",
        "source": {
            "output_stem": sample_id.removesuffix("_deadbeef"),
            "cal2d_dtype": "float32",
        },
    }


def _append_history_row(app, output_dir, run_id):
    app.append_k_history(
        files={
            "std": str(output_dir.parent / "std.tif"),
            "bg": str(output_dir.parent / "bg.tif"),
            "dark": str(output_dir.parent / "dark.tif"),
            "poni": str(output_dir.parent / "geometry.poni"),
        },
        params={
            "std_exp": 1.0,
            "std_i0": 10.0,
            "std_t": 0.5,
            "std_thk": 1.055,
            "bg_exp": 1.0,
            "bg_i0": 8.0,
            "bg_t": 1.0,
        },
        monitor_mode="integrated",
        apply_solid_angle=True,
        k_val=2.5,
        k_std=0.1,
        points_used=12,
        q_min=0.01,
        q_max=0.2,
        output_dir=output_dir,
        run_id=run_id,
        calibration_check_path=output_dir / f"calibration_check_{run_id}.csv",
        calibration_context_path=output_dir / f"calibration_context_{run_id}.json",
        calibration_record_path=output_dir / f"calibration_record_{run_id}.json",
    )


def test_workbench_k_history_refuses_to_replace_unreadable_history(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    output_dir = tmp_path / "saxsabs_calibration_outputs"
    output_dir.mkdir()
    history = output_dir / "k_factor_history.csv"
    original = b"BROKEN_HISTORY\x00\xff"
    history.write_bytes(original)

    with pytest.raises(ValueError, match="unreadable.*refusing to overwrite"):
        _append_history_row(app, output_dir, "run002")

    assert history.read_bytes() == original


def test_workbench_k_history_atomic_failure_preserves_original(
    tmp_path, monkeypatch
):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    output_dir = tmp_path / "saxsabs_calibration_outputs"
    _append_history_row(app, output_dir, "run001")
    history = output_dir / "k_factor_history.csv"
    original = history.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        _append_history_row(app, output_dir, "run002")

    assert history.read_bytes() == original
    assert not list(output_dir.glob(".k_factor_history.csv.*.tmp"))


def test_workbench_k_history_paths_are_relative_to_history_directory(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    output_dir = tmp_path / "saxsabs_calibration_outputs"
    _append_history_row(app, output_dir, "run001")

    row = __import__("pandas").read_csv(output_dir / "k_factor_history.csv").iloc[0]
    for field in (
        "Std_File",
        "BG_File",
        "Dark_File",
        "Poni_File",
        "Calibration_Check",
        "CalibrationContextFile",
        "CalibrationRecordFile",
    ):
        assert not Path(str(row[field])).is_absolute(), field

def _write_complete_cal2d_resume_package(module, root, sample_id):
    from fabio.edfimage import EdfImage

    paths = module._calibrated2d_package_paths(root, sample_id)
    image = np.arange(12, dtype=np.float32).reshape(3, 4)
    mask = np.zeros((3, 4), dtype=np.uint8)
    paths["image"].parent.mkdir(parents=True, exist_ok=True)
    EdfImage(data=image).write(str(paths["image"]))
    paths["mask_npy"].parent.mkdir(parents=True, exist_ok=True)
    np.save(paths["mask_npy"], mask)
    EdfImage(data=mask).write(str(paths["mask_edf"]))
    paths["poni"].parent.mkdir(parents=True, exist_ok=True)
    paths["poni"].write_text(
        "poni_version: 2\nDetector: Detector\nDistance: 1\n",
        encoding="utf-8",
    )
    paths["metadata"].parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "saxsabs.calibrated2d.v1",
        "files": {
            "calibrated_image": f"../images/{sample_id}_cal2d.edf",
            "mask_npy": f"../masks/{sample_id}_mask.npy",
            "mask_edf": f"../masks/{sample_id}_mask.edf",
            "poni": f"../geometry/{sample_id}.poni",
        },
        "qc": {"image_shape": [3, 4], "mask_shape": [3, 4]},
        **_cal2d_resume_contract(sample_id),
    }
    paths["metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return paths


def test_workbench_cal2d_resume_validation_rejects_incomplete_package(tmp_path):
    module = _load_workbench_module()
    sample_id = "sample001_deadbeef"
    paths = module._calibrated2d_package_paths(tmp_path / "cal2d", sample_id)
    paths["image"].parent.mkdir(parents=True, exist_ok=True)
    paths["image"].write_bytes(b"partial-edf")

    with pytest.raises(ValueError, match="incomplete existing calibrated 2D package"):
        module._validate_existing_calibrated2d_package(tmp_path / "cal2d", sample_id)


def test_workbench_cal2d_resume_validation_accepts_complete_consistent_package(tmp_path):
    module = _load_workbench_module()
    sample_id = "sample001_deadbeef"
    root = tmp_path / "cal2d"
    paths = _write_complete_cal2d_resume_package(module, root, sample_id)

    validated = module._validate_existing_calibrated2d_package(root, sample_id)

    assert validated == paths


def test_workbench_cal2d_resume_validation_rejects_truncated_complete_package(tmp_path):
    module = _load_workbench_module()
    sample_id = "sample001_deadbeef"
    root = tmp_path / "cal2d"
    paths = _write_complete_cal2d_resume_package(module, root, sample_id)
    paths["mask_npy"].write_bytes(b"")

    with pytest.raises(ValueError, match="truncated.*mask_npy"):
        module._validate_existing_calibrated2d_package(root, sample_id)


def test_workbench_cal2d_resume_validation_rejects_shape_mismatch(tmp_path):
    module = _load_workbench_module()
    sample_id = "sample001_deadbeef"
    root = tmp_path / "cal2d"
    paths = _write_complete_cal2d_resume_package(module, root, sample_id)
    np.save(paths["mask_npy"], np.zeros((2, 4), dtype=np.uint8))

    with pytest.raises(ValueError, match="shape mismatch"):
        module._validate_existing_calibrated2d_package(root, sample_id)


def test_workbench_cal2d_resume_validation_rejects_same_shape_mask_content_mismatch(
    tmp_path,
):
    module = _load_workbench_module()
    sample_id = "sample001_deadbeef"
    root = tmp_path / "cal2d"
    paths = _write_complete_cal2d_resume_package(module, root, sample_id)
    np.save(paths["mask_npy"], np.ones((3, 4), dtype=np.uint8))

    with pytest.raises(ValueError, match="mask.*content mismatch"):
        module._validate_existing_calibrated2d_package(root, sample_id)


def test_workbench_cal2d_resume_binds_current_image_mask_poni_context_and_parameters(
    tmp_path,
):
    module = _load_workbench_module()
    sample_id = "sample001_deadbeef"
    root = tmp_path / "cal2d"
    paths = _write_complete_cal2d_resume_package(module, root, sample_id)
    current_poni = tmp_path / "current.poni"
    current_poni.write_bytes(paths["poni"].read_bytes())
    expected_metadata = _cal2d_resume_contract(sample_id)
    expected_image = np.arange(12, dtype=np.float32).reshape(3, 4)
    expected_mask = np.zeros((3, 4), dtype=np.uint8)

    validated = module._validate_existing_calibrated2d_package(
        root,
        sample_id,
        expected_image=expected_image,
        expected_mask=expected_mask,
        expected_poni_path=current_poni,
        expected_metadata=expected_metadata,
    )
    assert validated == paths

    stale_context = json.loads(json.dumps(expected_metadata))
    stale_context["calibration_context_fingerprint"] = "ctx-stale"
    with pytest.raises(ValueError, match="calibration_context_fingerprint"):
        module._validate_existing_calibrated2d_package(
            root,
            sample_id,
            expected_image=expected_image,
            expected_mask=expected_mask,
            expected_poni_path=current_poni,
            expected_metadata=stale_context,
        )

    changed_parameters = json.loads(json.dumps(expected_metadata))
    changed_parameters["normalization"]["k_factor"] = 9.0
    with pytest.raises(ValueError, match="normalization"):
        module._validate_existing_calibrated2d_package(
            root,
            sample_id,
            expected_image=expected_image,
            expected_mask=expected_mask,
            expected_poni_path=current_poni,
            expected_metadata=changed_parameters,
        )

    changed_poni = tmp_path / "changed.poni"
    changed_poni.write_text(
        "poni_version: 2\nDetector: DifferentDetector\nDistance: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="PONI content mismatch"):
        module._validate_existing_calibrated2d_package(
            root,
            sample_id,
            expected_image=expected_image,
            expected_mask=expected_mask,
            expected_poni_path=changed_poni,
            expected_metadata=expected_metadata,
        )

def test_workbench_rejects_out_of_range_batch_workers():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)

    assert app.validate_batch_workers(1) == 1
    assert app.validate_batch_workers(module.MAX_BATCH_WORKERS) == module.MAX_BATCH_WORKERS
    for invalid in (0, module.MAX_BATCH_WORKERS + 1, 1000, 1.5, True, "nan"):
        with pytest.raises(ValueError):
            app.validate_batch_workers(invalid)


def test_workbench_output_stems_are_bounded_unique_and_stable(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    long_stem = "sample_" + ("verylong" * 40)
    files = [
        str(tmp_path / "run_a" / f"{long_stem}.tif"),
        str(tmp_path / "run_b" / f"{long_stem}.tif"),
    ]

    first = app.build_output_stem_map(files)
    second = app.build_output_stem_map(files)

    assert first == second
    assert len(set(value.casefold() for value in first.values())) == len(files)
    assert all(len(value) <= module.MAX_OUTPUT_STEM_LENGTH for value in first.values())
    assert all(not value.endswith((" ", ".")) for value in first.values())


def test_workbench_allocates_one_rerun_id_for_entire_cal2d_package(tmp_path):
    module = _load_workbench_module()
    root = tmp_path / "cal2d"
    sample_id = "sample001_deadbeef"
    base_paths = module._calibrated2d_package_paths(root, sample_id)
    base_paths["image"].parent.mkdir(parents=True, exist_ok=True)
    base_paths["image"].write_bytes(b"existing")
    rerun1_paths = module._calibrated2d_package_paths(root, f"{sample_id}_rerun1")
    rerun1_paths["metadata"].parent.mkdir(parents=True, exist_ok=True)
    rerun1_paths["metadata"].write_bytes(b"existing")

    allocated = module._allocate_calibrated2d_rerun_id(root, sample_id)

    assert allocated == f"{sample_id}_rerun2"
    allocated_paths = module._calibrated2d_package_paths(root, allocated)
    assert all(allocated in path.name for path in allocated_paths.values())
    assert not any(path.exists() for path in allocated_paths.values())
