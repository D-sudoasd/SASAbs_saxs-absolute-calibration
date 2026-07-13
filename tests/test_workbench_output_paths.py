import csv
import importlib.util
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
