import importlib.util
import os
from pathlib import Path
import sys

from matplotlib.figure import Figure
import pytest

import saxs_mpl_style


def test_plot_presets_cover_required_export_modes():
    required = {
        "single_column",
        "double_column",
        "presentation",
        "raw_inspection",
        "publication",
    }
    assert required <= set(saxs_mpl_style.PLOT_PRESETS)
    assert saxs_mpl_style.PLOT_PRESETS["publication"].dpi >= 600
    assert saxs_mpl_style.PLOT_PRESETS["raw_inspection"].dpi >= 150


def test_save_figure_uses_tight_publication_export(tmp_path):
    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0, 1], [1, 2], label="data")
    ax.set_xlabel("q (A$^{-1}$)")
    ax.set_ylabel("Intensity (cm$^{-1}$)")
    ax.legend()

    out = tmp_path / "figure.pdf"
    result = saxs_mpl_style.save_figure(fig, out, preset="publication")

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_save_figure_does_not_mutate_live_figure(tmp_path):
    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0, 1], [1, 2], label="data")
    ax.set_title("Screen title")
    ax.legend(frameon=True)

    original_size = tuple(fig.get_size_inches())
    original_dpi = fig.get_dpi()
    original_facecolor = fig.get_facecolor()
    original_top_spine_visible = ax.spines["top"].get_visible()
    original_legend_frame = ax.get_legend().get_frame_on()

    out = tmp_path / "figure.png"
    saxs_mpl_style.save_figure(fig, out, preset="publication")

    assert out.exists()
    assert tuple(fig.get_size_inches()) == original_size
    assert fig.get_dpi() == original_dpi
    assert fig.get_facecolor() == original_facecolor
    assert ax.spines["top"].get_visible() == original_top_spine_visible
    assert ax.get_legend().get_frame_on() == original_legend_frame


def test_saxsabs_dynamic_load_finds_style_module_outside_repo_cwd(tmp_path, monkeypatch):
    pytest.importorskip("fabio")
    pytest.importorskip("pyFAI")

    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "SASAbs.py"
    original_style_module = sys.modules.pop("saxs_mpl_style", None)
    original_path = list(sys.path)

    try:
        monkeypatch.chdir(tmp_path)
        sys.path = [
            item
            for item in sys.path
            if Path(item or os.getcwd()).resolve() != repo_root.resolve()
        ]

        spec = importlib.util.spec_from_file_location("saxsabs_legacy_dynamic_test", script_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module.saxs_mpl_style, "PRESET_LABELS")
        assert ("single_column", "Single-column figure") in list(
            module.saxs_mpl_style.preset_choices()
        )
    finally:
        sys.path = original_path
        sys.modules.pop("saxs_mpl_style", None)
        if original_style_module is not None:
            sys.modules["saxs_mpl_style"] = original_style_module
