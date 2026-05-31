"""Shared Matplotlib style presets for SAXSAbs figures.

The presets are intentionally small and dependency-free.  They standardize
fonts, line weights, figure size, DPI, color choices, and export behavior
without changing any scientific calculation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pickle
from typing import Iterable

import matplotlib as mpl
from matplotlib.figure import Figure


@dataclass(frozen=True)
class PlotPreset:
    label: str
    figsize: tuple[float, float]
    dpi: int
    font_size: float
    label_size: float
    tick_size: float
    legend_size: float
    linewidth: float
    marker_size: float
    axes_linewidth: float
    constrained_layout: bool = True


PLOT_PRESETS: dict[str, PlotPreset] = {
    "single_column": PlotPreset(
        "Single-column figure", (3.45, 2.55), 600, 7.5, 8.0, 7.0, 7.0, 1.1, 3.6, 0.8
    ),
    "double_column": PlotPreset(
        "Double-column figure", (7.10, 4.40), 600, 8.5, 9.0, 7.5, 7.5, 1.2, 4.0, 0.9
    ),
    "presentation": PlotPreset(
        "Presentation", (10.0, 5.8), 300, 12.0, 13.0, 11.0, 11.0, 1.8, 5.6, 1.1
    ),
    "raw_inspection": PlotPreset(
        "Raw inspection", (7.2, 5.0), 150, 9.0, 10.0, 8.5, 8.0, 1.1, 4.0, 0.8
    ),
    "publication": PlotPreset(
        "Publication", (6.8, 4.2), 600, 8.5, 9.5, 8.0, 8.0, 1.25, 4.2, 0.9
    ),
}

PRESET_LABELS = {key: preset.label for key, preset in PLOT_PRESETS.items()}

SCIENCE_COLORS = {
    "blue": "#2b6cb0",
    "orange": "#dd6b20",
    "green": "#2f855a",
    "red": "#c53030",
    "purple": "#6b46c1",
    "gray": "#4a5568",
    "black": "#1a202c",
}


def _font_family() -> list[str]:
    return ["Arial", "Helvetica", "DejaVu Sans", "Microsoft YaHei", "sans-serif"]


def apply_nature_style(preset: str = "publication") -> None:
    """Apply a clean publication-oriented Matplotlib rc style globally."""
    p = PLOT_PRESETS.get(preset, PLOT_PRESETS["publication"])
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": _font_family(),
            "font.size": p.font_size,
            "axes.labelsize": p.label_size,
            "axes.titlesize": p.label_size,
            "xtick.labelsize": p.tick_size,
            "ytick.labelsize": p.tick_size,
            "legend.fontsize": p.legend_size,
            "lines.linewidth": p.linewidth,
            "lines.markersize": p.marker_size,
            "axes.linewidth": p.axes_linewidth,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
            "figure.dpi": p.dpi,
            "savefig.dpi": p.dpi,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.04,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "image.cmap": "viridis",
        }
    )


def create_figure(preset: str = "raw_inspection", **kwargs) -> Figure:
    """Create a Figure using one of the shared presets."""
    p = PLOT_PRESETS.get(preset, PLOT_PRESETS["raw_inspection"])
    options = {
        "figsize": p.figsize,
        "dpi": p.dpi,
        "constrained_layout": p.constrained_layout,
    }
    options.update(kwargs)
    return Figure(**options)


def style_axes(ax, preset: str = "publication", xlabel: str | None = None, ylabel: str | None = None):
    """Apply consistent axis styling without touching plotted data."""
    p = PLOT_PRESETS.get(preset, PLOT_PRESETS["publication"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_linewidth(p.axes_linewidth)
        ax.spines[side].set_color("#1f2933")
    ax.tick_params(
        axis="both",
        which="major",
        labelsize=p.tick_size,
        width=p.axes_linewidth,
        length=3.5,
        direction="out",
    )
    ax.tick_params(axis="both", which="minor", width=max(p.axes_linewidth * 0.75, 0.5), length=2.0)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.margins(x=0.03, y=0.06)
    return ax


def style_legend(ax, preset: str = "publication", loc: str = "best"):
    p = PLOT_PRESETS.get(preset, PLOT_PRESETS["publication"])
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return None
    legend = ax.legend(
        loc=loc,
        fontsize=p.legend_size,
        frameon=False,
        handlelength=2.0,
        borderaxespad=0.4,
    )
    return legend


def style_colorbar(colorbar, preset: str = "publication", label: str | None = None):
    p = PLOT_PRESETS.get(preset, PLOT_PRESETS["publication"])
    if label:
        colorbar.set_label(label, fontsize=p.label_size)
    colorbar.ax.tick_params(labelsize=p.tick_size, width=p.axes_linewidth, length=3.0)
    try:
        colorbar.outline.set_linewidth(p.axes_linewidth)
    except Exception:
        pass
    return colorbar


def apply_figure_preset(fig: Figure, preset: str = "publication") -> Figure:
    """Restyle an existing figure for screen display or export."""
    p = PLOT_PRESETS.get(preset, PLOT_PRESETS["publication"])
    fig.set_size_inches(*p.figsize, forward=True)
    fig.set_dpi(p.dpi)
    fig.set_facecolor("white")
    for ax in fig.get_axes():
        ax.set_facecolor("white")
        style_axes(ax, preset=preset)
        legend = ax.get_legend()
        if legend is not None:
            legend.set_frame_on(False)
            for text in legend.get_texts():
                text.set_fontsize(p.legend_size)
        ax.title.set_fontsize(p.label_size)
        ax.xaxis.label.set_fontsize(p.label_size)
        ax.yaxis.label.set_fontsize(p.label_size)
    return fig


def save_figure(fig: Figure, path: str | Path, preset: str = "publication") -> Path:
    """Save a figure with the selected preset and tight bounding box.

    The live Tk figure must not be restyled during export; otherwise the GUI
    canvas changes size/DPI after the user saves a publication preset.
    """
    path = Path(path)
    p = PLOT_PRESETS.get(preset, PLOT_PRESETS["publication"])
    export_fig = pickle.loads(pickle.dumps(fig))
    apply_figure_preset(export_fig, preset=preset)
    export_fig.savefig(path, dpi=p.dpi, bbox_inches="tight", pad_inches=0.04, facecolor="white")
    return path


def preset_choices() -> Iterable[tuple[str, str]]:
    return PRESET_LABELS.items()
