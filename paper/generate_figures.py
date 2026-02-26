#!/usr/bin/env python3
"""Generate publication-quality figures for the JOSS paper.

Run:  python paper/generate_figures.py
Output:
  paper/fig_workflow.png       – calibration workflow diagram
  paper/fig_kfactor_demo.png   – K-factor estimation demonstration
"""

from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe

OUT_DIR = Path(__file__).resolve().parent

# ══════════════════════════════════════════════════════════════════════
# Figure 1 — Calibration Workflow Diagram
# ══════════════════════════════════════════════════════════════════════

def make_workflow_figure():
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    # ── colour palette ──
    c_input  = "#E8F0FE"  # light blue
    c_core   = "#FFF3E0"  # light orange
    c_output = "#E8F5E9"  # light green
    c_ref    = "#FCE4EC"  # light pink
    c_border = "#455A64"
    c_arrow  = "#37474F"

    def box(x, y, w, h, text, color, fontsize=9, bold=False):
        bx = FancyBboxPatch(
            (x - w/2, y - h/2), w, h,
            boxstyle="round,pad=0.12",
            facecolor=color, edgecolor=c_border, linewidth=1.2,
        )
        ax.add_patch(bx)
        weight = "bold" if bold else "normal"
        ax.text(x, y, text, ha="center", va="center",
                fontsize=fontsize, fontweight=weight, color="#212121",
                wrap=True)
        return bx

    def arrow(x1, y1, x2, y2, text="", curved=False):
        style = "Simple,tail_width=0.6,head_width=6,head_length=4"
        if curved:
            a = FancyArrowPatch(
                (x1, y1), (x2, y2),
                connectionstyle="arc3,rad=0.25",
                arrowstyle=style, color=c_arrow, linewidth=1.0,
            )
        else:
            a = FancyArrowPatch(
                (x1, y1), (x2, y2),
                arrowstyle=style, color=c_arrow, linewidth=1.0,
            )
        ax.add_patch(a)
        if text:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            ax.text(mx + 0.15, my + 0.12, text, fontsize=7,
                    color="#616161", style="italic")

    # ── Row 1: Inputs ──
    y1 = 6.0
    box(1.5, y1, 2.4, 0.75, "2D Detector\nImages", c_input, 9, True)
    box(5.0, y1, 2.4, 0.75, "Instrument\nMetadata", c_input, 9, True)
    box(8.5, y1, 2.4, 0.75, "NIST SRM 3600\nReference", c_ref, 9, True)

    # ── Row 2: Parsing ──
    y2 = 4.7
    box(3.25, y2, 3.0, 0.65, "Header Parsing  &  Normalization", c_core, 9)
    arrow(1.5, y1 - 0.38, 3.25, y2 + 0.33)
    arrow(5.0, y1 - 0.38, 3.25, y2 + 0.33)

    # ── Row 3: 2D Processing ──
    y3 = 3.6
    box(3.25, y3, 3.5, 0.65, "Dark Subtraction  →  BG Subtraction  →  pyFAI Integration", c_core, 8.5)
    arrow(3.25, y2 - 0.33, 3.25, y3 + 0.33)

    # ── Row 4: K-factor ──
    y4 = 2.5
    box(5.5, y4, 3.5, 0.65, "Robust K-factor Estimation\n(median + MAD outlier rejection)", c_core, 8.5)
    arrow(3.25, y3 - 0.33, 5.5, y4 + 0.33)
    arrow(8.5, y1 - 0.38, 5.5, y4 + 0.33, curved=False)

    # ── Row 5: Absolute conversion ──
    y5 = 1.4
    box(5.0, y5, 3.0, 0.65, "I_abs(q) = K × I_1D(q) / d", c_core, 10, True)
    arrow(5.5, y4 - 0.33, 5.0, y5 + 0.33)

    # ── Row 6: Outputs ──
    y6 = 0.35
    box(2.0, y6, 2.4, 0.55, "Calibrated\n1D Profiles", c_output, 9, True)
    box(5.0, y6, 2.2, 0.55, "Batch\nReports", c_output, 9, True)
    box(8.0, y6, 2.4, 0.55, "K-factor\nHistory Log", c_output, 9, True)
    arrow(5.0, y5 - 0.33, 2.0, y6 + 0.28)
    arrow(5.0, y5 - 0.33, 5.0, y6 + 0.28)
    arrow(5.0, y5 - 0.33, 8.0, y6 + 0.28)

    # ── Legend ──
    for lx, lc, lt in [(0.3, c_input, "Input"), (1.5, c_core, "Processing"),
                        (2.9, c_output, "Output"), (4.1, c_ref, "Reference")]:
        bx = FancyBboxPatch((lx, 6.65), 0.7, 0.25, boxstyle="round,pad=0.05",
                            facecolor=lc, edgecolor=c_border, linewidth=0.8)
        ax.add_patch(bx)
        ax.text(lx + 0.75 + 0.08, 6.775, lt, fontsize=7.5, va="center", color="#424242")

    fig.savefig(OUT_DIR / "fig_workflow.png", dpi=300, bbox_inches="tight",
                facecolor="white", pad_inches=0.15)
    plt.close(fig)
    print(f"  ✓ fig_workflow.png")


# ══════════════════════════════════════════════════════════════════════
# Figure 2 — K-factor Estimation Demonstration
# ══════════════════════════════════════════════════════════════════════

# NIST SRM 3600 reference data (15 points)
Q_REF = np.array([0.008, 0.010, 0.020, 0.030, 0.040, 0.050, 0.060,
                   0.080, 0.100, 0.120, 0.150, 0.180, 0.200, 0.220, 0.250])
I_REF = np.array([35.0, 34.2, 30.8, 28.8, 27.5, 26.8, 26.3,
                   25.4, 23.6, 20.8, 15.8, 10.9, 8.4, 6.5, 4.2])


def make_kfactor_figure():
    np.random.seed(42)

    # ── Simulate a measured profile (K_true ≈ 0.035, with noise + 2 outliers) ──
    K_TRUE = 0.035
    q_dense = np.linspace(0.006, 0.260, 200)
    i_ref_dense = np.interp(q_dense, Q_REF, I_REF)
    noise = 1 + np.random.normal(0, 0.03, size=q_dense.shape)
    i_meas_dense = i_ref_dense / K_TRUE * noise

    # Interpolate measured onto reference grid
    i_meas_at_ref = np.interp(Q_REF, q_dense, i_meas_dense)
    ratios = I_REF / i_meas_at_ref

    # Inject two artificial outliers
    ratios_with_outliers = ratios.copy()
    ratios_with_outliers[1] = K_TRUE * 3.5    # outlier high
    ratios_with_outliers[13] = K_TRUE * 0.3    # outlier low

    # Recompute measured values to show outlier-affected data
    i_meas_at_ref_vis = I_REF / ratios_with_outliers

    # MAD outlier rejection
    r_med = np.median(ratios_with_outliers)
    r_mad = np.median(np.abs(ratios_with_outliers - r_med))
    robust_sigma = 1.4826 * r_mad
    inlier_mask = np.abs(ratios_with_outliers - r_med) <= 3.0 * robust_sigma
    k_robust = np.median(ratios_with_outliers[inlier_mask])

    # ── Create figure ──
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"wspace": 0.35})

    # --- Panel (a): I(q) curves ---
    ax1 = axes[0]
    ax1.semilogy(Q_REF, I_REF, "s-", color="#D32F2F", markersize=6,
                 linewidth=1.5, label="NIST SRM 3600 reference", zorder=3)
    ax1.semilogy(q_dense, i_meas_dense * K_TRUE, "-", color="#1976D2",
                 linewidth=1.2, alpha=0.7, label="Measured (rescaled by K)")
    ax1.set_xlabel(r"$q$ (Å$^{-1}$)", fontsize=11)
    ax1.set_ylabel(r"$I(q)$ (cm$^{-1}$ sr$^{-1}$)", fontsize=11)
    ax1.set_title("(a) Scattering profiles", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=8.5, loc="upper right", framealpha=0.9)
    ax1.set_xlim(0, 0.27)
    ax1.tick_params(labelsize=9)
    ax1.grid(True, alpha=0.3, linewidth=0.5)

    # --- Panel (b): Ratio plot with MAD filtering ---
    ax2 = axes[1]
    # Inliers
    ax2.plot(Q_REF[inlier_mask], ratios_with_outliers[inlier_mask], "o",
             color="#2E7D32", markersize=7, label="Inlier ratios", zorder=3)
    # Outliers
    ax2.plot(Q_REF[~inlier_mask], ratios_with_outliers[~inlier_mask], "x",
             color="#D32F2F", markersize=9, markeredgewidth=2,
             label="Rejected outliers", zorder=3)
    # Median line
    ax2.axhline(k_robust, color="#1976D2", linewidth=1.5, linestyle="-",
                label=f"K = {k_robust:.4f}", zorder=2)
    # ±3σ band
    lower = r_med - 3 * robust_sigma
    upper = r_med + 3 * robust_sigma
    ax2.axhspan(lower, upper, alpha=0.12, color="#1976D2",
                label=f"±3σ̂ band (σ̂ = {robust_sigma:.5f})")
    ax2.axhline(lower, color="#1976D2", linewidth=0.7, linestyle="--", alpha=0.5)
    ax2.axhline(upper, color="#1976D2", linewidth=0.7, linestyle="--", alpha=0.5)

    ax2.set_xlabel(r"$q$ (Å$^{-1}$)", fontsize=11)
    ax2.set_ylabel(r"$R_i = I_{\mathrm{ref}} / I_{\mathrm{meas}}$", fontsize=11)
    ax2.set_title("(b) Robust K-factor estimation", fontsize=11, fontweight="bold")
    ax2.legend(fontsize=8, loc="upper right", framealpha=0.9)
    ax2.set_xlim(0, 0.27)
    ax2.tick_params(labelsize=9)
    ax2.grid(True, alpha=0.3, linewidth=0.5)

    fig.savefig(OUT_DIR / "fig_kfactor_demo.png", dpi=300, bbox_inches="tight",
                facecolor="white", pad_inches=0.1)
    plt.close(fig)
    print(f"  ✓ fig_kfactor_demo.png")


# ══════════════════════════════════════════════════════════════════════
# Run all
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Generating JOSS paper figures ...")
    make_workflow_figure()
    make_kfactor_figure()
    print("Done.")
