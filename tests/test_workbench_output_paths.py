import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest


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
