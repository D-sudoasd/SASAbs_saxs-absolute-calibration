"""SAXSAbs Workbench — GUI for SAXS absolute intensity calibration.

Part of the saxsabs package.
Repository: https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration
License: BSD-3-Clause
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import argparse
import sys
import logging
import numpy as np
import fabio
import pyFAI
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from pathlib import Path
import traceback
import math
import pandas as pd
import datetime
import re
import json
import concurrent.futures
import threading
from types import SimpleNamespace

APP_NAME = "SAXSAbs Workbench"


def _read_package_version() -> str:
    """Keep the legacy GUI version aligned with the packaged library version."""
    version_file = Path(__file__).resolve().parent / "src" / "saxsabs" / "__init__.py"
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        return "1.1.1"
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "1.1.1"


APP_VERSION = _read_package_version()

logger = logging.getLogger(__name__)
SUPPORTED_LANGUAGES = ("en", "zh")

I18N = {
    "en": {
        "app_title": f"{APP_NAME} v{APP_VERSION}",
        "header_title": f"{APP_NAME}  |  Absolute Intensity Calibration",
        "theme_toggle": "🌓 Theme",
        "lang_toggle_to_zh": "中文",
        "lang_toggle_to_en": "English",
        "tab1": "\U0001f4d0  1. K-Factor Calibration",
        "tab2": "\U0001f4e6  2. Batch Processing",
        "tab3": "\U0001f4c8  3. External 1D \u2192 Abs",
        "tab4": "\u2753  4. Help",
        "t1_guide_title": "Quick Start",
        "t1_guide_text": "① Select standard/background/dark/geometry files\n② Verify auto-loaded Time, I0, T\n③ Set standard thickness (mm)\n④ Run calibration to obtain K\n⑤ Check Std Dev and valid points",
        "t1_files_title": "1. Calibration Files (Required)",
        "t1_phys_title": "2. Physical Parameters",
        "t1_run_btn": "\u25b6  Run K Calibration",
        "t1_hist_btn": "K History",
        "t1_report_title": "Analysis Report",
        "t1_plot_tip": "Plot: black dashed=net signal; blue=K-corrected; red circles=NIST",
        "t2_guide_title": "Batch Workflow",
        "t2_guide_text": "① Ensure K, BG/Dark, and poni are ready\n② Select thickness logic\n③ Select one or more integration modes\n④ Add sample files and run dry-check\n⑤ Start batch and review batch_report.csv",
        "t2_mid_title": "Sample Queue",
        "t2_add_btn": "Add Files",
        "t2_clear_btn": "Clear Queue",
        "t2_check_btn": "Dry Check",
        "t2_run_btn": "\u25b6  Start Batch Processing",
        "t3_guide_title": "External 1D Workflow",
        "t3_guide_text": "① Obtain K in Tab1\n② Select pipeline mode (scaled/raw)\n③ Import external 1D files\n④ Select correction formula and X-axis type\n⑤ Dry-check then batch-export absolute intensity",
        "t3_mid_title": "External 1D Queue",
        "t3_add_btn": "Add 1D Files",
        "t3_clear_btn": "Clear Queue",
        "t3_check_btn": "Dry Check",
        "t3_run_btn": "\u25b6  Start External 1D Calibration",
        "queue_files": "Queue files",
        "queue_dedup": "deduplicated",
        "out_auto_prefix": "Output directories will be created",
        "out_write_prefix": "Output directories under",
        "out_none_mode": "Output: no integration mode selected",
        "msg_help_title": "Help",
        "msg_help_copied": "Help text has been copied to clipboard.",
        "msg_preview_title": "Dry Check",
        "msg_ext_done_title": "External 1D Completed",
        "msg_ext_error_title": "External 1D Error",
        "msg_calib_error_title": "Calibration Error",
        "msg_k_history_title": "K History",
        "msg_batch_error_title": "Batch Processing Error",
        "msg_iq_preview_error_title": "I-Q Preview Error",
        "msg_ichi_preview_error_title": "I-chi Preview Error",
        "msg_warning_title": "Warning",
        "msg_input_error_title": "Input Error",
        "help_panel_title": "Program Help",
        "help_panel_intro": "Goal: obtain a reliable K factor in Tab1, then process robust batches in Tab2.",
        "help_scroll_label": "Help text:",
        "help_copy_btn": "Copy Help Text",
        "help_copy_tooltip": "Copy full help text for sharing or records.",
        "hint_prefix": "Note",
        "session_error_title": "Session Error",
        "session_error_body": "Failed to read session:\n{err}",
        "session_loaded_title": "Session Loaded",
        # --- Tab1 labels ---
        "lbl_t1_std_file": "Standard (GC):",
        "lbl_t1_bg_file": "Background:",
        "lbl_t1_dark_file": "Dark image:",
        "lbl_t1_poni_file": "Geometry (.poni):",
        "lbl_i0_semantic": "I0 mode:",
        "cb_solid_angle": "SolidAngle correction",
        # --- Tab1 hints ---
        "hint_t1_files": "Standard recommended: Glassy Carbon (GC); BG/Dark/poni must share the same geometry and energy.",
        "hint_t1_phys": "Time(s)=exposure; I0=incident monitor; T=transmission(0–1). Normalisation follows selected I0 mode.",
        # --- Tab1 tooltips ---
        "tip_t1_guide": "Follow steps 1–5 to avoid missing key parameters.",
        "tip_t1_std_entry": "Standard sample 2D image for absolute calibration (GC recommended).",
        "tip_t1_std_btn": "Browse to select standard file.",
        "tip_t1_bg_entry": "Empty-cell / air / background 2D image for subtraction.",
        "tip_t1_bg_btn": "Browse to select background image.",
        "tip_t1_bg_multi": "Multi-select BG images & average (normalised); for capillary blanks / repeats.",
        "tip_t1_dark_entry": "Detector dark-current / electronic noise image.",
        "tip_t1_dark_btn": "Browse to select dark image.",
        "tip_t1_poni_entry": "pyFAI geometry file; controls q conversion accuracy.",
        "tip_t1_poni_btn": "Browse to select .poni file.",
        "tip_t1_std_exp": "Standard exposure time (s).",
        "tip_t1_std_i0": "Standard I0 (monitor reading).",
        "tip_t1_std_t": "Standard transmission; should be in 0–1.",
        "tip_t1_std_thk": "Standard thickness (mm); for volume normalisation.",
        "tip_t1_bg_exp": "Background exposure time (s).",
        "tip_t1_bg_i0": "Background I0 (monitor reading).",
        "tip_t1_bg_t": "Background transmission.",
        "tip_t1_norm_mode": "rate: I0 is count rate; integrated: I0 is integrated counts.",
        "tip_t1_norm_hint": "Choose according to beamline output. Wrong choice adds exposure-related systematic error.",
        "tip_t1_solid_angle": "Shared by Tab1 calibration & Tab2 batch. Must be consistent or K is invalid.",
        "tip_t1_calibrate": "Run 2D BG subtraction + 1D integration + NIST matching; writes K factor.",
        "tip_t1_history": "View historical K factor trend to monitor instrument drift.",
        "tip_t1_report": "Displays calibration key metrics: K, valid points, Q overlap range and dispersion.",
        "tip_t1_plot": "If the blue line tracks the red dots, K calibration quality is good.",
        # --- Tab2 labels ---
        "lf_t2_global": "1. Global Settings",
        "lbl_t2_k_factor": "K factor:",
        "lbl_t2_bg_file": "Background:",
        "lbl_t2_i0_semantic": "I0 mode:",
        "lf_t2_thickness": "2. Thickness Strategy",
        "rb_t2_auto_thk": "Auto thickness (d = −ln(T)/μ)",
        "lbl_t2_mu": " μ(cm⁻¹):",
        "btn_t2_mu_est": "μ est.",
        "rb_t2_fix_thk": "Fixed thickness (mm):",
        "lf_t2_integration": "3. Integration Modes (post BG subtraction)",
        "cb_t2_full_ring": "I-Q full ring",
        "cb_t2_sector": "I-Q sector",
        "btn_t2_iq_preview": "Preview I-Q",
        "lbl_t2_multi_sector": " Multi-sector:",
        "lbl_t2_sector_example": " e.g. -25~25;45~65",
        "cb_t2_sec_save_each": "Save sectors separately",
        "cb_t2_sec_save_sum": "Save merged sector",
        "cb_t2_texture": "I-chi texture",
        "btn_t2_chi_preview": "Preview I-chi",
        "lf_t2_correction": "4. Correction Parameters",
        "cb_t2_solid_angle": "Apply Solid Angle correction",
        "lbl_t2_error_model": "Error model:",
        "lbl_t2_mask": "Mask file:",
        "lbl_t2_flat": "Flat file:",
        "lf_t2_execution": "5. Reference Matching & Execution",
        "rb_t2_ref_fixed": "Fixed BG/Dark",
        "rb_t2_ref_auto": "Auto-match BG/Dark",
        "btn_t2_bg_lib": "BG Library",
        "btn_t2_dark_lib": "Dark Library",
        "btn_t2_clear_lib": "Clear Lib",
        "lbl_t2_workers": "Workers:",
        "cb_t2_resume": "Resume (skip existing output)",
        "cb_t2_overwrite": "Force overwrite",
        "cb_t2_strict": "Strict instrument consistency",
        "lbl_t2_tolerance": "Tolerance(%):",
        "lbl_t2_outdir": "Output dir:",
        # --- Tab2 hints ---
        "hint_t2_global": "K from Tab1. I0 mode selects normalisation formula; BG path for quick confirmation.",
        "hint_t2_thickness": "Auto: d=−ln(T)/μ ; Fixed: all samples use same thickness (mm).",
        "hint_t2_integration": "Multi-select & output to different folders: full-ring / sector / texture run simultaneously.",
        "hint_t2_correction": "Recommend enabling solid angle. Optional mask / flat / polarisation & error model.",
        "hint_t2_execution": "Fix BG/Dark, or auto-match the closest BG/Dark by metadata.",
        "hint_t2_queue": "Add multiple files. Click 'Dry Check' first to verify headers & thickness.",
        # --- Tab2 tooltips ---
        "tip_t2_guide": "Pre-check before running batch significantly reduces mid-run failures.",
        "tip_t2_k_factor": "Absolute intensity scale factor. Must be > 0.",
        "tip_t2_bg_label": "Current background path (shared from Tab1).",
        "tip_t2_norm_mode": "Global: rate means I0 is count rate; integrated means I0 is integrated counts.",
        "tip_t2_norm_hint": "Affects normalisation factors in both calibration and batch.",
        "tip_t2_auto_thk": "Suitable when every sample has reliable transmission T.",
        "tip_t2_mu": "Linear attenuation coefficient μ, unit cm⁻¹, must be > 0.",
        "tip_t2_mu_est": "Estimate μ from alloy composition (30 keV empirical).",
        "tip_t2_fix_thk": "When transmission is unreliable or missing, use fixed thickness.",
        "tip_t2_fix_thk_val": "Uniform thickness for all samples, in mm.",
        "tip_t2_mu_label": "Larger μ → smaller thickness for same T.",
        "tip_t2_full": "Recommended for isotropic samples. Can be combined with other modes.",
        "tip_t2_sector": "Integrate a specified azimuthal sector, highlighting directional structure.",
        "tip_t2_sec_min": "Sector start angle (°). Supports wrap-around ±180° (e.g. 170 to −170).",
        "tip_t2_sec_max": "Sector end angle (°). Same as start (mod 360) is invalid.",
        "tip_t2_sec_preview": "Open 2D preview of I-Q integration region (sector or full ring).",
        "tip_t2_sec_multi": "Multi-sector list. '-25~25;45~65' or '-25,25 45,65'; empty = use single sector above.",
        "tip_t2_sec_each": "Each sector outputs to its own subfolder (sector_XX_*).",
        "tip_t2_sec_sum": "Merge all sectors by pixel weight into one I-Q and save separately.",
        "tip_t2_texture": "Output I vs azimuthal angle chi in a given q range. Runs alongside I-Q.",
        "tip_t2_qmin": "Texture analysis q minimum (Å⁻¹).",
        "tip_t2_qmax": "Texture analysis q maximum (Å⁻¹), must exceed q_min.",
        "tip_t2_chi_preview": "Open 2D preview of I-chi q-ring band range.",
        "tip_t2_solid_angle": "Must match Tab1 calibration. Mismatch will block batch.",
        "tip_t2_error_model": "azimuthal: azimuthal scatter; poisson: counting stats; none: no errors.",
        "tip_t2_polarization": "Polarisation factor, usually −1 to 1. 0 = unpolarised.",
        "tip_t2_mask": "Mask image: non-zero pixels are excluded.",
        "tip_t2_flat": "Flat-field correction image (optional).",
        "tip_t2_ref_fixed": "All samples use Tab1 BG/Dark.",
        "tip_t2_ref_auto": "Auto-select BG & Dark closest in exposure/I0/T/time.",
        "tip_t2_bg_lib": "Select background file library for auto-matching.",
        "tip_t2_dark_lib": "Select dark file library for auto-matching.",
        "tip_t2_clear_lib": "Clear BG/Dark libraries.",
        "tip_t2_workers": "Parallel threads; 1 = serial. Suggest 1–8.",
        "tip_t2_resume": "Skip existing output files; supports resume after interruption.",
        "tip_t2_overwrite": "Ignore existing output and recalculate.",
        "tip_t2_strict": "Check energy/wavelength/distance/pixel/size consistency; stop on mismatch.",
        "tip_t2_tolerance": "Consistency tolerance %, e.g. 0.5 means 0.5%.",
        "tip_t2_add": "Multi-select TIFF files.",
        "tip_t2_clear": "Clear queue; does not delete files on disk.",
        "tip_t2_check": "Batch-check each file's exp/mon/T and thickness availability.",
        "tip_t2_listbox": "Current sample queue.",
        "tip_t2_run": "Run batch. Single-file failure does not abort the batch.",
        "tip_t2_progress": "Batch processing progress.",
        "tip_t2_outdir": "Optional. Empty = output next to sample files.",
        "tip_t2_out_label": "Output files and batch_report.csv will be written here.",
        # --- Tab3 labels ---
        "lf_t3_global": "1. Global & Formula",
        "lbl_t3_k_factor": "K factor:",
        "lbl_t3_pipeline": "Pipeline:",
        "rb_t3_scaled": "Scale only",
        "rb_t3_raw": "Raw 1D full correction",
        "rb_t3_kd_formula": "Ext. 1D w/o thickness: I_abs = I_rel × K / d",
        "lbl_t3_thk": "Fixed thickness(mm):",
        "rb_t3_k_formula": "Ext. 1D w/ thickness: I_abs = I_rel × K",
        "lbl_t3_x_type": "X-axis type:",
        "lbl_t3_i0_semantic": "I0 mode:",
        "lf_t3_execution": "2. Execution Strategy",
        "cb_t3_resume": "Resume (skip existing output)",
        "cb_t3_overwrite": "Force overwrite",
        "lbl_t3_formats": "Supported: .dat .txt .chi .csv (need X & I columns; Error optional)",
        "lf_t3_raw_params": "3. Raw 1D Correction Params (raw pipeline)",
        "btn_t3_meta_from_batch": "Generate metadata from Tab2 report",
        "cb_t3_meta_thk": "Prefer thk_mm from metadata",
        "cb_t3_sync_bg": "Sync BG params with Tab1 global (bg_exp/bg_i0/bg_t)",
        "lbl_t3_sample_params": "Sample fixed params exp/i0/T:",
        "lbl_t3_bg_params": "BG fixed params exp/i0/T:",
        "lbl_t3_outdir": "Output dir:",
        # --- Tab3 hints ---
        "hint_t3_global": "K from Tab1. Choose pipeline, then formula. Raw pipeline uses exp/I0/T and BG1D/Dark1D.",
        "hint_t3_execution": "Recommend dry-check first. Resume to avoid redundant overwrites.",
        "hint_t3_raw": "Only active when pipeline = Raw 1D. Can use Tab2's batch_report.csv or metadata.csv directly.",
        "hint_t3_queue": "Click 'Dry Check' to verify column parsing for each file.",
        # --- Tab3 tooltips ---
        "tip_t3_guide": "For data already integrated in pyFAI or other software; absolute calibration only.",
        "tip_t3_k": "Must be > 0. Uses latest Tab1 calibration value.",
        "tip_t3_scaled": "For external 1D already BG-subtracted & normalised; just apply absolute scale.",
        "tip_t3_raw": "For external 1D with raw integrated intensity; full 1D-level BG subtraction & normalisation here.",
        "tip_t3_kd": "For external integrated result still in relative intensity (not divided by thickness).",
        "tip_t3_thk": "Only used in K/d mode. Unit: mm.",
        "tip_t3_k_only": "For external integrated result already divided by thickness.",
        "tip_t3_x_mode": "'auto' infers Q_Å⁻¹ or Chi_deg from column names / suffix.",
        "tip_t3_resume": "Skip if output exists; for resuming large batches.",
        "tip_t3_overwrite": "Ignore existing results and recalculate.",
        "tip_t3_meta": "Optional. Supports metadata.csv or Tab2's batch_report.csv.",
        "tip_t3_bg1d": "Required (raw pipeline). BG 1D integrated the same way as the sample.",
        "tip_t3_dark1d": "Optional. Not supplied → treated as zero.",
        "tip_t3_meta_from_batch": "One-click: generate Tab3 metadata.csv from Tab2 batch_report.csv; auto-fill path.",
        "tip_t3_meta_thk": "If enabled and sample's metadata has thk_mm, overrides fixed thickness.",
        "tip_t3_sync_bg": "When enabled, Tab3 BG params auto-update from Tab1/global, avoiding stale values.",
        "tip_t3_add": "Multi-select external integration result files.",
        "tip_t3_clear": "Clear queue only; does not delete files on disk.",
        "tip_t3_check": "Check column recognition, point count, and X-axis type inference.",
        "tip_t3_listbox": "Current external 1D file list for conversion.",
        "tip_t3_run": "Batch-convert external 1D relative intensity to absolute using chosen formula.",
        "tip_t3_progress": "External 1D batch progress.",
        "tip_t3_outdir": "Optional. Empty = output next to first input file.",
        # --- Window titles ---
        "title_t3_dryrun": "External 1D Dry Check Results",
        "title_k_history": "K Factor History Trend",
        "title_t2_dryrun": "Batch Dry Check Results",
        "title_iq_preview": "I-Q 2D Preview – {name}",
        "title_ichi_preview": "I-chi 2D Preview – {name}",
        "title_mu_tool": "Universal μ Calculator (any energy)",
        # --- Standard selector ---
        "lbl_t1_std_type": "Standard:",
        "opt_std_srm3600": "NIST SRM 3600 (GC)",
        "opt_std_water": "Water (H\u2082O)",
        "opt_std_lupolen": "Lupolen (user curve)",
        "opt_std_custom": "Custom (user file)",
        "lbl_t1_water_temp": "Water T (°C):",
        "lbl_t1_std_ref_file": "Ref. curve file:",
        "hint_t1_std_water": "Water: q-independent, dΣ/dΩ = 0.01632 cm\u207b\xb9 at 20 \u00b0C (Orthaber et al. 2000)",
        "hint_t1_std_lupolen": "Lupolen: batch-dependent; load your beamline calibration curve.",
        # --- Buffer subtraction ---
        "lf_t3_buffer": "Buffer / Solvent Subtraction",
        "cb_t3_buffer_enable": "Enable buffer subtraction",
        "lbl_t3_buffer_file": "Buffer 1D file:",
        "lbl_t3_alpha": "\u03b1 (scale):",
        "lbl_t3_buffer_status": "(not loaded)",
        "lbl_t2_alpha": "BG \u03b1-scale:",
        "cb_t2_buffer_enable": "Enable BG \u03b1-scaling",
        # --- Output format ---
        "lbl_output_format": "Output format:",
        "opt_fmt_tsv": "TSV (tab-separated)",
        "opt_fmt_csv": "CSV (comma-separated)",
        "opt_fmt_cansas_xml": "canSAS 1D XML",
        "opt_fmt_nxcansas_h5": "NXcanSAS HDF5",
        # --- Mu tool new keys ---
        "lbl_mu_energy": "Energy (keV):",
        "lbl_mu_energy_or_wl": "or wavelength (Å):",
        "lbl_mu_preset": "Preset material:",
        "lbl_mu_custom_comp": "Custom (El:wt%, ...)",
        "lbl_mu_result_murho": "\u03bc/\u03c1 (cm\xb2/g):",
        "lbl_mu_result_mu": "\u03bc_linear (cm\u207b\xb9):",
        "btn_mu_add_row": "+ Element",
        "btn_mu_del_row": "- Element",
        "lbl_mu_contrib": "Element contributions",
        # --- Messagebox bodies ---
        "msg_meta_gen_title": "Metadata Generated",
        "msg_batch_done_title": "Batch Completed",
        "msg_k_history_empty": "No K history yet; run calibration first.",
        "msg_k_history_file_empty": "History file is empty.",
        "msg_k_history_read_error": "Failed to read history: {e}",
        # --- Dry-run panel labels ---
        "pre_k_factor": "K factor:",
        "pre_pipeline": "Pipeline:",
        "pre_corr_mode": "Correction mode:",
        "pre_fixed_thk": "Fixed thickness(mm):",
        "pre_x_mode": "X-axis mode:",
        "pre_i0_semantic": "I0 mode:",
        "pre_warning_header": "[Dry-Check Warnings]",
        "pre_pass_t3": "[Dry-Check Passed] No obvious issues with parameters.",
        "pre_i0_norm": "I0 normalisation mode:",
        "pre_integ_mode": "Integration mode:",
        "pre_integ_none": "None",
        "pre_sector_output": "Sector output:",
        "pre_sector_list": "Sector list:",
        "pre_ref_mode": "Reference mode:",
        "pre_error_model": "Error model:",
        "pre_workers": "Workers:",
        "pre_pass_t2": "[Dry-Check Passed] No obvious configuration issues.",
        # --- Status / health labels ---
        "status_ok": "OK",
        "status_fail": "FAIL",
        "status_no_match": "No match",
        "status_match_fail": "Match failed",
        # --- Lib info ---
        "var_bg_lib": "BG lib: {n}",
        "var_dark_lib": "Dark lib: {n}",
        # --- Mu tool ---
        "lbl_mu_wt_pct": "Wt% fraction",
        "lbl_mu_density": "Density ρ (g/cm³):",
        "btn_mu_apply": "Apply to batch",
        # --- File row labels (Tab3) ---
        "lbl_t3_bg1d_file": "BG 1D file:",
        "lbl_t3_dark1d_file": "Dark 1D file:",
        # --- Report messages ---
        "rpt_start_calib": "Start calibration (robust mode)...",
        "rpt_i0_norm_mode": "I0 normalisation mode: {mode} (norm={formula})",
        "rpt_solid_angle": "SolidAngle correction: {state}",
        "rpt_calib_ok": "Calibration succeeded (robust estimate)",
        # --- Ext 1D done messagebox ---
        "msg_ext_done_body": "External 1D absolute calibration completed.\nSuccess: {ok}\nSkipped: {skip}\nFailed: {fail}\nOutput dir: {out_dir}\nReport: {report}\nMeta: {meta}",
        # --- Dry-run warnings (Tab3) ---
        "warn_k_le_zero": "K factor ≤ 0.",
        "warn_kd_thk_le_zero": "K/d mode: fixed thickness must be > 0 mm.",
        "warn_meta_read_fail": "metadata CSV read failed: {e}",
        "warn_raw_no_meta": "Raw pipeline: no metadata CSV; fixed sample params will be used for all.",
        "warn_raw_no_bg1d": "Raw pipeline: BG 1D file is missing.",
        "warn_bg1d_read_fail": "BG 1D read failed: {e}",
        "warn_dark1d_read_fail": "Dark 1D read failed: {e}",
        "warn_bg_norm_invalid": "BG normalisation factor ≤ 0; check BG exp/i0/T.",
        # --- Dry-run warnings (Tab2) ---
        "warn_no_integ_mode": "No integration mode selected (check at least one).",
        "warn_sector_no_output": "Sector mode: no output selected (save each / merge).",
        "warn_sector_angle_invalid": "Sector angle range invalid: {e}",
        "warn_texture_q_invalid": "Texture q range invalid: qmin must be < qmax.",
        "warn_auto_thk_mu": "Auto thickness mode: μ must be > 0.",
        "warn_fix_thk_le_zero": "Fixed thickness must be > 0 mm.",
        "warn_auto_bg_empty": "Auto-match mode: BG library is empty.",
        "warn_auto_dark_empty": "Auto-match mode: Dark library is empty.",
        "warn_inst_issues": "Instrument consistency found {n} issues (see details below).",
        "warn_bg_norm_mismatch": "BG_Norm vs sample Norm_s magnitude mismatch (BG/sample median={ratio:.3g}, BG_Norm={bg_norm:.6g}, SampleMed={med:.6g}).",
        # --- Dry-run ext 1D status/reason ---
        "reason_norm_invalid": "Sample normalisation factor invalid (exp/i0/T)",
        "reason_thk_invalid": "Thickness invalid (fixed thickness or metadata thk_mm)",
        # --- Ext 1D messagebox ---
        "msg_t3_queue_empty": "Queue is empty; please add external 1D files first.",
        # --- Preview info labels ---
        "info_iq_sector": "Sector mode({n}): {desc}",
        "info_iq_full": "Full ring (valid pixels)",
        "info_iq_title": "Tab2 I-Q Integration Preview",
        "info_ichi_title": "Tab2 I-chi (q-ring) Preview",
        "info_iq_line1": "Sample: {name} | Mode: {mode} | Coverage: {pct:.2f}%",
        "info_iq_line2": "Angle convention (pyFAI chi): 0° right, +90° down, -90° up, ±180° left.",
        "info_ichi_line1": "Sample: {name} | q range: [{qmin:.4g}, {qmax:.4g}] Å⁻¹ | Coverage: {pct:.2f}%",
        "info_ichi_line2": "q-map unit: {src} (corresponds to Tab2 radial_chi q selection).",
        # --- Mu tool messagebox ---
        "msg_mu_wt_warn": "Total wt% = {w_tot}",
        "msg_mu_fail": "μ estimation failed: {e}",
    },
    "zh": {
        "app_title": f"{APP_NAME} v{APP_VERSION}",
        "header_title": f"{APP_NAME}｜绝对强度校正",
        "theme_toggle": "🌓 切换深色/浅色模式",
        "lang_toggle_to_zh": "中文",
        "lang_toggle_to_en": "English",
        "tab1": "\U0001f4d0  1. K 因子标定",
        "tab2": "\U0001f4e6  2. 批处理",
        "tab3": "\U0001f4c8  3. 外部 1D \u2192 绝对强度",
        "tab4": "\u2753  4. 帮助",
        "t1_guide_title": "快速流程（新手）",
        "t1_guide_text": "① 选择标准样/本底/暗场/几何文件\n② 核对自动读取的 Time、I0、T\n③ 填写标准样厚度(mm)\n④ 点击运行标定，得到 K 因子\n⑤ 查看报告中的 Std Dev 与点数",
        "t1_files_title": "1. 标定文件（必须）",
        "t1_phys_title": "2. 物理参数（核心输入）",
        "t1_run_btn": "\u25b6  运行 K 因子标定",
        "t1_hist_btn": "K 历史",
        "t1_report_title": "分析报告（建议重点看 Std Dev）",
        "t1_plot_tip": "图示说明：黑虚线=净信号；蓝线=K 校正后；红圈=NIST 参考点",
        "t2_guide_title": "批处理工作流（推荐顺序）",
        "t2_guide_text": "① 先确认 K 因子和 BG/暗场/poni 已就绪\n② 选择厚度逻辑（自动/固定）\n③ 选择一个或多个积分模式（可同时勾选）\n④ 添加样品文件并点击预检查\n⑤ 启动批处理并查看 batch_report.csv",
        "t2_mid_title": "样品队列",
        "t2_add_btn": "添加文件",
        "t2_clear_btn": "清空队列",
        "t2_check_btn": "预检查",
        "t2_run_btn": "\u25b6  开始批处理",
        "t3_guide_title": "外部 1D 绝对强度校正流程",
        "t3_guide_text": "① 先在 Tab1 得到可信 K 因子\n② 选择流程：仅比例缩放 / 原始1D完整校正\n③ 导入外部1D文件（原始模式还需 BG1D/Dark1D 与参数）\n④ 选择校正公式（K/d 或 K）与 X 轴类型\n⑤ 先预检查，再批量输出绝对强度表格",
        "t3_mid_title": "外部 1D 文件队列",
        "t3_add_btn": "添加1D文件",
        "t3_clear_btn": "清空队列",
        "t3_check_btn": "预检查",
        "t3_run_btn": "\u25b6  开始外部 1D 绝对强度校正",
        "queue_files": "队列文件",
        "queue_dedup": "去重后",
        "out_auto_prefix": "输出目录将自动创建",
        "out_write_prefix": "输出目录将写入",
        "out_none_mode": "输出目录: 未选择积分模式",
        "msg_help_title": "帮助",
        "msg_help_copied": "帮助文本已复制到剪贴板。",
        "msg_preview_title": "预检查",
        "msg_ext_done_title": "外部1D校正完成",
        "msg_ext_error_title": "外部1D校正错误",
        "msg_calib_error_title": "标定错误",
        "msg_k_history_title": "K 历史",
        "msg_batch_error_title": "批处理错误",
        "msg_iq_preview_error_title": "I-Q 预览错误",
        "msg_ichi_preview_error_title": "I-chi 预览错误",
        "msg_warning_title": "警告",
        "msg_input_error_title": "输入错误",
        "help_panel_title": "程序帮助（新手版）",
        "help_panel_intro": "目标：先在 Tab1 得到可靠 K 因子，再在 Tab2 做稳健批处理。",
        "help_scroll_label": "帮助文本（可滚动）：",
        "help_copy_btn": "复制帮助文本",
        "help_copy_tooltip": "复制完整帮助内容，方便发给同事或存档。",
        "hint_prefix": "注释",
        "session_error_title": "会话错误",
        "session_error_body": "读取会话失败:\n{err}",
        "session_loaded_title": "会话已加载",
        # --- Tab1 labels ---
        "lbl_t1_std_file": "标准样 (GC):",
        "lbl_t1_bg_file": "背景图像:",
        "lbl_t1_dark_file": "暗场图像:",
        "lbl_t1_poni_file": "几何文件 (.poni):",
        "lbl_i0_semantic": "I0 语义:",
        "cb_solid_angle": "SolidAngle修正",
        # --- Tab1 hints ---
        "hint_t1_files": "标准样建议用玻璃碳（GC）；背景/暗场/poni 应与样品保持同一实验几何与能量。",
        "hint_t1_phys": "Time(s)=曝光时间；I0=入射强度监测值；T=透过率(0~1)。归一化按下方 I0 语义选择公式。",
        # --- Tab1 tooltips ---
        "tip_t1_guide": "按 1~5 步执行，基本不会漏关键参数。",
        "tip_t1_std_entry": "用于绝对强度标定的标准样二维图像（推荐 GC）。",
        "tip_t1_std_btn": "点击选择标准样文件。",
        "tip_t1_bg_entry": "空样品/空气或本底散射图像，用于 2D 本底扣除。",
        "tip_t1_bg_btn": "点击选择背景图像。",
        "tip_t1_bg_multi": "多选背景图并合并扣除（归一化后平均），适用于空毛细管/空白重复。",
        "tip_t1_dark_entry": "探测器暗电流/本底噪声图像。",
        "tip_t1_dark_btn": "点击选择暗场图像。",
        "tip_t1_poni_entry": "pyFAI 几何标定文件，决定 q 转换精度。",
        "tip_t1_poni_btn": "点击选择 .poni 文件。",
        "tip_t1_std_exp": "标准样曝光时间（秒）。",
        "tip_t1_std_i0": "标准样 I0（监测器读数）。",
        "tip_t1_std_t": "标准样透过率，建议在 0~1 之间。",
        "tip_t1_std_thk": "标准样厚度（mm），用于体积归一化。",
        "tip_t1_bg_exp": "背景图曝光时间（秒）。",
        "tip_t1_bg_i0": "背景图 I0（监测器读数）。",
        "tip_t1_bg_t": "背景图透过率。",
        "tip_t1_norm_mode": "rate: I0 是每秒计数率；integrated: I0 是曝光积分计数。",
        "tip_t1_norm_hint": "请按线站实际输出选择。选错会引入曝光时间相关系统误差。",
        "tip_t1_solid_angle": "Tab1标定与Tab2批处理共用此设置。两者必须一致，否则 K 因子无效。",
        "tip_t1_calibrate": "执行 2D 扣背景 + 1D 积分 + NIST 匹配，自动写入 K 因子。",
        "tip_t1_history": "查看历史 K 因子趋势，监控仪器漂移。",
        "tip_t1_report": "会显示标定关键指标：K、有效点数、Q 重叠区间和离散度。",
        "tip_t1_plot": "若蓝线与红点趋势一致，通常说明 K 标定质量较好。",
        # --- Tab2 labels ---
        "lf_t2_global": "1. 全局配置",
        "lbl_t2_k_factor": "K 因子:",
        "lbl_t2_bg_file": "背景文件:",
        "lbl_t2_i0_semantic": "I0 语义:",
        "lf_t2_thickness": "2. 厚度策略",
        "rb_t2_auto_thk": "自动厚度 (d = -ln(T)/μ)",
        "lbl_t2_mu": " μ(cm⁻¹):",
        "btn_t2_mu_est": "μ估算",
        "rb_t2_fix_thk": "固定厚度 (mm):",
        "lf_t2_integration": "3. 积分模式（2D 扣背景后）",
        "cb_t2_full_ring": "I-Q 全环",
        "cb_t2_sector": "I-Q 扇区",
        "btn_t2_iq_preview": "预览I-Q",
        "lbl_t2_multi_sector": " 多扇区:",
        "lbl_t2_sector_example": " 例:-25~25;45~65",
        "cb_t2_sec_save_each": "分扇区分别保存",
        "cb_t2_sec_save_sum": "扇区合并保存",
        "cb_t2_texture": "I-chi 织构",
        "btn_t2_chi_preview": "预览I-chi",
        "lf_t2_correction": "4. 修正参数",
        "cb_t2_solid_angle": "应用 Solid Angle 修正",
        "lbl_t2_error_model": "误差模型:",
        "lbl_t2_mask": "Mask 文件:",
        "lbl_t2_flat": "Flat 文件:",
        "lf_t2_execution": "5. 参考匹配与执行",
        "rb_t2_ref_fixed": "固定 BG/Dark",
        "rb_t2_ref_auto": "自动匹配 BG/Dark",
        "btn_t2_bg_lib": "选择 BG 库",
        "btn_t2_dark_lib": "选择 Dark 库",
        "btn_t2_clear_lib": "清空库",
        "lbl_t2_workers": "并行线程:",
        "cb_t2_resume": "断点续跑(跳过已存在输出)",
        "cb_t2_overwrite": "强制覆盖输出",
        "cb_t2_strict": "严格仪器一致性校验",
        "lbl_t2_tolerance": "阈值(%):",
        "lbl_t2_outdir": "输出根目录:",
        # --- Tab2 hints ---
        "hint_t2_global": "K 因子来自 Tab1 标定结果。I0 语义决定归一化公式；BG 路径仅用于快速确认。",
        "hint_t2_thickness": "自动模式: d=-ln(T)/mu；固定模式: 所有样品使用同一厚度(mm)。",
        "hint_t2_integration": "可多选并一次性输出到不同文件夹：全环/扇区/织构可同时运行。",
        "hint_t2_correction": "建议开启 solid angle。可选 mask/flat/polarization 与误差模型。",
        "hint_t2_execution": "可固定 BG/Dark，或按元数据自动匹配最接近的 BG/Dark。",
        "hint_t2_queue": '可一次添加多个文件。建议先点"预检查"，确认头信息与厚度计算是否正常。',
        # --- Tab2 tooltips ---
        "tip_t2_guide": "先预检查再正式跑批，可显著减少中途失败。",
        "tip_t2_k_factor": "绝对强度比例因子。必须大于 0。",
        "tip_t2_bg_label": "当前启用的背景图路径（由 Tab1 共享）。",
        "tip_t2_norm_mode": "全局生效：rate 表示 I0 为计数率；integrated 表示 I0 为积分计数。",
        "tip_t2_norm_hint": "该设置会影响标定与批处理的所有归一化因子。",
        "tip_t2_auto_thk": "适合每个样品都具有可靠透过率 T 的情况。",
        "tip_t2_mu": "线性衰减系数 mu，单位 cm^-1，必须大于 0。",
        "tip_t2_mu_est": "按合金成分估算 mu（30 keV 经验）。",
        "tip_t2_fix_thk": "透过率不稳定或缺失时，建议改为固定厚度。",
        "tip_t2_fix_thk_val": "所有样品统一厚度值，单位 mm。",
        "tip_t2_mu_label": "mu 越大，按同样 T 算出的厚度越小。",
        "tip_t2_full": "对各向同性样品优先推荐。可与其他模式同时勾选。",
        "tip_t2_sector": "仅对指定方位角扇区积分，突出方向性结构。可多选并行输出。",
        "tip_t2_sec_min": "扇区起始角（度）。支持跨 ±180°（例如 170 到 -170）。",
        "tip_t2_sec_max": "扇区结束角（度）。与起始角相同（模360）无效。",
        "tip_t2_sec_preview": "弹出2D窗口预览 I-Q 积分区域（扇区或全环），用于确认选区。",
        "tip_t2_sec_multi": "多扇区列表。支持 `-25~25;45~65`、`-25,25 45,65` 等格式；留空时使用上方单扇区。",
        "tip_t2_sec_each": "每个扇区输出到独立子文件夹（sector_XX_*）。",
        "tip_t2_sec_sum": "将所有扇区按像素权重合并成一条 I-Q，并单独输出。",
        "tip_t2_texture": "在给定 q 范围内输出 I 随方位角 chi 的分布。可与 I-Q 同时输出。",
        "tip_t2_qmin": "织构分析 q 最小值（A^-1）。",
        "tip_t2_qmax": "织构分析 q 最大值（A^-1），需大于 q_min。",
        "tip_t2_chi_preview": "弹出2D窗口预览 I-chi 使用的 q 环带范围。",
        "tip_t2_solid_angle": "必须与 Tab1 标定时保持一致。若不一致程序会阻断批处理。",
        "tip_t2_error_model": "azimuthal: 方位离散；poisson: 计数统计；none: 不计算误差。",
        "tip_t2_polarization": "偏振因子，通常在 -1 到 1。0 表示不偏振。",
        "tip_t2_mask": "掩膜图：非零像素视为无效区域。",
        "tip_t2_flat": "平场校正图（可选）。",
        "tip_t2_ref_fixed": "全批次统一使用 Tab1 指定的 BG/Dark。",
        "tip_t2_ref_auto": "按曝光/I0/T/时间与样品最接近原则自动选 BG 和 Dark。",
        "tip_t2_bg_lib": "选择可供自动匹配的背景文件集合。",
        "tip_t2_dark_lib": "选择可供自动匹配的暗场文件集合。",
        "tip_t2_clear_lib": "清空 BG/Dark 库。",
        "tip_t2_workers": "并行线程数，1 表示串行。建议 1~8。",
        "tip_t2_resume": "已存在输出文件时自动跳过，支持中断后续跑。",
        "tip_t2_overwrite": "忽略已存在输出并重新计算。",
        "tip_t2_strict": "检查能量/波长/距离/像素/尺寸一致性，不一致则停止。",
        "tip_t2_tolerance": "一致性阈值百分比，例如 0.5 表示 0.5%。",
        "tip_t2_add": "支持多选 TIFF 文件。",
        "tip_t2_clear": "清空队列，不会删除磁盘文件。",
        "tip_t2_check": "批量检查每个文件的 exp/mon/T 和厚度可用性。",
        "tip_t2_listbox": "显示当前待处理样品列表。",
        "tip_t2_run": "执行批处理。单文件失败不会中断整批。",
        "tip_t2_progress": "显示批处理进度。",
        "tip_t2_outdir": "可选。不填时默认输出到样品所在目录。",
        "tip_t2_out_label": "输出文件与 batch_report.csv 会写入该目录。",
        # --- Tab3 labels ---
        "lf_t3_global": "1. 全局与公式",
        "lbl_t3_k_factor": "K 因子:",
        "lbl_t3_pipeline": "流程:",
        "rb_t3_scaled": "仅比例缩放",
        "rb_t3_raw": "原始1D完整校正",
        "rb_t3_kd_formula": "外部1D未除厚度: I_abs = I_rel * K / d",
        "lbl_t3_thk": "固定厚度(mm):",
        "rb_t3_k_formula": "外部1D已除厚度: I_abs = I_rel * K",
        "lbl_t3_x_type": "X轴类型:",
        "lbl_t3_i0_semantic": "I0语义:",
        "lf_t3_execution": "2. 执行策略",
        "cb_t3_resume": "断点续跑(跳过已存在输出)",
        "cb_t3_overwrite": "强制覆盖输出",
        "lbl_t3_formats": "支持格式: .dat .txt .chi .csv（列至少包含 X 与 I；Error 可选）",
        "lf_t3_raw_params": "3. 原始1D校正参数（raw流程）",
        "btn_t3_meta_from_batch": "由 Tab2 报告生成 metadata",
        "cb_t3_meta_thk": "优先使用 metadata 中的 thk_mm",
        "cb_t3_sync_bg": "BG参数跟随 Tab1 全局(bg_exp/bg_i0/bg_t)",
        "lbl_t3_sample_params": "样品固定参数 exp/i0/T:",
        "lbl_t3_bg_params": "BG固定参数 exp/i0/T:",
        "lbl_t3_outdir": "输出根目录:",
        # --- Tab3 hints ---
        "hint_t3_global": "K 来自 Tab1。先选流程，再选公式。原始1D流程会用到 exp/I0/T 与 BG1D/Dark1D。",
        "hint_t3_execution": "建议先预检查。可断点续跑，避免重复覆盖。",
        "hint_t3_raw": "仅当流程=原始1D完整校正时生效。可直接使用 Tab2 的 batch_report.csv 或 metadata.csv。",
        "hint_t3_queue": '建议先点"预检查"确认每个文件的列解析情况。',
        # --- Tab3 tooltips ---
        "tip_t3_guide": "适合你在 pyFAI/其他软件完成积分后，仅在本程序做绝对标定。",
        "tip_t3_k": "必须 >0。优先使用 Tab1 最新标定值。",
        "tip_t3_scaled": "适合外部1D已做过本底/归一化，仅需绝对强度映射。",
        "tip_t3_raw": "适合外部1D是原始积分强度，需要在本页完成1D级扣本底和归一化。",
        "tip_t3_kd": "适用于外部积分结果仍是相对强度（尚未除厚度）。",
        "tip_t3_thk": "仅在 K/d 模式下使用。单位 mm。",
        "tip_t3_k_only": "适用于外部积分结果已经做了厚度归一化。",
        "tip_t3_x_mode": "auto 会根据列名/后缀推断 Q_A^-1 或 Chi_deg。",
        "tip_t3_resume": "输出存在时跳过，适合大批量中断后继续。",
        "tip_t3_overwrite": "忽略已存在结果并重算。",
        "tip_t3_meta": "可选。支持 metadata.csv，或直接选择 Tab2 的 batch_report.csv。",
        "tip_t3_bg1d": "必填（raw流程）。与样品同积分方式得到的 BG 1D。",
        "tip_t3_dark1d": "可选。未提供则按 0 处理。",
        "tip_t3_meta_from_batch": "从 Tab2 的 batch_report.csv 一键生成 Tab3 可用 metadata.csv，并自动回填路径。",
        "tip_t3_meta_thk": "开启后，若某样品 metadata 含 thk_mm，则覆盖固定厚度。",
        "tip_t3_sync_bg": "开启后 Tab3 的 BG 参数会随 Tab1/全局变化自动更新，避免陈旧值。",
        "tip_t3_add": "支持多选外部积分结果文件。",
        "tip_t3_clear": "仅清空队列，不删除磁盘文件。",
        "tip_t3_check": "检查列识别、点数和坐标类型推断。",
        "tip_t3_listbox": "当前待转换的外部1D文件列表。",
        "tip_t3_run": "将外部1D相对强度按选定公式批量转换为绝对强度。",
        "tip_t3_progress": "显示外部1D批处理进度。",
        "tip_t3_outdir": "可选。不填时默认输出到首个输入文件所在目录。",
        # --- Window titles ---
        "title_t3_dryrun": "外部1D预检查结果",
        "title_k_history": "K 因子历史趋势",
        "title_t2_dryrun": "批处理预检查结果",
        "title_iq_preview": "I-Q 2D预览 - {name}",
        "title_ichi_preview": "I-chi 2D预览 - {name}",
        "title_mu_tool": "通用 μ 计算器（任意能量）",
        # --- 标准样选择 ---
        "lbl_t1_std_type": "标准样品:",
        "opt_std_srm3600": "NIST SRM 3600 (GC)",
        "opt_std_water": "纯水 (H\u2082O)",
        "opt_std_lupolen": "Lupolen (用户曲线)",
        "opt_std_custom": "自定义 (用户文件)",
        "lbl_t1_water_temp": "水温 (°C):",
        "lbl_t1_std_ref_file": "参考曲线文件:",
        "hint_t1_std_water": "水标准: q无关, dΣ/dΩ=0.01632 cm\u207b\xb9 (20 \u00b0C) (Orthaber et al. 2000)",
        "hint_t1_std_lupolen": "Lupolen: 批次相关; 请加载光束线标定曲线。",
        # --- 缓冲液扣除 ---
        "lf_t3_buffer": "缓冲液/溶剂扣除",
        "cb_t3_buffer_enable": "启用缓冲液扣除",
        "lbl_t3_buffer_file": "缓冲液1D文件:",
        "lbl_t3_alpha": "\u03b1 (缩放):",
        "lbl_t3_buffer_status": "(未加载)",
        "lbl_t2_alpha": "背景 \u03b1缩放:",
        "cb_t2_buffer_enable": "启用背景 \u03b1-缩放",
        # --- 输出格式 ---
        "lbl_output_format": "输出格式:",
        "opt_fmt_tsv": "TSV (制表符分隔)",
        "opt_fmt_csv": "CSV (逗号分隔)",
        "opt_fmt_cansas_xml": "canSAS 1D XML",
        "opt_fmt_nxcansas_h5": "NXcanSAS HDF5",
        # --- μ 计算器新键 ---
        "lbl_mu_energy": "能量 (keV):",
        "lbl_mu_energy_or_wl": "或波长 (Å):",
        "lbl_mu_preset": "预设材料:",
        "lbl_mu_custom_comp": "自定义 (El:wt%, ...)",
        "lbl_mu_result_murho": "\u03bc/\u03c1 (cm\xb2/g):",
        "lbl_mu_result_mu": "\u03bc_linear (cm\u207b\xb9):",
        "btn_mu_add_row": "+ 元素",
        "btn_mu_del_row": "- 元素",
        "lbl_mu_contrib": "各元素贡献",
        # --- Messagebox bodies ---
        "msg_meta_gen_title": "metadata 已生成",
        "msg_batch_done_title": "批处理完成",
        "msg_k_history_empty": "尚无 K 历史记录，请先运行一次标定。",
        "msg_k_history_file_empty": "历史文件为空。",
        "msg_k_history_read_error": "读取历史失败: {e}",
        # --- Dry-run panel labels ---
        "pre_k_factor": "K 因子:",
        "pre_pipeline": "流程:",
        "pre_corr_mode": "校正模式:",
        "pre_fixed_thk": "固定厚度(mm):",
        "pre_x_mode": "X轴模式:",
        "pre_i0_semantic": "I0语义:",
        "pre_warning_header": "[预检查警告]",
        "pre_pass_t3": "[预检查通过] 参数未见明显问题。",
        "pre_i0_norm": "I0 归一化模式:",
        "pre_integ_mode": "积分模式:",
        "pre_integ_none": "无",
        "pre_sector_output": "扇区输出:",
        "pre_sector_list": "扇区列表:",
        "pre_ref_mode": "参考模式:",
        "pre_error_model": "误差模型:",
        "pre_workers": "并行线程:",
        "pre_pass_t2": "[预检查通过] 未发现明显配置问题。",
        # --- Status / health labels ---
        "status_ok": "正常",
        "status_fail": "失败",
        "status_no_match": "无匹配",
        "status_match_fail": "匹配失败",
        # --- Lib info ---
        "var_bg_lib": "BG库: {n}",
        "var_dark_lib": "Dark库: {n}",
        # --- Mu tool ---
        "lbl_mu_wt_pct": "质量分数 (wt%)",
        "lbl_mu_density": "密度 rho (g/cm3):",
        "btn_mu_apply": "应用到批处理",
        # --- File row labels (Tab3) ---
        "lbl_t3_bg1d_file": "BG 1D 文件:",
        "lbl_t3_dark1d_file": "Dark 1D 文件:",
        # --- Report messages ---
        "rpt_start_calib": "开始标定（稳健模式）...",
        "rpt_i0_norm_mode": "I0 归一化模式: {mode} (norm={formula})",
        "rpt_solid_angle": "SolidAngle 修正: {state}",
        "rpt_calib_ok": "标定成功（稳健估计）",
        # --- Ext 1D done messagebox ---
        "msg_ext_done_body": "外部1D绝对强度校正完成。\n成功: {ok}\n跳过: {skip}\n失败: {fail}\n输出目录: {out_dir}\n报告: {report}\n元数据: {meta}",
        # --- Dry-run warnings (Tab3) ---
        "warn_k_le_zero": "K 因子 <= 0。",
        "warn_kd_thk_le_zero": "K/d 模式下固定厚度必须 > 0 mm。",
        "warn_meta_read_fail": "metadata CSV 读取失败: {e}",
        "warn_raw_no_meta": "raw流程未提供 metadata CSV，将全部使用固定样品参数。",
        "warn_raw_no_bg1d": "raw流程缺少 BG 1D 文件。",
        "warn_bg1d_read_fail": "BG 1D 读取失败: {e}",
        "warn_dark1d_read_fail": "Dark 1D 读取失败: {e}",
        "warn_bg_norm_invalid": "BG 归一化因子 <=0，请检查 BG exp/i0/T。",
        # --- Dry-run warnings (Tab2) ---
        "warn_no_integ_mode": "未选择积分模式（至少勾选一种）。",
        "warn_sector_no_output": "扇区模式未勾选任何输出（分别保存/合并保存）。",
        "warn_sector_angle_invalid": "扇区角度范围无效：{e}",
        "warn_texture_q_invalid": "织构 q 范围无效：qmin 必须 < qmax。",
        "warn_auto_thk_mu": "自动厚度模式下 mu 必须 > 0。",
        "warn_fix_thk_le_zero": "固定厚度必须 > 0 mm。",
        "warn_auto_bg_empty": "自动匹配模式下 BG 库为空。",
        "warn_auto_dark_empty": "自动匹配模式下 Dark 库为空。",
        "warn_inst_issues": "仪器一致性发现 {n} 项问题（见下方详情）。",
        "warn_bg_norm_mismatch": "BG_Norm 与样品 Norm_s 量级差异过大 (BG/样品中位={ratio:.3g}, BG_Norm={bg_norm:.6g}, SampleMed={med:.6g})。",
        # --- Dry-run ext 1D status/reason ---
        "reason_norm_invalid": "样品归一化因子无效（exp/i0/T）",
        "reason_thk_invalid": "厚度无效（固定厚度或metadata thk_mm）",
        # --- Ext 1D messagebox ---
        "msg_t3_queue_empty": "队列为空，请先添加外部1D文件。",
        # --- Preview info labels ---
        "info_iq_sector": "扇区模式({n}): {desc}",
        "info_iq_full": "全环 (有效像素)",
        "info_iq_title": "Tab2 I-Q 积分区域预览",
        "info_ichi_title": "Tab2 I-chi (q环带) 预览",
        "info_iq_line1": "样品: {name} | 模式: {mode} | 覆盖像素: {pct:.2f}%",
        "info_iq_line2": "角度定义（pyFAI chi）：0°向右，+90°向下，-90°向上，±180°向左。",
        "info_ichi_line1": "样品: {name} | q区间: [{qmin:.4g}, {qmax:.4g}] A^-1 | 覆盖像素: {pct:.2f}%",
        "info_ichi_line2": "q 映射单位: {src}（用于对应 Tab2 radial_chi 的 q 选区）。",
        # --- Mu tool messagebox ---
        "msg_mu_wt_warn": "总 wt% = {w_tot}",
        "msg_mu_fail": "μ 估算失败: {e}",
    },
}

try:
    from saxs_ui_kit import apply_ios_theme, promote_primary_buttons, toggle_theme, ToolTip
except Exception:
    # ---- sv_ttk Sun-Valley theme (lightweight Win11-style) ----
    try:
        import sv_ttk as _sv_ttk
    except ImportError:
        _sv_ttk = None

    def apply_ios_theme(root):
        if _sv_ttk is not None:
            _sv_ttk.set_theme("light")

    def promote_primary_buttons(root):
        return None  # sv_ttk handles Accent.TButton natively

    def toggle_theme(root):
        if _sv_ttk is not None:
            _sv_ttk.toggle_theme()
            # update native tk widgets after theme switch
            app = getattr(root, '_app_ref', None)
            if app is not None:
                app._sync_native_widget_colors()

    class ToolTip:
        """Minimal cross-platform tooltip for ttk / tk widgets."""
        _DELAY_MS = 450
        def __init__(self, widget, text):
            self.widget = widget
            self.text = text
            self._tw = None
            self._id_after = None
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress>", self._hide, add="+")

        def _schedule(self, event=None):
            self._hide()
            self._id_after = self.widget.after(self._DELAY_MS, self._show)

        def _show(self):
            if not self.text:
                return
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            # Adapt colours to current theme
            is_dark = (_sv_ttk is not None and _sv_ttk.get_theme() == "dark")
            bg = "#3a3a3a" if is_dark else "#ffffe1"
            fg = "#e0e0e0" if is_dark else "#1a1a1a"
            lbl = tk.Label(tw, text=self.text, justify="left",
                           background=bg, foreground=fg,
                           relief="solid", borderwidth=1,
                           font=("Segoe UI", 9), wraplength=360,
                           padx=6, pady=4)
            lbl.pack()
            self._tw = tw

        def _hide(self, event=None):
            if self._id_after:
                self.widget.after_cancel(self._id_after)
                self._id_after = None
            if self._tw:
                self._tw.destroy()
                self._tw = None

        def update_text(self, new_text):
            self.text = new_text

try:
    from saxs_core import load_session, session_geometry
except Exception:
    def load_session(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def session_geometry(session_payload):
        if not isinstance(session_payload, dict):
            return {}
        geom = session_payload.get("geometry", {})
        return geom if isinstance(geom, dict) else {}

try:
    import saxs_mpl_style
except Exception:
    class _SaxsMplStyleFallback:
        @staticmethod
        def apply_nature_style():
            return None

    saxs_mpl_style = _SaxsMplStyleFallback()

_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from saxsabs.core.calibration import estimate_k_factor_robust
except Exception:
    estimate_k_factor_robust = None

try:
    from saxsabs.constants import (
        NIST_SRM3600_DATA,
        STANDARD_REGISTRY,
        get_reference_data,
        water_dsdw,
    )
except Exception:
    NIST_SRM3600_DATA = np.array([
        [0.008, 35.0], [0.010, 34.2], [0.020, 30.8], [0.030, 28.8],
        [0.040, 27.5], [0.050, 26.8], [0.060, 26.3], [0.080, 25.4],
        [0.100, 23.6], [0.120, 20.8], [0.150, 15.8], [0.180, 10.9],
        [0.200, 8.4],  [0.220, 6.5],  [0.250, 4.2]
    ])
    STANDARD_REGISTRY = None
    get_reference_data = None
    water_dsdw = None

try:
    from saxsabs.core.mu_calculator import (
        calculate_mu,
        mu_rho_single,
        parse_composition_string,
        MATERIAL_PRESETS,
    )
except Exception:
    calculate_mu = None
    mu_rho_single = None
    parse_composition_string = None
    MATERIAL_PRESETS = None

try:
    from saxsabs.core.buffer_subtraction import subtract_buffer
except Exception:
    subtract_buffer = None

try:
    from saxsabs.core.execution_policy import parse_run_policy, should_skip_all_existing
except Exception:
    parse_run_policy = None

    def should_skip_all_existing(existing_flags, policy):
        if not existing_flags:
            return False
        resume_enabled = bool(getattr(policy, "resume_enabled", False))
        overwrite_existing = bool(getattr(policy, "overwrite_existing", False))
        if overwrite_existing:
            return False
        if not resume_enabled:
            return False
        return all(bool(x) for x in existing_flags)

try:
    from saxsabs.core.preflight import evaluate_preflight_gate
except Exception:
    evaluate_preflight_gate = None

try:
    from saxsabs.io.writers import write_cansas1d_xml, write_nxcansas_h5
except Exception:
    write_cansas1d_xml = None
    write_nxcansas_h5 = None

FLOAT_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
HC_KEV_A = 12.398419843320025  # E(keV) * lambda(A)
MONITOR_NORM_MODES = ("rate", "integrated")

class SAXSAbsWorkbenchApp:
    def __init__(self, root, language="en"):
        self.root = root
        self.language = (language or "en").strip().lower()
        if self.language not in SUPPORTED_LANGUAGES:
            self.language = "en"
        self.root.title(self.tr("app_title"))
        self.root.geometry("1280x900")
        self.root.minsize(1024, 700)
        
        # Apply Nature style globally
        saxs_mpl_style.apply_nature_style()
        
        self.set_style()
        self._tooltips = []
        
        # Top bar for theme toggle
        top_bar = ttk.Frame(self.root)
        top_bar.pack(fill="x", padx=16, pady=(12, 6))
        top_bar.columnconfigure(0, weight=1)
        self.lbl_header_title = ttk.Label(top_bar, text=self.tr("header_title"), style="Title.TLabel")
        self.lbl_header_title.grid(row=0, column=0, sticky="w")

        self.btn_theme = ttk.Button(top_bar, text=self.tr("theme_toggle"), command=lambda: toggle_theme(self.root))
        self.btn_theme.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.btn_lang = ttk.Button(top_bar, text=self._lang_button_text(), width=10, command=self.toggle_language)
        self.btn_lang.grid(row=0, column=2, sticky="e", padx=(8, 0))

        # Separator under top bar
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=12, pady=(0, 4))
        
        # === 全局共享状态 ===
        self.global_vars = {
            "k_factor": tk.DoubleVar(value=1.0),
            "poni_path": tk.StringVar(),
            "bg_path": tk.StringVar(),
            "dark_path": tk.StringVar(),
            "bg_exp": tk.DoubleVar(value=1.0),
            "bg_i0": tk.DoubleVar(value=1.0),
            "bg_t": tk.DoubleVar(value=1.0),
            "monitor_mode": tk.StringVar(value="rate"),
            "apply_solid_angle": tk.BooleanVar(value=True),
            "k_solid_angle": tk.StringVar(value="unknown"),
        }
        self.session_geometry_fallback = {}

        # === 布局 ===
        self.nb = ttk.Notebook(root)
        self.nb.pack(expand=1, fill="both", padx=8, pady=(0, 8))

        self.tab1 = ttk.Frame(self.nb)
        self.tab2 = ttk.Frame(self.nb)
        self.tab3 = ttk.Frame(self.nb)
        self.tab_help = ttk.Frame(self.nb)

        self.nb.add(self.tab1, text=self.tr("tab1"))
        self.nb.add(self.tab2, text=self.tr("tab2"))
        self.nb.add(self.tab3, text=self.tr("tab3"))
        self.nb.add(self.tab_help, text=self.tr("tab4"))

        # --- Status bar ---
        status_sep = ttk.Separator(self.root, orient="horizontal")
        status_sep.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="Ready")
        self._status_bar = ttk.Label(
            self.root, textvariable=self._status_var, style="Status.TLabel", anchor="w"
        )
        self._status_bar.pack(fill="x", side="bottom")

        self.init_tab1_k_calc()
        self.init_tab2_batch()
        self.init_tab3_external_1d()
        self.init_tab_help()
        promote_primary_buttons(self.root)

    def tr(self, key):
        lang_pack = I18N.get(self.language, I18N["en"])
        return lang_pack.get(key, key)

    def _lang_button_text(self):
        return self.tr("lang_toggle_to_zh") if self.language == "en" else self.tr("lang_toggle_to_en")

    def toggle_language(self):
        self.language = "zh" if self.language == "en" else "en"
        self.refresh_ui_language()

    def refresh_ui_language(self):
        self.root.title(self.tr("app_title"))
        if hasattr(self, "lbl_header_title"):
            self.lbl_header_title.configure(text=self.tr("header_title"))
        if hasattr(self, "btn_theme"):
            self.btn_theme.configure(text=self.tr("theme_toggle"))
        if hasattr(self, "btn_lang"):
            self.btn_lang.configure(text=self._lang_button_text())
        if hasattr(self, "nb"):
            self.nb.tab(self.tab1, text=self.tr("tab1"))
            self.nb.tab(self.tab2, text=self.tr("tab2"))
            self.nb.tab(self.tab3, text=self.tr("tab3"))
            self.nb.tab(self.tab_help, text=self.tr("tab4"))
        if hasattr(self, "_i18n_widgets"):
            for widget, key in self._i18n_widgets:
                try:
                    widget.configure(text=self.tr(key))
                except Exception:
                    pass
        if hasattr(self, "_i18n_tooltips"):
            for tt, key in self._i18n_tooltips:
                try:
                    tt.text = self.tr(key)
                except Exception:
                    pass
        if hasattr(self, "_i18n_hints"):
            for lbl, key in self._i18n_hints:
                try:
                    lbl.configure(text=f"{self.tr('hint_prefix')}: {self.tr(key)}")
                except Exception:
                    pass
        self.refresh_help_text()
        self.refresh_queue_status()
        self.refresh_external_1d_status()

    def _register_i18n_widget(self, widget, key):
        if not hasattr(self, "_i18n_widgets"):
            self._i18n_widgets = []
        self._i18n_widgets.append((widget, key))

    def _fmt_queue_info(self, total, uniq):
        if total == uniq:
            return f"{self.tr('queue_files')}: {uniq}"
        return f"{self.tr('queue_files')}: {total} ({self.tr('queue_dedup')} {uniq})"

    def split_path_list(self, raw):
        if raw is None:
            return []
        s = str(raw).strip()
        if not s:
            return []

        tokens = [t.strip().strip('"').strip("'") for t in re.split(r"[;\n\|]+", s) if t.strip()]
        if not tokens:
            tokens = [s]

        out = []
        seen = set()
        for t in tokens:
            p = str(Path(t))
            k = p.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(p)
        return out

    def build_composite_bg_net(self, bg_paths, d_dark, monitor_mode, fallback_triplet, ref_shape=None):
        nets = []
        norms = []
        used_paths = []
        dark = np.asarray(d_dark, dtype=np.float64)

        for bg_path in bg_paths:
            img = fabio.open(bg_path)
            d_bg = np.asarray(img.data, dtype=np.float64)
            self._assert_same_shape(d_bg, dark, "bg", "dark")
            if ref_shape is not None and tuple(d_bg.shape) != tuple(ref_shape):
                raise ValueError(f"BG 尺寸不匹配: {d_bg.shape} vs {ref_shape}")

            exp, mon, trans = self.parse_header(bg_path, header_dict=getattr(img, "header", {}))
            n = self.compute_norm_factor(exp, mon, trans, monitor_mode)
            if not np.isfinite(n) or n <= 0:
                n = self.compute_norm_factor(fallback_triplet[0], fallback_triplet[1], fallback_triplet[2], monitor_mode)
            if not np.isfinite(n) or n <= 0:
                raise ValueError(f"背景归一化因子无效: {Path(bg_path).name}")

            nets.append((d_bg - dark) / float(n))
            norms.append(float(n))
            used_paths.append(str(bg_path))

        if not nets:
            raise ValueError("未提供可用背景图像。")

        bg_net = np.nanmean(np.stack(nets, axis=0), axis=0)
        return bg_net, norms, used_paths

    def _localize_runtime_text(self, msg):
        if self.language != "en":
            return msg
        text = str(msg)
        repl = {
            # --- Report / log prefixes ---
            "开始标定（稳健模式）": "Start calibration (robust mode)",
            "标定成功（稳健估计）": "Calibration succeeded (robust estimate)",
            "批处理错误": "Batch processing error",
            "外部1D绝对强度校正完成": "External 1D absolute calibration completed",
            "批处理完成": "Batch processing completed",
            # --- Status values ---
            "成功": "Success",
            "失败": "Failed",
            "已跳过": "Skipped",
            "部分成功": "Partially successful",
            "正常": "OK",
            "无匹配": "No match",
            "匹配失败": "Match failed",
            # --- Queue / output ---
            "输出目录将自动创建": "Output directories will be created",
            "输出目录将写入": "Output directories under",
            "队列文件": "Queue files",
            "去重后": "deduplicated",
            # --- Log prefixes ---
            "配置": "Config",
            "提示": "Hint",
            "警告": "Warning",
            "错误": "Error",
            "跳过": "Skip",
            # --- Log messages ---
            "所有输出已存在": "all outputs already exist",
            "所有模式输出已存在": "all mode outputs already exist",
            "无输出": "no output",
            "净信号全部为无效值，无法输出": "Net signal all invalid; cannot output",
            # --- Exception / validation messages ---
            "文件不完整：请先选择标准样、背景、暗场和 poni": "Incomplete files: select standard, BG, dark, and poni first",
            "标准样厚度必须 > 0 mm": "Standard thickness must be > 0 mm",
            "队列为空：请先添加外部1D文件": "Queue is empty: add external 1D files first",
            "K 因子无效（必须 > 0）": "K factor invalid (must be > 0)",
            "未知流程模式": "Unknown pipeline mode",
            "未知校正模式": "Unknown correction mode",
            "K/d 模式下固定厚度必须 > 0 mm": "K/d mode: fixed thickness must be > 0 mm",
            "raw流程必须提供 BG 1D 文件": "Raw pipeline: BG 1D file required",
            "raw流程下 BG 归一化因子无效，请检查 BG exp/i0/T": "Raw pipeline: BG norm factor invalid; check BG exp/i0/T",
            "样品归一化因子无效（exp/i0/T）": "Sample norm factor invalid (exp/i0/T)",
            "厚度无效（固定厚度或metadata thk_mm）": "Thickness invalid (fixed or metadata thk_mm)",
            "BG 尺寸不匹配": "BG shape mismatch",
            "背景归一化因子无效": "Background norm factor invalid",
            "未提供可用背景图像": "No usable background images provided",
            "未提供背景图像": "No background images provided",
            "归一化因子 <= 0": "Normalisation factor <= 0",
            "扣背景后信号过弱": "Signal too weak after BG subtraction",
            # --- I0 / normalisation ---
            "I0 归一化模式仅支持": "I0 normalisation mode only supports",
            "未知 I0 归一化模式": "Unknown I0 normalisation mode",
            # --- Parser messages ---
            "角度非法": "Invalid angle",
            "扇区角度范围无效": "Invalid sector angle range",
            "扇区解析后为空": "Sector parsing result is empty",
            "无法解析文件": "Cannot parse file",
            "无法识别有效数值列": "Cannot identify valid numeric columns",
            "文件无法读取": "File unreadable",
            # --- Metadata ---
            "metadata CSV 缺少文件列": "metadata CSV missing file column",
            "未从报告中提取到可用 metadata 行": "No usable metadata rows extracted from report",
            # --- Instrument check ---
            "无法读取文件头": "Cannot read file header",
            "图像尺寸不一致": "Image dimensions inconsistent",
            "探测器型号不一致": "Detector model inconsistent",
            "无法读取 poni 做一致性检查": "Cannot read poni for consistency check",
            # --- Batch / load_data ---
            "缺少输出目录映射": "Missing output directory mapping",
            "扇区结果不完整，无法合并": "Sector results incomplete; cannot merge",
            "不支持的积分模式": "Unsupported integration mode",
            "文件头缺少关键字段": "File header missing key fields",
            "自动匹配失败": "Auto-match failed",
            "并行线程数必须为正整数": "Worker count must be a positive integer",
            # --- Preview ---
            "请先在 Tab1/Tab2 设置 poni 文件": "Please set poni file in Tab1/Tab2 first",
            "I-chi q 环带为空": "I-chi q-ring band is empty",
            "I-Q 预览区域为空，请检查扇区范围或 mask": "I-Q preview area empty; check sector range or mask",
            "I-chi 预览 q 范围无效：qmin 必须 < qmax": "I-chi preview q range invalid: qmin must be < qmax",
            # --- Misc ---
            "计算得到的 K <= 0": "Computed K <= 0",
            "输出已存在": "output already exists",
            "缺少文件头字段": "Missing header fields",
            "匹配到的 BG 头参数不完整": "Matched BG header params incomplete",
            "pyFAI 不支持 radial_unit，q 区间已按 A^-1->nm^-1 转换": "pyFAI unsupported radial_unit; q range converted A^-1->nm^-1",
            "模式失败": "Mode failed",
        }
        for k, v in repl.items():
            text = text.replace(k, v)
        return text

    def show_info(self, title_key, message):
        messagebox.showinfo(self.tr(title_key), message)

    def show_error(self, title_key, message):
        messagebox.showerror(self.tr(title_key), message)

    def show_warning(self, title_key, message):
        messagebox.showwarning(self.tr(title_key), message)

    def set_style(self):
        # Apply Sun-Valley theme first (light by default)
        apply_ios_theme(self.root)
        style = ttk.Style()
        # Only fall back to clam if sv_ttk is not active
        current = style.theme_use()
        if "sun-valley" not in current and "sv" not in current:
            try:
                style.theme_use("clam")
            except Exception:
                pass

        # --- Unified typography hierarchy ---
        _FONT_FAMILY = "Segoe UI"
        # Detect current theme for adaptive foreground colours
        try:
            import sv_ttk as _sv
            _is_dark = _sv.get_theme() == "dark"
        except Exception:
            _is_dark = False
        _title_fg = "#e0e0e0" if _is_dark else "#1a1a2e"
        _accent_fg = "#60a5fa" if _is_dark else "#0078d4"
        _hint_fg = "#9ca3af" if _is_dark else "#6b7280"

        style.configure("Title.TLabel",
                        font=(_FONT_FAMILY, 13, "bold"),
                        foreground=_title_fg)
        style.configure("Bold.TLabel",
                        font=(_FONT_FAMILY, 9, "bold"))
        style.configure("Group.TLabelframe.Label",
                        font=(_FONT_FAMILY, 9, "bold"),
                        foreground=_accent_fg)
        style.configure("Hint.TLabel",
                        font=(_FONT_FAMILY, 8),
                        foreground=_hint_fg)
        # Accent button font (sv_ttk supplies colours automatically)
        style.configure("Accent.TButton",
                        font=(_FONT_FAMILY, 10, "bold"))
        # Tab label – slightly larger, padded
        style.configure("TNotebook.Tab",
                        font=(_FONT_FAMILY, 10),
                        padding=(14, 6))
        # LabelFrame internal padding – breathable
        style.configure("Group.TLabelframe",
                        padding=(10, 8))
        # Status bar style
        style.configure("Status.TLabel",
                        font=(_FONT_FAMILY, 8),
                        foreground=_hint_fg,
                        padding=(8, 3))

        # Store references for dark-mode syncing (initialise only once)
        if not hasattr(self, "_native_widgets"):
            self._native_widgets: list = []
        if not hasattr(self, "_scroll_canvases"):
            self._scroll_canvases: list = []
        self.root._app_ref = self  # allow toggle_theme callback to reach us

    def _register_native_widget(self, widget):
        """Track a tk.Text or tk.Listbox so its colours follow the theme."""
        self._native_widgets.append(widget)
        self._apply_native_colors(widget)

    def _apply_native_colors(self, widget):
        """Set bg/fg on a single native tk widget according to current theme."""
        try:
            import sv_ttk as _sv
            is_dark = _sv.get_theme() == "dark"
        except Exception:
            is_dark = False
        if is_dark:
            bg, fg, sel_bg, sel_fg = "#2b2b2b", "#e0e0e0", "#264f78", "#ffffff"
            ins = "#e0e0e0"
        else:
            bg, fg, sel_bg, sel_fg = "#ffffff", "#1a1a1a", "#0078d4", "#ffffff"
            ins = "#1a1a1a"
        try:
            widget.configure(bg=bg, fg=fg, selectbackground=sel_bg, selectforeground=sel_fg)
            if isinstance(widget, tk.Text):
                widget.configure(insertbackground=ins)
        except Exception:
            pass

    def _sync_native_widget_colors(self):
        """Called after theme toggle to update all native tk widgets + mpl."""
        # Re-apply adaptive ttk styles (Title, Hint, Group, Status, Tab)
        self.set_style()

        alive = []
        for w in self._native_widgets:
            try:
                w.winfo_exists()  # raises TclError if destroyed
                self._apply_native_colors(w)
                alive.append(w)
            except Exception:
                pass
        self._native_widgets = alive

        # Update scroll-canvas backgrounds
        try:
            import sv_ttk as _sv
            is_dark = _sv.get_theme() == "dark"
        except Exception:
            is_dark = False
        canvas_bg = "#1e1e1e" if is_dark else "#fafafa"
        alive_c = []
        for c in self._scroll_canvases:
            try:
                c.winfo_exists()
                c.configure(bg=canvas_bg)
                alive_c.append(c)
            except Exception:
                pass
        self._scroll_canvases = alive_c

        # Update matplotlib figure backgrounds if present
        fig_bg = "#2b2b2b" if is_dark else "#fafafa"
        ax_bg = "#1e1e1e" if is_dark else "#ffffff"
        txt_c = "#e0e0e0" if is_dark else "#1a1a1a"
        import matplotlib as mpl
        mpl.rcParams.update({
            "figure.facecolor": fig_bg,
            "axes.facecolor": ax_bg,
            "text.color": txt_c,
            "axes.labelcolor": txt_c,
            "xtick.color": txt_c,
            "ytick.color": txt_c,
        })
        for attr in ("fig", "fig_preview"):
            fig = getattr(self, attr, None)
            if fig is not None:
                fig.set_facecolor(fig_bg)
                for ax in fig.get_axes():
                    ax.set_facecolor(ax_bg)
                fig.canvas.draw_idle()

    def _make_scrollable_frame(self, parent):
        """Wrap *parent* with a vertical-scrollable Canvas; return inner Frame."""
        # Choose canvas bg matching theme
        try:
            import sv_ttk as _sv
            _bg = "#1e1e1e" if _sv.get_theme() == "dark" else "#fafafa"
        except Exception:
            _bg = "#fafafa"
        canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0, bg=_bg)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda _: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(win_id, width=e.width),
        )
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))
        # Track for dark-mode sync
        self._scroll_canvases.append(canvas)
        return inner

    def add_tooltip(self, widget, text_or_key):
        if widget is None or not text_or_key:
            return
        # If text_or_key is a known i18n key, resolve it; otherwise use raw text
        lang_pack = I18N.get("en", {})
        is_key = text_or_key in lang_pack
        resolved = self.tr(text_or_key) if is_key else text_or_key
        tt = ToolTip(widget, resolved)
        self._tooltips.append(tt)
        if is_key:
            if not hasattr(self, "_i18n_tooltips"):
                self._i18n_tooltips = []
            self._i18n_tooltips.append((tt, text_or_key))

    def add_hint(self, parent, text_or_key, wraplength=420):
        lang_pack = I18N.get("en", {})
        is_key = text_or_key in lang_pack
        resolved = self.tr(text_or_key) if is_key else text_or_key
        lbl = ttk.Label(parent, text=f"{self.tr('hint_prefix')}: {resolved}", style="Hint.TLabel", justify="left", wraplength=wraplength)
        lbl.pack(fill="x", padx=3, pady=(1, 3))
        if is_key:
            if not hasattr(self, "_i18n_hints"):
                self._i18n_hints = []
            self._i18n_hints.append((lbl, text_or_key))
        return lbl

    # =========================================================================
    # 核心解析器
    # =========================================================================
    def _norm_key(self, key):
        return str(key).strip().lower().replace("_", "").replace(" ", "")

    def _extract_float(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float, np.number)):
            return float(value)

        s = str(value).strip()
        if not s:
            return None

        # 支持欧洲小数逗号，避免 "0,85" 无法解析
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")

        m = FLOAT_PATTERN.search(s)
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None

    def _normalize_transmission(self, trans, raw=None, key=None):
        if trans is None:
            return None
        try:
            t = float(trans)
        except Exception:
            return None
        if not np.isfinite(t):
            return None
        raw_s = str(raw).strip().lower() if raw is not None else ""
        key_s = self._norm_key(key) if key is not None else ""

        # 透过率归一化策略：
        # 1) 明确百分号/percent/pct -> 按百分数处理
        # 2) 1.0~2.0 视为轻微漂移，夹紧到 1.0（避免把 1.25 误判成 1.25%）
        # 3) 2.0~100 视作百分数字面量（如 85 -> 0.85）
        has_pct_hint = (
            "%" in raw_s
            or "percent" in raw_s
            or "pct" in raw_s
            or "percent" in key_s
            or "pct" in key_s
        )
        if has_pct_hint:
            t /= 100.0
        elif 1.0 < t <= 2.0:
            # 移除激进截断，保留物理真实性
            pass
        elif 2.0 < t <= 100.0:
            t /= 100.0
        if not np.isfinite(t) or t <= 0:
            return None
        if t > 1.0:
            logger.warning(
                "Transmission T=%.4f > 1.0 (physically impossible); "
                "header value will be ignored.",
                t,
            )
            return None
        return t

    def _assert_same_shape(self, a, b, a_name, b_name):
        if a.shape != b.shape:
            raise ValueError(f"Shape mismatch: {a_name}{a.shape} vs {b_name}{b.shape}")

    def get_monitor_mode(self):
        mode = str(self.global_vars["monitor_mode"].get()).strip().lower()
        if mode not in MONITOR_NORM_MODES:
            raise ValueError(f"I0 归一化模式仅支持: {', '.join(MONITOR_NORM_MODES)}")
        return mode

    def monitor_norm_formula(self, mode):
        if mode == "rate":
            return "exp * I0 * T"
        if mode == "integrated":
            return "I0 * T"
        raise ValueError(f"未知 I0 归一化模式: {mode}")

    def compute_norm_factor(self, exp, mon, trans, mode):
        if mon is None or trans is None:
            return np.nan
        try:
            mon_v = float(mon)
            trans_v = float(trans)
        except Exception:
            return np.nan

        if not (np.isfinite(mon_v) and np.isfinite(trans_v)):
            return np.nan
        if mon_v <= 0 or trans_v <= 0:
            return np.nan
        if trans_v > 1.0:
            logger.warning(
                "Transmission T=%.4f > 1.0 (physically impossible); "
                "normalization factor set to NaN. Check header parsing.",
                trans_v,
            )
            return np.nan

        if mode == "rate":
            if exp is None:
                return np.nan
            try:
                exp_v = float(exp)
            except Exception:
                return np.nan
            if not np.isfinite(exp_v) or exp_v <= 0:
                return np.nan
            return exp_v * mon_v * trans_v

        if mode == "integrated":
            return mon_v * trans_v

        raise ValueError(f"未知 I0 归一化模式: {mode}")

    def parse_header(self, filepath, header_dict=None):
        meta = {}

        def add_meta(k, v):
            if k is None or v is None:
                return
            nk = self._norm_key(k)
            if nk:
                meta[nk] = str(v).strip()

        exp_keys = ["exposuretime", "counttime", "acqtime", "exposure", "time"]
        mon_keys = ["monitor", "beammonitor", "ionchamber", "mon", "i0", "flux"]
        trans_keys = ["sampletransmission", "transmission", "trans", "abs"]
        exp_exact_only = {"time"}
        mon_exact_only = {"mon", "i0"}
        trans_exact_only = {"abs"}

        def get_val(keys, exact_only=None):
            exact_only = set(exact_only or [])
            # 1) exact
            for k in keys:
                if k in meta:
                    return meta[k], k

            # 2) prefix/suffix（避免通配 contains 误命中）
            for mk, mv in meta.items():
                for k in keys:
                    if k in exact_only:
                        continue
                    if mk.startswith(k) or mk.endswith(k):
                        return mv, mk

            # 3) contains 仅用于较长关键字
            for mk, mv in meta.items():
                for k in keys:
                    if k in exact_only or len(k) < 6:
                        continue
                    if k in mk:
                        return mv, mk
            return None, None

        def has_keys():
            exp_raw, _ = get_val(exp_keys, exact_only=exp_exact_only)
            mon_raw, _ = get_val(mon_keys, exact_only=mon_exact_only)
            trans_raw, _ = get_val(trans_keys, exact_only=trans_exact_only)
            return (exp_raw is not None) and (mon_raw is not None) and (trans_raw is not None)

        # 优先读取 FabIO header（对 tiff/edf 更稳健）
        need_text_fallback = True
        if header_dict is not None:
            for k, v in header_dict.items():
                add_meta(k, v)
            need_text_fallback = not has_keys()
        else:
            try:
                img = fabio.open(filepath)
                for k, v in getattr(img, "header", {}).items():
                    add_meta(k, v)
                need_text_fallback = not has_keys()
            except Exception:
                need_text_fallback = True

        # 回退：从文件文本头提取
        if need_text_fallback:
            try:
                with open(filepath, "rb") as f:
                    head_bytes = f.read(65536)
                # 某些 TIFF 头字段由 NUL 分隔，先替换可降低键值粘连风险
                head_str = head_bytes.decode("utf-8", errors="ignore").replace("\x00", "\n")
                for line in head_str.splitlines():
                    line = line.strip().lstrip("#").strip()
                    if not line:
                        continue
                    parts = []
                    if "=" in line:
                        parts = line.split("=", 1)
                    elif ":" in line:
                        parts = line.split(":", 1)
                    else:
                        parts = line.split(None, 1)
                    if len(parts) == 2:
                        k = str(parts[0]).strip()
                        # 限制 key 形态，降低从二进制噪声中误解析的概率
                        if not re.match(r"^[A-Za-z_][A-Za-z0-9_\- ]{0,64}$", k):
                            continue
                        add_meta(k, parts[1])
            except Exception:
                pass

        exp_raw, exp_key = get_val(exp_keys, exact_only=exp_exact_only)
        mon_raw, _ = get_val(mon_keys, exact_only=mon_exact_only)
        trans_raw, trans_key = get_val(trans_keys, exact_only=trans_exact_only)

        exp = self._extract_float(exp_raw)
        mon = self._extract_float(mon_raw)
        trans = self._extract_float(trans_raw)

        # 时间单位兼容：ms/us 自动转为秒
        if exp is not None:
            exp_tag = f"{exp_key or ''} {exp_raw or ''}".lower()
            if "ms" in exp_tag:
                exp /= 1000.0
            elif "us" in exp_tag:
                exp /= 1_000_000.0

        trans = self._normalize_transmission(trans, raw=trans_raw, key=trans_key)
        return exp, mon, trans

    def normalize_header_dict(self, header_dict):
        meta = {}
        if not header_dict:
            return meta
        for k, v in header_dict.items():
            nk = self._norm_key(k)
            if nk:
                meta[nk] = str(v).strip()
        return meta

    def meta_get_raw(self, meta, keys):
        for k in keys:
            if k in meta:
                return meta[k], k
        for mk, mv in meta.items():
            for k in keys:
                if k in mk:
                    return mv, mk
        return None, None

    def value_with_unit_to_si(self, raw, target):
        val = self._extract_float(raw)
        if val is None:
            return None
        s = str(raw).lower() if raw is not None else ""

        if target == "distance_m":
            if "mm" in s:
                return val / 1000.0
            if "cm" in s:
                return val / 100.0
            if "um" in s or "micron" in s:
                return val / 1_000_000.0
            if "nm" in s:
                return val / 1_000_000_000.0
            if " m" in f" {s}" or s.endswith("m"):
                return val
            if val > 20:
                return val / 1000.0
            return val

        if target == "pixel_m":
            if "um" in s or "micron" in s:
                return val / 1_000_000.0
            if "mm" in s:
                return val / 1000.0
            if "nm" in s:
                return val / 1_000_000_000.0
            if " m" in f" {s}" or s.endswith("m"):
                return val
            if val > 10:
                return val / 1_000_000.0
            if val > 0.01:
                return val / 1000.0
            return val

        if target == "wavelength_a":
            if "nm" in s:
                return val * 10.0
            if "pm" in s:
                return val / 100.0
            if "m" in s and "mm" not in s and "um" not in s and "nm" not in s:
                return val * 1e10
            return val

        if target == "energy_kev":
            if "mev" in s:
                return val * 1000.0
            if "ev" in s and "kev" not in s:
                return val / 1000.0
            return val

        return val

    def extract_instrument_signature(self, filepath, header_dict=None, shape=None):
        meta = self.normalize_header_dict(header_dict)
        if not meta:
            try:
                img = fabio.open(filepath)
                meta = self.normalize_header_dict(getattr(img, "header", {}))
                if shape is None:
                    shape = tuple(img.data.shape)
            except Exception:
                pass

        wl_raw, _ = self.meta_get_raw(meta, ["wavelength", "lambda", "wave"])
        en_raw, _ = self.meta_get_raw(meta, ["energykev", "energy", "xrayenergy", "beamenergy"])
        dist_raw, _ = self.meta_get_raw(meta, ["detdistance", "distance", "sampledetdist", "camlength"])
        px1_raw, _ = self.meta_get_raw(meta, ["pixel1", "pixelsizey", "pixely", "ypixelsize"])
        px2_raw, _ = self.meta_get_raw(meta, ["pixel2", "pixelsizex", "pixelx", "xpixelsize"])
        det_raw, _ = self.meta_get_raw(meta, ["detector", "detectorname", "detector_model"])

        wl_a = self.value_with_unit_to_si(wl_raw, "wavelength_a")
        en_kev = self.value_with_unit_to_si(en_raw, "energy_kev")
        dist_m = self.value_with_unit_to_si(dist_raw, "distance_m")
        px1_m = self.value_with_unit_to_si(px1_raw, "pixel_m")
        px2_m = self.value_with_unit_to_si(px2_raw, "pixel_m")

        if wl_a is None and en_kev and en_kev > 0:
            wl_a = HC_KEV_A / en_kev
        if en_kev is None and wl_a and wl_a > 0:
            en_kev = HC_KEV_A / wl_a

        return {
            "distance_m": dist_m,
            "pixel1_m": px1_m,
            "pixel2_m": px2_m,
        }

    def relative_diff(self, a, b):
        if a is None or b is None:
            return None
        if not (np.isfinite(a) and np.isfinite(b)):
            return None
        den = max(abs(a), 1e-12)
        return abs(a - b) / den

    def normalize_azimuth_deg(self, angle_deg):
        a = float(angle_deg)
        if not np.isfinite(a):
            raise ValueError(f"角度非法: {angle_deg}")
        return ((a + 180.0) % 360.0) - 180.0

    def resolve_sector_range(self, sec_min, sec_max):
        s1 = self.normalize_azimuth_deg(sec_min)
        s2 = self.normalize_azimuth_deg(sec_max)
        span = (s2 - s1 + 360.0) % 360.0
        if np.isclose(span, 0.0, atol=1e-9):
            raise ValueError("扇区角度范围无效：sec_min 与 sec_max 不能相同（模360）。")

        wrap = s1 > s2
        if wrap:
            segments = [(s1, 180.0), (-180.0, s2)]
        else:
            segments = [(s1, s2)]
        return s1, s2, wrap, segments

    def build_sector_mask(self, chi_deg, sec_min, sec_max):
        s1, s2, wrap, _ = self.resolve_sector_range(sec_min, sec_max)
        chi = np.asarray(chi_deg, dtype=np.float64)
        if wrap:
            mask = (chi >= s1) | (chi <= s2)
        else:
            mask = (chi >= s1) & (chi <= s2)
        return mask, s1, s2, wrap

    def _sector_value_token(self, value):
        s = f"{float(value):.3f}".rstrip("0").rstrip(".")
        if s in {"", "-0"}:
            s = "0"
        s = s.replace("-", "m").replace("+", "p").replace(".", "p")
        return s

    def sector_folder_name(self, idx, sec_min, sec_max):
        return f"sector_{int(idx):02d}_{self._sector_value_token(sec_min)}_to_{self._sector_value_token(sec_max)}"

    def parse_sector_specs(self, text, fallback_pair=None):
        raw = str(text).strip() if text is not None else ""
        pairs = []

        if raw:
            norm = (
                raw.replace("，", ",")
                .replace("；", ";")
                .replace("：", ":")
                .replace("～", "~")
                .replace("→", "->")
                .replace("至", "to")
            )
            pat = re.compile(
                r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(?:~|,|:|->|to)\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
                re.IGNORECASE,
            )
            for m in pat.finditer(norm):
                pairs.append((float(m.group(1)), float(m.group(2))))

            if not pairs:
                nums = [float(x) for x in FLOAT_PATTERN.findall(norm)]
                if len(nums) >= 2 and len(nums) % 2 == 0:
                    pairs = list(zip(nums[::2], nums[1::2]))

        if not pairs:
            if raw:
                raise ValueError(
                    "未解析到扇区范围。可用示例：-25~25;45~65 或 -25,25 45,65。"
                )
            if fallback_pair is not None:
                a, b = fallback_pair
                pairs = [(float(a), float(b))]
            else:
                raise ValueError("未提供扇区范围。")

        specs = []
        seen = set()
        for a, b in pairs:
            s1, s2, wrap, segments = self.resolve_sector_range(a, b)
            sig = (round(float(s1), 6), round(float(s2), 6))
            if sig in seen:
                continue
            seen.add(sig)
            idx = len(specs) + 1
            specs.append({
                "index": idx,
                "input_min": float(a),
                "input_max": float(b),
                "sec_min": float(s1),
                "sec_max": float(s2),
                "wrap": bool(wrap),
                "segments": list(segments),
                "label": f"[{s1:.2f},{s2:.2f}]",
                "key": self.sector_folder_name(idx, s1, s2),
            })

        if not specs:
            raise ValueError("扇区解析后为空，请检查输入。")
        return specs

    def get_t2_sector_specs(self):
        txt = self.t2_sector_ranges_text.get().strip() if hasattr(self, "t2_sector_ranges_text") else ""
        fallback = (float(self.t2_sec_min.get()), float(self.t2_sec_max.get()))
        return self.parse_sector_specs(txt, fallback_pair=fallback)

    def merge_integrate1d_results(self, results):
        if not results:
            raise ValueError("无可合并积分结果。")

        r0 = np.asarray(results[0].radial, dtype=np.float64)
        if r0.size < 2:
            raise ValueError("积分结果点数不足。")

        sum_w = np.zeros_like(r0, dtype=np.float64)
        sum_iw = np.zeros_like(r0, dtype=np.float64)
        sum_sw2 = np.zeros_like(r0, dtype=np.float64)
        has_sigma = False

        for res in results:
            rr = np.asarray(res.radial, dtype=np.float64)
            if rr.shape != r0.shape or not np.allclose(rr, r0, rtol=1e-7, atol=1e-12, equal_nan=False):
                raise ValueError("分段扇区积分的 q 网格不一致，无法合并。")

            i = np.asarray(res.intensity, dtype=np.float64)
            w = getattr(res, "count", None)
            if w is None:
                w = np.where(np.isfinite(i), 1.0, 0.0)
            else:
                w = np.asarray(w, dtype=np.float64)
                if w.shape != r0.shape:
                    w = np.where(np.isfinite(i), 1.0, 0.0)
                w = np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0)
                w = np.maximum(w, 0.0)

            i_num = np.nan_to_num(i, nan=0.0, posinf=0.0, neginf=0.0)
            sum_iw += i_num * w
            sum_w += w

            sigma = getattr(res, "sigma", None)
            if sigma is not None:
                s = np.asarray(sigma, dtype=np.float64)
                if s.shape == r0.shape:
                    term = np.nan_to_num(s, nan=0.0, posinf=0.0, neginf=0.0) * w
                    sum_sw2 += term * term
                    has_sigma = True

        i_merge = np.divide(sum_iw, sum_w, out=np.full_like(sum_iw, np.nan), where=sum_w > 0)
        sigma_merge = None
        if has_sigma:
            sigma_merge = np.divide(
                np.sqrt(sum_sw2),
                sum_w,
                out=np.full_like(sum_w, np.nan),
                where=sum_w > 0,
            )

        return SimpleNamespace(
            radial=r0,
            intensity=i_merge,
            sigma=sigma_merge,
            count=sum_w,
        )

    def integrate1d_sector(self, ai, img, npt, sec_min, sec_max, **kwargs):
        s1, s2, wrap, segments = self.resolve_sector_range(sec_min, sec_max)

        if len(segments) == 1:
            res = ai.integrate1d(
                img,
                npt,
                unit="q_A^-1",
                azimuth_range=segments[0],
                **kwargs,
            )
            return res, s1, s2, wrap

        parts = []
        for seg in segments:
            parts.append(
                ai.integrate1d(
                    img,
                    npt,
                    unit="q_A^-1",
                    azimuth_range=seg,
                    **kwargs,
                )
            )
        res = self.merge_integrate1d_results(parts)
        return res, s1, s2, wrap

    def check_instrument_consistency(self, file_paths, poni_path=None, tol_pct=0.5):
        if not file_paths:
            return []
        tol = max(float(tol_pct), 0.01) / 100.0
        sigs = []
        for fp in file_paths:
            try:
                img = fabio.open(fp)
                d = img.data
                sig = self.extract_instrument_signature(fp, header_dict=getattr(img, "header", {}), shape=d.shape)
                sigs.append(sig)
            except Exception as e:
                sigs.append({"path": str(fp), "shape": None, "error": str(e)})

        ref = sigs[0]
        fallback = self.session_geometry_fallback if isinstance(self.session_geometry_fallback, dict) else {}
        if fallback:
            for key in ("wavelength_a", "distance_m", "pixel1_m", "pixel2_m", "energy_kev"):
                if ref.get(key) is None and fallback.get(key) is not None:
                    ref[key] = fallback.get(key)

        issues = []
        for s in sigs[1:]:
            p = Path(s.get("path", "")).name
            if "error" in s:
                issues.append(f"{p}: 无法读取文件头 ({s['error']})")
                continue

            if ref.get("shape") and s.get("shape") and ref["shape"] != s["shape"]:
                issues.append(f"{p}: 图像尺寸不一致 {s['shape']} != {ref['shape']}")

            if ref.get("detector") and s.get("detector") and ref["detector"] != s["detector"]:
                issues.append(f"{p}: 探测器型号不一致 {s['detector']} != {ref['detector']}")

            for key, label in [
                ("energy_kev", "能量(keV)"),
                ("wavelength_a", "波长(A)"),
                ("distance_m", "样探距(m)"),
                ("pixel1_m", "pixel1(m)"),
                ("pixel2_m", "pixel2(m)"),
            ]:
                rd = self.relative_diff(s.get(key), ref.get(key))
                if rd is not None and rd > tol:
                    issues.append(
                        f"{p}: {label} 偏差 {rd*100:.3f}% 超过阈值 {tol*100:.3f}%"
                    )

        if poni_path:
            try:
                ai = pyFAI.load(poni_path)
                ai_wl_a = ai.wavelength * 1e10 if getattr(ai, "wavelength", None) else None
                if ai_wl_a and ref.get("wavelength_a"):
                    rd = self.relative_diff(ai_wl_a, ref["wavelength_a"])
                    if rd is not None and rd > tol:
                        issues.append(
                            f"poni 波长与样品头信息不一致: {ai_wl_a:.6g} A vs {ref['wavelength_a']:.6g} A"
                        )
            except Exception as e:
                issues.append(f"无法读取 poni 做一致性检查: {e}")

        return issues

    def build_output_stem_map(self, files):
        name_count = {}
        for fp in files:
            stem = Path(fp).stem
            name_count[stem] = name_count.get(stem, 0) + 1

        used = set()
        out = {}
        for fp in files:
            p = Path(fp)
            stem = p.stem
            if name_count[stem] == 1:
                candidate = stem
            else:
                candidate = f"{p.parent.name}_{stem}"

            if candidate in used:
                idx = 2
                while f"{candidate}_{idx}" in used:
                    idx += 1
                candidate = f"{candidate}_{idx}"

            used.add(candidate)
            out[fp] = candidate
        return out

    def mode_output_path(self, save_dirs, mode, out_stem):
        ext = ".chi" if mode == "radial_chi" else ".dat"
        return save_dirs[mode] / f"{out_stem}{ext}"

    def build_sample_output_targets(self, context, out_stem):
        targets = []
        for mode in context["selected_modes"]:
            if mode != "1d_sector":
                targets.append((mode, self.mode_output_path(context["save_dirs"], mode, out_stem)))
                continue

            if context.get("sector_save_each", True):
                for spec in context.get("sector_specs", []):
                    d = context.get("sector_save_dirs", {}).get(spec["key"])
                    if d is None:
                        continue
                    targets.append((f"1d_sector{spec['label']}", d / f"{out_stem}.dat"))

            if context.get("sector_save_combined", False):
                d = context.get("sector_combined_dir", None)
                if d is not None:
                    targets.append(("1d_sector_sum", d / f"{out_stem}.dat"))
        return targets

    def save_profile_table(self, out_path, x, i_abs, i_err, x_label, output_format="tsv"):
        # Origin-friendly text table: first row is column names, tab-separated.
        out_path = Path(out_path)
        x_arr = np.asarray(x, dtype=np.float64)
        i_arr = np.asarray(i_abs, dtype=np.float64)
        e_arr = np.asarray(i_err, dtype=np.float64)

        if output_format in ("cansas_xml", "nxcansas_h5") and str(x_label) != "Q_A^-1":
            raise ValueError(
                f"输出格式 {output_format} 仅支持 Q_A^-1 轴数据，当前为 {x_label}。"
            )

        if output_format == "cansas_xml" and write_cansas1d_xml is not None:
            xml_path = out_path.with_suffix(".xml")
            write_cansas1d_xml(xml_path, x_arr, i_arr, e_arr)
            return
        if output_format == "nxcansas_h5" and write_nxcansas_h5 is not None:
            h5_path = out_path.with_suffix(".h5")
            write_nxcansas_h5(h5_path, x_arr, i_arr, e_arr)
            return

        df = pd.DataFrame({
            x_label: x_arr,
            "I_abs_cm^-1": i_arr,
            "Error_cm^-1": e_arr,
        })
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        sep = "," if output_format == "csv" else "\t"
        suffix = ".csv" if output_format == "csv" else ".dat"
        final_path = out_path.with_suffix(suffix) if output_format == "csv" else out_path
        df.to_csv(
            final_path,
            sep=sep,
            index=False,
            encoding="utf-8-sig",
            na_rep="",
            float_format="%.10g",
        )

    def load_optional_array(self, path, name):
        if not path:
            return None
        p = Path(path)
        if p.suffix.lower() == ".npy":
            arr = np.load(path)
        else:
            arr = fabio.open(path).data
        if arr is None:
            raise ValueError(f"{name} 文件无法读取: {path}")
        return np.asarray(arr)

    def profile_health_issue(self, i_abs):
        arr = np.asarray(i_abs, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if arr.size < 50:
            return None
        non_pos_frac = float(np.mean(arr <= 0))
        if non_pos_frac >= 0.98:
            return (
                f"积分结果异常：非正值比例 {non_pos_frac*100:.1f}% "
                "(疑似过扣背景或归一化设置错误)"
            )
        return None

    def build_reference_library(self, paths):
        refs = []
        for p in list(dict.fromkeys(paths or [])):
            try:
                img = fabio.open(p)
                data = np.asarray(img.data)
                exp, mon, trans = self.parse_header(p, header_dict=getattr(img, "header", {}))
                refs.append({
                    "path": str(p),
                    "shape": tuple(data.shape),
                    "exp": exp,
                    "mon": mon,
                    "trans": trans,
                    "mtime": Path(p).stat().st_mtime if Path(p).exists() else None,
                })
            except Exception:
                continue
        return refs

    def reference_score(self, sample_meta, ref_meta, kind="bg"):
        score = 0.0
        used = 0.0

        se, re = sample_meta.get("exp"), ref_meta.get("exp")
        sm, rm = sample_meta.get("mon"), ref_meta.get("mon")
        st, rt = sample_meta.get("trans"), ref_meta.get("trans")
        stime, rtime = sample_meta.get("mtime"), ref_meta.get("mtime")

        if se and re and se > 0 and re > 0:
            score += self.relative_diff(se, re) * 1.0
            used += 1.0
        if sm and rm and sm > 0 and rm > 0:
            score += self.relative_diff(sm, rm) * 0.8
            used += 0.8
        if kind == "bg" and st and rt and st > 0 and rt > 0:
            score += abs(st - rt) * 1.5
            used += 1.5
        if stime and rtime:
            dt_h = abs(stime - rtime) / 3600.0
            score += min(dt_h / 24.0, 3.0) * 0.5
            used += 0.5

        if used == 0:
            return 1e9
        return score / used

    def select_best_reference(self, sample_meta, refs, kind="bg"):
        if not refs:
            return None, None
        same_shape = [r for r in refs if r.get("shape") == sample_meta.get("shape")]
        pool = same_shape if same_shape else refs
        scored = []
        for r in pool:
            scored.append((self.reference_score(sample_meta, r, kind=kind), r))
        scored.sort(key=lambda x: x[0])
        return scored[0][1], scored[0][0]

    # =========================================================================
    # TAB 1: K-Factor Calibration
    # =========================================================================
    def init_tab1_k_calc(self):
        p = self.tab1
        left_panel = ttk.Frame(p, width=400)
        left_panel.pack(side="left", fill="y", padx=5, pady=5)

        # 流程提示
        f_guide = ttk.LabelFrame(left_panel, text=self.tr("t1_guide_title"), style="Group.TLabelframe")
        self._register_i18n_widget(f_guide, "t1_guide_title")
        f_guide.pack(fill="x", pady=5)
        guide_text = self.tr("t1_guide_text")
        lbl_guide = ttk.Label(f_guide, text=guide_text, justify="left", style="Hint.TLabel")
        self._register_i18n_widget(lbl_guide, "t1_guide_text")
        lbl_guide.pack(fill="x", padx=4, pady=3)
        self.add_tooltip(lbl_guide, "tip_t1_guide")

        # 1. 文件区
        f_files = ttk.LabelFrame(left_panel, text=self.tr("t1_files_title"), style="Group.TLabelframe")
        self._register_i18n_widget(f_files, "t1_files_title")
        f_files.pack(fill="x", pady=5)
        self.add_hint(f_files, "hint_t1_files")
        
        self.t1_files = {
            "std": tk.StringVar(), "bg": self.global_vars["bg_path"],
            "dark": self.global_vars["dark_path"], "poni": self.global_vars["poni_path"]
        }

        # --- Standard type selector row ---
        self.t1_std_type = tk.StringVar(value="SRM3600")
        self.t1_water_temp = tk.DoubleVar(value=20.0)
        self.t1_std_ref_path = tk.StringVar()

        row_std_type = ttk.Frame(f_files); row_std_type.pack(fill="x", pady=1)
        lbl_std_type = ttk.Label(row_std_type, text=self.tr("lbl_t1_std_type"), width=15, anchor="e")
        lbl_std_type.pack(side="left")
        self._register_i18n_widget(lbl_std_type, "lbl_t1_std_type")
        std_options = [
            self.tr("opt_std_srm3600"),
            self.tr("opt_std_water"),
            self.tr("opt_std_lupolen"),
            self.tr("opt_std_custom"),
        ]
        self._t1_std_option_map = {
            self.tr("opt_std_srm3600"): "SRM3600",
            self.tr("opt_std_water"): "Water_20C",
            self.tr("opt_std_lupolen"): "Lupolen",
            self.tr("opt_std_custom"): "Custom",
        }
        self.t1_std_combo = ttk.Combobox(row_std_type, values=std_options, width=25, state="readonly")
        self.t1_std_combo.current(0)
        self.t1_std_combo.pack(side="left", padx=5)
        self.t1_std_combo.bind("<<ComboboxSelected>>", self._on_std_type_changed)

        # Water temperature row (hidden by default)
        self.t1_water_row = ttk.Frame(f_files)
        lbl_wt = ttk.Label(self.t1_water_row, text=self.tr("lbl_t1_water_temp"), width=15, anchor="e")
        lbl_wt.pack(side="left")
        self._register_i18n_widget(lbl_wt, "lbl_t1_water_temp")
        ttk.Entry(self.t1_water_row, textvariable=self.t1_water_temp, width=8).pack(side="left", padx=5)
        # Not packed initially — shown when Water is selected

        # Reference curve file row (hidden by default)
        self.t1_ref_row = self.add_file_row(f_files, self.tr("lbl_t1_std_ref_file"), self.t1_std_ref_path, "*.dat *.txt *.csv *.xml")
        self.t1_ref_row["frame"].pack_forget()  # hidden by default

        row_std = self.add_file_row(f_files, self.tr("lbl_t1_std_file"), self.t1_files["std"], "*.tif", self.on_load_std_t1)
        self.add_tooltip(row_std["entry"], "tip_t1_std_entry")
        self.add_tooltip(row_std["button"], "tip_t1_std_btn")

        row_bg = self.add_file_row(f_files, self.tr("lbl_t1_bg_file"), self.t1_files["bg"], "*.tif", self.on_load_bg_t1)
        self.add_tooltip(row_bg["entry"], "tip_t1_bg_entry")
        self.add_tooltip(row_bg["button"], "tip_t1_bg_btn")
        btn_bg_multi = ttk.Button(row_bg["frame"], text="+", width=3, command=self.select_multi_bg_t1)
        btn_bg_multi.pack(side="left", padx=(2, 0))
        self.add_tooltip(btn_bg_multi, "tip_t1_bg_multi")

        row_dark = self.add_file_row(f_files, self.tr("lbl_t1_dark_file"), self.t1_files["dark"], "*.tif")
        self.add_tooltip(row_dark["entry"], "tip_t1_dark_entry")
        self.add_tooltip(row_dark["button"], "tip_t1_dark_btn")

        row_poni = self.add_file_row(f_files, self.tr("lbl_t1_poni_file"), self.t1_files["poni"], "*.poni")
        self.add_tooltip(row_poni["entry"], "tip_t1_poni_entry")
        self.add_tooltip(row_poni["button"], "tip_t1_poni_btn")

        # 2. 物理参数
        f_phys = ttk.LabelFrame(left_panel, text=self.tr("t1_phys_title"), style="Group.TLabelframe")
        self._register_i18n_widget(f_phys, "t1_phys_title")
        f_phys.pack(fill="x", pady=5)
        self.add_hint(f_phys, "hint_t1_phys")
        f_phys_grid = ttk.Frame(f_phys)
        f_phys_grid.pack(fill="x")
        
        self.t1_params = {
            "std_exp": tk.DoubleVar(value=1.0), "std_i0": tk.DoubleVar(value=1.0),
            "std_t": tk.DoubleVar(value=1.0), "std_thk": tk.DoubleVar(value=1.0),
            "bg_exp": self.global_vars["bg_exp"], "bg_i0": self.global_vars["bg_i0"], "bg_t": self.global_vars["bg_t"]
        }
        
        headers = ["Time(s)", "I0(Mon)", "Trans(T)", "Thk(mm)"]
        for i, h in enumerate(headers):
            ttk.Label(f_phys_grid, text=h, style="Hint.TLabel").grid(row=0, column=i+1)
        
        ttk.Label(f_phys_grid, text="Std:", style="Bold.TLabel").grid(row=1, column=0, pady=2)
        e_std_exp = self.add_grid_entry(f_phys_grid, self.t1_params["std_exp"], 1, 1)
        e_std_i0 = self.add_grid_entry(f_phys_grid, self.t1_params["std_i0"], 1, 2)
        e_std_t = self.add_grid_entry(f_phys_grid, self.t1_params["std_t"], 1, 3)
        e_std_thk = self.add_grid_entry(f_phys_grid, self.t1_params["std_thk"], 1, 4)
        
        ttk.Label(f_phys_grid, text="BG:", style="Bold.TLabel").grid(row=2, column=0, pady=2)
        e_bg_exp = self.add_grid_entry(f_phys_grid, self.t1_params["bg_exp"], 2, 1)
        e_bg_i0 = self.add_grid_entry(f_phys_grid, self.t1_params["bg_i0"], 2, 2)
        e_bg_t = self.add_grid_entry(f_phys_grid, self.t1_params["bg_t"], 2, 3)
        ttk.Label(f_phys_grid, text="-").grid(row=2, column=4)

        norm_row = ttk.Frame(f_phys)
        norm_row.pack(fill="x", pady=(3, 0))
        lbl_i0_t1 = ttk.Label(norm_row, text=self.tr("lbl_i0_semantic"))
        lbl_i0_t1.pack(side="left")
        self._register_i18n_widget(lbl_i0_t1, "lbl_i0_semantic")
        cb_norm_t1 = ttk.Combobox(
            norm_row,
            textvariable=self.global_vars["monitor_mode"],
            width=11,
            state="readonly",
            values=MONITOR_NORM_MODES,
        )
        cb_norm_t1.pack(side="left", padx=(4, 6))
        lbl_norm_hint_t1 = ttk.Label(
            norm_row,
            text="rate: exp*I0*T | integrated: I0*T",
            style="Hint.TLabel",
        )
        lbl_norm_hint_t1.pack(side="left")
        cb_solid_t1 = ttk.Checkbutton(
            norm_row,
            text=self.tr("cb_solid_angle"),
            variable=self.global_vars["apply_solid_angle"],
        )
        cb_solid_t1.pack(side="left", padx=(8, 0))
        self._register_i18n_widget(cb_solid_t1, "cb_solid_angle")

        self.add_tooltip(e_std_exp, "tip_t1_std_exp")
        self.add_tooltip(e_std_i0, "tip_t1_std_i0")
        self.add_tooltip(e_std_t, "tip_t1_std_t")
        self.add_tooltip(e_std_thk, "tip_t1_std_thk")
        self.add_tooltip(e_bg_exp, "tip_t1_bg_exp")
        self.add_tooltip(e_bg_i0, "tip_t1_bg_i0")
        self.add_tooltip(e_bg_t, "tip_t1_bg_t")
        self.add_tooltip(cb_norm_t1, "tip_t1_norm_mode")
        self.add_tooltip(lbl_norm_hint_t1, "tip_t1_norm_hint")
        self.add_tooltip(cb_solid_t1, "tip_t1_solid_angle")

        # 3. 操作按钮
        btn_row = ttk.Frame(left_panel)
        btn_row.pack(fill="x", pady=10)
        btn_cal = ttk.Button(btn_row, text=self.tr("t1_run_btn"), command=self.run_calibration, style="Accent.TButton")
        self._register_i18n_widget(btn_cal, "t1_run_btn")
        btn_cal.pack(side="left", fill="x", expand=True, ipady=5)
        btn_hist = ttk.Button(btn_row, text=self.tr("t1_hist_btn"), command=self.open_k_history)
        self._register_i18n_widget(btn_hist, "t1_hist_btn")
        btn_hist.pack(side="left", padx=(6, 0))
        self.add_tooltip(btn_cal, "tip_t1_calibrate")
        self.add_tooltip(btn_hist, "tip_t1_history")

        # 4. 报告
        f_rep = ttk.LabelFrame(left_panel, text=self.tr("t1_report_title"), style="Group.TLabelframe")
        self._register_i18n_widget(f_rep, "t1_report_title")
        f_rep.pack(fill="both", expand=True, pady=5)
        self.txt_report = tk.Text(f_rep, font=("Consolas", 9), height=15, width=40)
        self.txt_report.pack(fill="both", expand=True)
        # Configure semantic highlight tags for report text
        self.txt_report.tag_configure("error", foreground="#dc2626")
        self.txt_report.tag_configure("success", foreground="#16a34a", font=("Consolas", 9, "bold"))
        self.txt_report.tag_configure("warning", foreground="#d97706")
        self._register_native_widget(self.txt_report)
        self.add_tooltip(self.txt_report, "tip_t1_report")

        # --- 右侧图形 ---
        right_panel = ttk.Frame(p)
        right_panel.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        lbl_plot_tip = ttk.Label(
            right_panel,
            text=self.tr("t1_plot_tip"),
            style="Hint.TLabel",
        )
        self._register_i18n_widget(lbl_plot_tip, "t1_plot_tip")
        lbl_plot_tip.pack(anchor="w", pady=(0, 2))
        self.fig1 = Figure(figsize=(6, 5), dpi=100)
        self.ax1 = self.fig1.add_subplot(111)
        self.canvas1 = FigureCanvasTkAgg(self.fig1, master=right_panel)
        self.canvas1.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar1 = NavigationToolbar2Tk(self.canvas1, right_panel)
        self.toolbar1.update()
        self.add_tooltip(lbl_plot_tip, "tip_t1_plot")

    # =========================================================================
    # TAB 2: Batch Processing
    # =========================================================================
    def init_tab2_batch(self):
        p = self._make_scrollable_frame(self.tab2)
        
        self.t2_files = []
        self.t2_mu = tk.DoubleVar(value=20.2)
        self.t2_calc_mode = tk.StringVar(value="auto") 
        self.t2_fixed_thk = tk.DoubleVar(value=1.0)
        self.t2_ref_mode = tk.StringVar(value="fixed")
        self.t2_error_model = tk.StringVar(value="azimuthal")
        self.t2_apply_solid_angle = self.global_vars["apply_solid_angle"]
        self.t2_polarization = tk.DoubleVar(value=0.0)
        self.t2_output_root = tk.StringVar(value="")
        self.t2_mask_path = tk.StringVar()
        self.t2_flat_path = tk.StringVar()
        self.t2_resume_enabled = tk.BooleanVar(value=True)
        self.t2_overwrite = tk.BooleanVar(value=False)
        self.t2_workers = tk.IntVar(value=1)
        self.t2_strict_instrument = tk.BooleanVar(value=True)
        self.t2_instr_tol_pct = tk.DoubleVar(value=0.5)
        self.t2_alpha = tk.DoubleVar(value=1.0)
        self.t2_alpha_enabled = tk.BooleanVar(value=False)
        self.t2_output_format = tk.StringVar(value="tsv")
        self.t2_bg_candidates = []
        self.t2_dark_candidates = []
        self.t2_bg_lib_info = tk.StringVar(value=self.tr("var_bg_lib").format(n=0))
        self.t2_dark_lib_info = tk.StringVar(value=self.tr("var_dark_lib").format(n=0))
        
        self.t2_mode_full = tk.BooleanVar(value=True)
        self.t2_mode_sector = tk.BooleanVar(value=False)
        self.t2_mode_chi = tk.BooleanVar(value=False)
        self.t2_sec_min = tk.DoubleVar(value=-20)
        self.t2_sec_max = tk.DoubleVar(value=20)
        self.t2_sector_ranges_text = tk.StringVar(value="")
        self.t2_sector_save_each = tk.BooleanVar(value=True)
        self.t2_sector_save_combined = tk.BooleanVar(value=False)
        self.t2_rad_qmin = tk.DoubleVar(value=0.5)
        self.t2_rad_qmax = tk.DoubleVar(value=2.5)

        # 流程提示
        f_guide = ttk.LabelFrame(p, text=self.tr("t2_guide_title"), style="Group.TLabelframe")
        self._register_i18n_widget(f_guide, "t2_guide_title")
        f_guide.pack(fill="x", padx=10, pady=(8, 3))
        guide = self.tr("t2_guide_text")
        lbl_guide = ttk.Label(f_guide, text=guide, justify="left", style="Hint.TLabel")
        self._register_i18n_widget(lbl_guide, "t2_guide_text")
        lbl_guide.pack(fill="x", padx=4, pady=3)
        self.add_tooltip(lbl_guide, "tip_t2_guide")

        # --- Settings ---
        top_frame = ttk.Frame(p)
        top_frame.pack(fill="x", padx=10, pady=5)
        
        # 1. Global
        c1 = ttk.LabelFrame(top_frame, text=self.tr("lf_t2_global"), style="Group.TLabelframe")
        c1.pack(side="left", fill="y", padx=5)
        self._register_i18n_widget(c1, "lf_t2_global")
        self.add_hint(c1, "hint_t2_global", wraplength=300)
        c1_grid = ttk.Frame(c1)
        c1_grid.pack(fill="x")
        lbl_k = ttk.Label(c1_grid, text=self.tr("lbl_t2_k_factor"))
        lbl_k.grid(row=0, column=0, sticky="e")
        self._register_i18n_widget(lbl_k, "lbl_t2_k_factor")
        e_k = ttk.Entry(c1_grid, textvariable=self.global_vars["k_factor"], width=10)
        e_k.grid(row=0, column=1, padx=5)
        lbl_bgf = ttk.Label(c1_grid, text=self.tr("lbl_t2_bg_file"))
        lbl_bgf.grid(row=1, column=0, sticky="e")
        self._register_i18n_widget(lbl_bgf, "lbl_t2_bg_file")
        lbl_bg = ttk.Label(c1_grid, textvariable=self.global_vars["bg_path"], width=20, style="Hint.TLabel")
        lbl_bg.grid(row=1, column=1, padx=5)
        lbl_i0 = ttk.Label(c1_grid, text=self.tr("lbl_t2_i0_semantic"))
        lbl_i0.grid(row=2, column=0, sticky="e")
        self._register_i18n_widget(lbl_i0, "lbl_t2_i0_semantic")
        cb_norm_t2 = ttk.Combobox(
            c1_grid,
            textvariable=self.global_vars["monitor_mode"],
            width=11,
            state="readonly",
            values=MONITOR_NORM_MODES,
        )
        cb_norm_t2.grid(row=2, column=1, padx=5, pady=(2, 0), sticky="w")
        lbl_norm_hint_t2 = ttk.Label(c1_grid, text="rate: exp*I0*T / integrated: I0*T", style="Hint.TLabel")
        lbl_norm_hint_t2.grid(row=3, column=0, columnspan=2, sticky="w", padx=2)
        self.add_tooltip(e_k, "tip_t2_k_factor")
        self.add_tooltip(lbl_bg, "tip_t2_bg_label")
        self.add_tooltip(cb_norm_t2, "tip_t2_norm_mode")
        self.add_tooltip(lbl_norm_hint_t2, "tip_t2_norm_hint")

        # 2. Thickness
        c2 = ttk.LabelFrame(top_frame, text=self.tr("lf_t2_thickness"), style="Group.TLabelframe")
        c2.pack(side="left", fill="y", padx=5)
        self._register_i18n_widget(c2, "lf_t2_thickness")
        self.add_hint(c2, "hint_t2_thickness", wraplength=320)
        
        r1 = ttk.Frame(c2); r1.pack(anchor="w")
        rb_auto = ttk.Radiobutton(r1, text=self.tr("rb_t2_auto_thk"), variable=self.t2_calc_mode, value="auto")
        rb_auto.pack(side="left")
        self._register_i18n_widget(rb_auto, "rb_t2_auto_thk")
        lbl_mu = ttk.Label(r1, text=self.tr("lbl_t2_mu"))
        lbl_mu.pack(side="left")
        self._register_i18n_widget(lbl_mu, "lbl_t2_mu")
        e_mu = ttk.Entry(r1, textvariable=self.t2_mu, width=6)
        e_mu.pack(side="left")
        btn_est = ttk.Button(r1, text=self.tr("btn_t2_mu_est"), command=self.open_mu_tool, width=8)
        btn_est.pack(side="left", padx=2)
        self._register_i18n_widget(btn_est, "btn_t2_mu_est")
        
        r2 = ttk.Frame(c2); r2.pack(anchor="w")
        rb_fix = ttk.Radiobutton(r2, text=self.tr("rb_t2_fix_thk"), variable=self.t2_calc_mode, value="fixed")
        rb_fix.pack(side="left")
        self._register_i18n_widget(rb_fix, "rb_t2_fix_thk")
        e_fix = ttk.Entry(r2, textvariable=self.t2_fixed_thk, width=6)
        e_fix.pack(side="left")

        self.add_tooltip(rb_auto, "tip_t2_auto_thk")
        self.add_tooltip(e_mu, "tip_t2_mu")
        self.add_tooltip(btn_est, "tip_t2_mu_est")
        self.add_tooltip(rb_fix, "tip_t2_fix_thk")
        self.add_tooltip(e_fix, "tip_t2_fix_thk_val")
        self.add_tooltip(lbl_mu, "tip_t2_mu_label")
        
        # 3. Integration
        c3 = ttk.LabelFrame(top_frame, text=self.tr("lf_t2_integration"), style="Group.TLabelframe")
        c3.pack(side="left", fill="y", padx=5)
        self._register_i18n_widget(c3, "lf_t2_integration")
        self.add_hint(c3, "hint_t2_integration", wraplength=320)
        c3_grid = ttk.Frame(c3)
        c3_grid.pack(fill="x")

        cb_full = ttk.Checkbutton(c3_grid, text=self.tr("cb_t2_full_ring"), variable=self.t2_mode_full)
        cb_full.grid(row=0, column=0, sticky="w")
        self._register_i18n_widget(cb_full, "cb_t2_full_ring")
        f_sec = ttk.Frame(c3_grid); f_sec.grid(row=1, column=0, sticky="w")
        cb_sec = ttk.Checkbutton(f_sec, text=self.tr("cb_t2_sector"), variable=self.t2_mode_sector)
        cb_sec.pack(side="left")
        self._register_i18n_widget(cb_sec, "cb_t2_sector")
        ttk.Label(f_sec, text=" [").pack(side="left")
        e_sec_min = ttk.Entry(f_sec, textvariable=self.t2_sec_min, width=4)
        e_sec_min.pack(side="left")
        ttk.Label(f_sec, text=",").pack(side="left")
        e_sec_max = ttk.Entry(f_sec, textvariable=self.t2_sec_max, width=4)
        e_sec_max.pack(side="left")
        ttk.Label(f_sec, text="] deg").pack(side="left")
        btn_sec_preview = ttk.Button(f_sec, text=self.tr("btn_t2_iq_preview"), width=8, command=self.preview_iq_window_t2)
        btn_sec_preview.pack(side="left", padx=(4, 0))
        self._register_i18n_widget(btn_sec_preview, "btn_t2_iq_preview")

        f_sec_multi = ttk.Frame(c3_grid); f_sec_multi.grid(row=2, column=0, sticky="w")
        lbl_msec = ttk.Label(f_sec_multi, text=self.tr("lbl_t2_multi_sector"))
        lbl_msec.pack(side="left")
        self._register_i18n_widget(lbl_msec, "lbl_t2_multi_sector")
        e_sec_multi = ttk.Entry(f_sec_multi, textvariable=self.t2_sector_ranges_text, width=26)
        e_sec_multi.pack(side="left")
        lbl_sec_ex = ttk.Label(f_sec_multi, text=self.tr("lbl_t2_sector_example"))
        lbl_sec_ex.pack(side="left")
        self._register_i18n_widget(lbl_sec_ex, "lbl_t2_sector_example")
        cb_sec_each = ttk.Checkbutton(f_sec_multi, text=self.tr("cb_t2_sec_save_each"), variable=self.t2_sector_save_each)
        cb_sec_each.pack(side="left", padx=(6, 0))
        self._register_i18n_widget(cb_sec_each, "cb_t2_sec_save_each")
        cb_sec_sum = ttk.Checkbutton(f_sec_multi, text=self.tr("cb_t2_sec_save_sum"), variable=self.t2_sector_save_combined)
        cb_sec_sum.pack(side="left", padx=(4, 0))
        self._register_i18n_widget(cb_sec_sum, "cb_t2_sec_save_sum")

        f_tex = ttk.Frame(c3_grid); f_tex.grid(row=3, column=0, sticky="w")
        cb_tex = ttk.Checkbutton(f_tex, text=self.tr("cb_t2_texture"), variable=self.t2_mode_chi)
        cb_tex.pack(side="left")
        self._register_i18n_widget(cb_tex, "cb_t2_texture")
        ttk.Label(f_tex, text=" Q[").pack(side="left")
        e_qmin = ttk.Entry(f_tex, textvariable=self.t2_rad_qmin, width=4)
        e_qmin.pack(side="left")
        ttk.Label(f_tex, text=",").pack(side="left")
        e_qmax = ttk.Entry(f_tex, textvariable=self.t2_rad_qmax, width=4)
        e_qmax.pack(side="left")
        ttk.Label(f_tex, text="] A⁻¹").pack(side="left")
        btn_chi_preview = ttk.Button(f_tex, text=self.tr("btn_t2_chi_preview"), width=10, command=self.preview_ichi_window_t2)
        btn_chi_preview.pack(side="left", padx=(4, 0))
        self._register_i18n_widget(btn_chi_preview, "btn_t2_chi_preview")

        self.add_tooltip(cb_full, "tip_t2_full")
        self.add_tooltip(cb_sec, "tip_t2_sector")
        self.add_tooltip(e_sec_min, "tip_t2_sec_min")
        self.add_tooltip(e_sec_max, "tip_t2_sec_max")
        self.add_tooltip(btn_sec_preview, "tip_t2_sec_preview")
        self.add_tooltip(e_sec_multi, "tip_t2_sec_multi")
        self.add_tooltip(cb_sec_each, "tip_t2_sec_each")
        self.add_tooltip(cb_sec_sum, "tip_t2_sec_sum")
        self.add_tooltip(cb_tex, "tip_t2_texture")
        self.add_tooltip(e_qmin, "tip_t2_qmin")
        self.add_tooltip(e_qmax, "tip_t2_qmax")
        self.add_tooltip(btn_chi_preview, "tip_t2_chi_preview")

        # 4. 修正与执行策略
        adv_frame = ttk.Frame(p)
        adv_frame.pack(fill="x", padx=10, pady=(2, 4))

        c4 = ttk.LabelFrame(adv_frame, text=self.tr("lf_t2_correction"), style="Group.TLabelframe")
        c4.pack(side="left", fill="x", expand=True, padx=5)
        self._register_i18n_widget(c4, "lf_t2_correction")
        self.add_hint(c4, "hint_t2_correction", wraplength=480)

        c4_row1 = ttk.Frame(c4); c4_row1.pack(fill="x", pady=2)
        cb_solid = ttk.Checkbutton(c4_row1, text=self.tr("cb_t2_solid_angle"), variable=self.t2_apply_solid_angle)
        cb_solid.pack(side="left")
        self._register_i18n_widget(cb_solid, "cb_t2_solid_angle")
        lbl_err = ttk.Label(c4_row1, text=self.tr("lbl_t2_error_model"))
        lbl_err.pack(side="left", padx=(8, 2))
        self._register_i18n_widget(lbl_err, "lbl_t2_error_model")
        cb_err = ttk.Combobox(c4_row1, textvariable=self.t2_error_model, width=10, state="readonly")
        cb_err["values"] = ("azimuthal", "poisson", "none")
        cb_err.pack(side="left")
        ttk.Label(c4_row1, text="Polarization(-1~1):").pack(side="left", padx=(8, 2))
        e_pol = ttk.Entry(c4_row1, textvariable=self.t2_polarization, width=6)
        e_pol.pack(side="left")

        row_mask = self.add_file_row(c4, self.tr("lbl_t2_mask"), self.t2_mask_path, "*.tif *.tiff *.edf *.npy")
        row_flat = self.add_file_row(c4, self.tr("lbl_t2_flat"), self.t2_flat_path, "*.tif *.tiff *.edf *.npy")

        self.add_tooltip(cb_solid, "tip_t2_solid_angle")
        self.add_tooltip(cb_err, "tip_t2_error_model")
        self.add_tooltip(e_pol, "tip_t2_polarization")
        self.add_tooltip(row_mask["entry"], "tip_t2_mask")
        self.add_tooltip(row_flat["entry"], "tip_t2_flat")

        c5 = ttk.LabelFrame(adv_frame, text=self.tr("lf_t2_execution"), style="Group.TLabelframe")
        c5.pack(side="left", fill="x", expand=True, padx=5)
        self._register_i18n_widget(c5, "lf_t2_execution")
        self.add_hint(c5, "hint_t2_execution", wraplength=480)

        row_ref = ttk.Frame(c5); row_ref.pack(fill="x")
        rb_ref_fixed = ttk.Radiobutton(row_ref, text=self.tr("rb_t2_ref_fixed"), variable=self.t2_ref_mode, value="fixed")
        rb_ref_fixed.pack(side="left")
        self._register_i18n_widget(rb_ref_fixed, "rb_t2_ref_fixed")
        rb_ref_auto = ttk.Radiobutton(row_ref, text=self.tr("rb_t2_ref_auto"), variable=self.t2_ref_mode, value="auto")
        rb_ref_auto.pack(side="left", padx=(8, 0))
        self._register_i18n_widget(rb_ref_auto, "rb_t2_ref_auto")

        row_lib = ttk.Frame(c5); row_lib.pack(fill="x", pady=2)
        btn_bg_lib = ttk.Button(row_lib, text=self.tr("btn_t2_bg_lib"), command=self.add_bg_library_files)
        btn_bg_lib.pack(side="left")
        self._register_i18n_widget(btn_bg_lib, "btn_t2_bg_lib")
        btn_dark_lib = ttk.Button(row_lib, text=self.tr("btn_t2_dark_lib"), command=self.add_dark_library_files)
        btn_dark_lib.pack(side="left", padx=(5, 0))
        self._register_i18n_widget(btn_dark_lib, "btn_t2_dark_lib")
        btn_clear_lib = ttk.Button(row_lib, text=self.tr("btn_t2_clear_lib"), command=self.clear_reference_libraries)
        btn_clear_lib.pack(side="left", padx=(5, 0))
        self._register_i18n_widget(btn_clear_lib, "btn_t2_clear_lib")

        row_lib_info = ttk.Frame(c5); row_lib_info.pack(fill="x")
        ttk.Label(row_lib_info, textvariable=self.t2_bg_lib_info, style="Hint.TLabel").pack(side="left")
        ttk.Label(row_lib_info, textvariable=self.t2_dark_lib_info, style="Hint.TLabel").pack(side="left", padx=(10, 0))

        row_exec = ttk.Frame(c5); row_exec.pack(fill="x", pady=2)
        lbl_wk = ttk.Label(row_exec, text=self.tr("lbl_t2_workers"))
        lbl_wk.pack(side="left")
        self._register_i18n_widget(lbl_wk, "lbl_t2_workers")
        e_workers = ttk.Entry(row_exec, textvariable=self.t2_workers, width=4)
        e_workers.pack(side="left")
        cb_resume = ttk.Checkbutton(row_exec, text=self.tr("cb_t2_resume"), variable=self.t2_resume_enabled)
        cb_resume.pack(side="left", padx=(8, 0))
        self._register_i18n_widget(cb_resume, "cb_t2_resume")
        cb_overwrite = ttk.Checkbutton(row_exec, text=self.tr("cb_t2_overwrite"), variable=self.t2_overwrite)
        cb_overwrite.pack(side="left", padx=(8, 0))
        self._register_i18n_widget(cb_overwrite, "cb_t2_overwrite")

        row_strict = ttk.Frame(c5); row_strict.pack(fill="x")
        cb_strict = ttk.Checkbutton(row_strict, text=self.tr("cb_t2_strict"), variable=self.t2_strict_instrument)
        cb_strict.pack(side="left")
        self._register_i18n_widget(cb_strict, "cb_t2_strict")
        lbl_tol = ttk.Label(row_strict, text=self.tr("lbl_t2_tolerance"))
        lbl_tol.pack(side="left", padx=(8, 2))
        self._register_i18n_widget(lbl_tol, "lbl_t2_tolerance")
        e_tol = ttk.Entry(row_strict, textvariable=self.t2_instr_tol_pct, width=5)
        e_tol.pack(side="left")

        self.add_tooltip(rb_ref_fixed, "tip_t2_ref_fixed")
        self.add_tooltip(rb_ref_auto, "tip_t2_ref_auto")
        self.add_tooltip(btn_bg_lib, "tip_t2_bg_lib")
        self.add_tooltip(btn_dark_lib, "tip_t2_dark_lib")
        self.add_tooltip(btn_clear_lib, "tip_t2_clear_lib")
        self.add_tooltip(e_workers, "tip_t2_workers")
        self.add_tooltip(cb_resume, "tip_t2_resume")
        self.add_tooltip(cb_overwrite, "tip_t2_overwrite")
        self.add_tooltip(cb_strict, "tip_t2_strict")
        self.add_tooltip(e_tol, "tip_t2_tolerance")

        # --- α-scaling and output format row ---
        row_alpha_fmt = ttk.Frame(c5); row_alpha_fmt.pack(fill="x", pady=(4, 0))
        cb_alpha = ttk.Checkbutton(row_alpha_fmt, text=self.tr("cb_t2_buffer_enable"), variable=self.t2_alpha_enabled)
        cb_alpha.pack(side="left")
        self._register_i18n_widget(cb_alpha, "cb_t2_buffer_enable")
        lbl_a2 = ttk.Label(row_alpha_fmt, text=self.tr("lbl_t2_alpha"))
        lbl_a2.pack(side="left", padx=(8, 2))
        self._register_i18n_widget(lbl_a2, "lbl_t2_alpha")
        ttk.Entry(row_alpha_fmt, textvariable=self.t2_alpha, width=6).pack(side="left")

        row_fmt2 = ttk.Frame(c5); row_fmt2.pack(fill="x", pady=(2, 0))
        lbl_ofmt2 = ttk.Label(row_fmt2, text=self.tr("lbl_output_format"))
        lbl_ofmt2.pack(side="left")
        self._register_i18n_widget(lbl_ofmt2, "lbl_output_format")
        self.t2_fmt_combo = ttk.Combobox(
            row_fmt2,
            textvariable=self.t2_output_format,
            values=["tsv", "csv", "cansas_xml", "nxcansas_h5"],
            width=18,
            state="readonly",
        )
        self.t2_fmt_combo.current(0)
        self.t2_fmt_combo.pack(side="left", padx=5)

        # --- List ---
        mid_frame = ttk.LabelFrame(p, text=self.tr("t2_mid_title"), style="Group.TLabelframe")
        self._register_i18n_widget(mid_frame, "t2_mid_title")
        mid_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.add_hint(mid_frame, "hint_t2_queue")
        
        tb = ttk.Frame(mid_frame); tb.pack(fill="x")
        btn_add = ttk.Button(tb, text=self.tr("t2_add_btn"), command=self.add_batch_files)
        self._register_i18n_widget(btn_add, "t2_add_btn")
        btn_add.pack(side="left")
        btn_clear = ttk.Button(tb, text=self.tr("t2_clear_btn"), command=self.clear_batch_files)
        self._register_i18n_widget(btn_clear, "t2_clear_btn")
        btn_clear.pack(side="left")
        btn_check = ttk.Button(tb, text=self.tr("t2_check_btn"), command=self.dry_run, style="Accent.TButton")
        self._register_i18n_widget(btn_check, "t2_check_btn")
        btn_check.pack(side="right", padx=10)
        self.add_tooltip(btn_add, "tip_t2_add")
        self.add_tooltip(btn_clear, "tip_t2_clear")
        self.add_tooltip(btn_check, "tip_t2_check")

        self.t2_queue_info = tk.StringVar(value=self._fmt_queue_info(0, 0))
        lbl_queue = ttk.Label(mid_frame, textvariable=self.t2_queue_info, style="Hint.TLabel")
        lbl_queue.pack(anchor="w", padx=5, pady=(2, 0))

        self.lb_batch = tk.Listbox(mid_frame, height=8)
        self.lb_batch.pack(fill="both", expand=True, padx=5, pady=5)
        self._register_native_widget(self.lb_batch)
        self.add_tooltip(self.lb_batch, "tip_t2_listbox")

        # --- Action ---
        bot_frame = ttk.Frame(p)
        bot_frame.pack(fill="x", padx=10, pady=10)
        btn_run = ttk.Button(bot_frame, text=self.tr("t2_run_btn"), command=self.run_batch, style="Accent.TButton")
        self._register_i18n_widget(btn_run, "t2_run_btn")
        btn_run.pack(fill="x", ipady=5)
        self.prog_bar = ttk.Progressbar(bot_frame, mode="determinate")
        self.prog_bar.pack(fill="x", pady=5)
        row_out_dir = self.add_dir_row(bot_frame, self.tr("lbl_t2_outdir"), self.t2_output_root)
        self.add_tooltip(btn_run, "tip_t2_run")
        self.add_tooltip(self.prog_bar, "tip_t2_progress")
        self.add_tooltip(row_out_dir["entry"], "tip_t2_outdir")

        self.t2_out_hint_var = tk.StringVar(value=f"{self.tr('out_auto_prefix')}: processed_robust_1d_full")
        lbl_out = ttk.Label(bot_frame, textvariable=self.t2_out_hint_var, style="Hint.TLabel")
        lbl_out.pack(anchor="w")
        self.add_tooltip(lbl_out, "tip_t2_out_label")

        self.t2_mode_full.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_mode_sector.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_mode_chi.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_sector_ranges_text.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_sector_save_each.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_sector_save_combined.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_output_root.trace_add("write", lambda *_: self.refresh_queue_status())
        self.refresh_queue_status()

    # =========================================================================
    # TAB 3: External 1D -> Absolute Intensity
    # =========================================================================
    def init_tab3_external_1d(self):
        p = self._make_scrollable_frame(self.tab3)

        self.t3_files = []
        self.t3_pipeline_mode = tk.StringVar(value="scaled")
        self.t3_corr_mode = tk.StringVar(value="k_over_d")
        self.t3_fixed_thk = tk.DoubleVar(value=1.0)
        self.t3_x_mode = tk.StringVar(value="auto")
        self.t3_meta_csv_path = tk.StringVar()
        self.t3_bg1d_path = tk.StringVar()
        self.t3_dark1d_path = tk.StringVar()
        self.t3_output_root = tk.StringVar(value="")
        self.t3_use_meta_thk = tk.BooleanVar(value=True)
        self.t3_sample_exp = tk.DoubleVar(value=1.0)
        self.t3_sample_i0 = tk.DoubleVar(value=1.0)
        self.t3_sample_t = tk.DoubleVar(value=1.0)
        self.t3_bg_exp = tk.DoubleVar(value=1.0)
        self.t3_bg_i0 = tk.DoubleVar(value=1.0)
        self.t3_bg_t = tk.DoubleVar(value=1.0)
        self.t3_sync_bg_from_global = tk.BooleanVar(value=True)
        self.t3_bg_exp.set(self.global_vars["bg_exp"].get())
        self.t3_bg_i0.set(self.global_vars["bg_i0"].get())
        self.t3_bg_t.set(self.global_vars["bg_t"].get())
        self.t3_resume_enabled = tk.BooleanVar(value=True)
        self.t3_overwrite = tk.BooleanVar(value=False)
        self.t3_queue_info = tk.StringVar(value=self._fmt_queue_info(0, 0))
        self.t3_out_hint = tk.StringVar(value=f"{self.tr('out_auto_prefix')}: processed_external_1d_abs")

        f_guide = ttk.LabelFrame(p, text=self.tr("t3_guide_title"), style="Group.TLabelframe")
        self._register_i18n_widget(f_guide, "t3_guide_title")
        f_guide.pack(fill="x", padx=10, pady=(8, 3))
        guide = self.tr("t3_guide_text")
        lbl_guide = ttk.Label(f_guide, text=guide, justify="left", style="Hint.TLabel")
        self._register_i18n_widget(lbl_guide, "t3_guide_text")
        lbl_guide.pack(fill="x", padx=4, pady=3)
        self.add_tooltip(lbl_guide, "tip_t3_guide")

        top = ttk.Frame(p)
        top.pack(fill="x", padx=10, pady=5)

        c1 = ttk.LabelFrame(top, text=self.tr("lf_t3_global"), style="Group.TLabelframe")
        c1.pack(side="left", fill="y", padx=5)
        self._register_i18n_widget(c1, "lf_t3_global")
        self.add_hint(c1, "hint_t3_global", wraplength=380)

        c1_grid = ttk.Frame(c1)
        c1_grid.pack(fill="x")
        lbl_k3 = ttk.Label(c1_grid, text=self.tr("lbl_t3_k_factor"))
        lbl_k3.grid(row=0, column=0, sticky="e")
        self._register_i18n_widget(lbl_k3, "lbl_t3_k_factor")
        e_k = ttk.Entry(c1_grid, textvariable=self.global_vars["k_factor"], width=10)
        e_k.grid(row=0, column=1, padx=5, pady=1, sticky="w")
        lbl_pl = ttk.Label(c1_grid, text=self.tr("lbl_t3_pipeline"))
        lbl_pl.grid(row=1, column=0, sticky="e")
        self._register_i18n_widget(lbl_pl, "lbl_t3_pipeline")
        rb_scaled = ttk.Radiobutton(
            c1_grid, text=self.tr("rb_t3_scaled"), variable=self.t3_pipeline_mode, value="scaled"
        )
        rb_scaled.grid(row=1, column=1, sticky="w")
        self._register_i18n_widget(rb_scaled, "rb_t3_scaled")
        rb_raw = ttk.Radiobutton(
            c1_grid, text=self.tr("rb_t3_raw"), variable=self.t3_pipeline_mode, value="raw"
        )
        rb_raw.grid(row=2, column=1, sticky="w")
        self._register_i18n_widget(rb_raw, "rb_t3_raw")

        rb_kd = ttk.Radiobutton(
            c1_grid,
            text=self.tr("rb_t3_kd_formula"),
            variable=self.t3_corr_mode,
            value="k_over_d",
        )
        rb_kd.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 1))
        self._register_i18n_widget(rb_kd, "rb_t3_kd_formula")
        lbl_thk = ttk.Label(c1_grid, text=self.tr("lbl_t3_thk"))
        lbl_thk.grid(row=4, column=0, sticky="e")
        self._register_i18n_widget(lbl_thk, "lbl_t3_thk")
        e_thk = ttk.Entry(c1_grid, textvariable=self.t3_fixed_thk, width=8)
        e_thk.grid(row=4, column=1, padx=5, pady=1, sticky="w")

        rb_k = ttk.Radiobutton(
            c1_grid,
            text=self.tr("rb_t3_k_formula"),
            variable=self.t3_corr_mode,
            value="k_only",
        )
        rb_k.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 1))
        self._register_i18n_widget(rb_k, "rb_t3_k_formula")

        lbl_xt = ttk.Label(c1_grid, text=self.tr("lbl_t3_x_type"))
        lbl_xt.grid(row=6, column=0, sticky="e")
        self._register_i18n_widget(lbl_xt, "lbl_t3_x_type")
        cb_x = ttk.Combobox(c1_grid, textvariable=self.t3_x_mode, width=12, state="readonly")
        cb_x["values"] = ("auto", "q_A^-1", "chi_deg")
        cb_x.grid(row=6, column=1, padx=5, pady=1, sticky="w")
        lbl_i0_3 = ttk.Label(c1_grid, text=self.tr("lbl_t3_i0_semantic"), style="Hint.TLabel")
        lbl_i0_3.grid(row=7, column=0, sticky="e")
        self._register_i18n_widget(lbl_i0_3, "lbl_t3_i0_semantic")
        ttk.Label(c1_grid, textvariable=self.global_vars["monitor_mode"], style="Hint.TLabel").grid(row=7, column=1, sticky="w")

        self.add_tooltip(e_k, "tip_t3_k")
        self.add_tooltip(rb_scaled, "tip_t3_scaled")
        self.add_tooltip(rb_raw, "tip_t3_raw")
        self.add_tooltip(rb_kd, "tip_t3_kd")
        self.add_tooltip(e_thk, "tip_t3_thk")
        self.add_tooltip(rb_k, "tip_t3_k_only")
        self.add_tooltip(cb_x, "tip_t3_x_mode")

        c2 = ttk.LabelFrame(top, text=self.tr("lf_t3_execution"), style="Group.TLabelframe")
        c2.pack(side="left", fill="y", padx=5)
        self._register_i18n_widget(c2, "lf_t3_execution")
        self.add_hint(c2, "hint_t3_execution", wraplength=320)
        row_exec = ttk.Frame(c2)
        row_exec.pack(fill="x")
        cb_resume = ttk.Checkbutton(c2, text=self.tr("cb_t3_resume"), variable=self.t3_resume_enabled)
        cb_resume.pack(anchor="w")
        self._register_i18n_widget(cb_resume, "cb_t3_resume")
        cb_overwrite = ttk.Checkbutton(c2, text=self.tr("cb_t3_overwrite"), variable=self.t3_overwrite)
        cb_overwrite.pack(anchor="w")
        self._register_i18n_widget(cb_overwrite, "cb_t3_overwrite")
        lbl_fmt = ttk.Label(
            row_exec,
            text=self.tr("lbl_t3_formats"),
            style="Hint.TLabel",
            wraplength=320,
            justify="left",
        )
        lbl_fmt.pack(anchor="w")
        self._register_i18n_widget(lbl_fmt, "lbl_t3_formats")
        self.add_tooltip(cb_resume, "tip_t3_resume")
        self.add_tooltip(cb_overwrite, "tip_t3_overwrite")

        c3 = ttk.LabelFrame(top, text=self.tr("lf_t3_raw_params"), style="Group.TLabelframe")
        c3.pack(side="left", fill="y", padx=5)
        self._register_i18n_widget(c3, "lf_t3_raw_params")
        self.add_hint(c3, "hint_t3_raw", wraplength=420)

        row_meta = self.add_file_row(c3, "Metadata CSV:", self.t3_meta_csv_path, "*.csv")
        row_bg = self.add_file_row(c3, self.tr("lbl_t3_bg1d_file"), self.t3_bg1d_path, "*.dat *.txt *.chi *.csv")
        row_dark = self.add_file_row(c3, self.tr("lbl_t3_dark1d_file"), self.t3_dark1d_path, "*.dat *.txt *.chi *.csv")

        row_meta_ops = ttk.Frame(c3)
        row_meta_ops.pack(fill="x", pady=(1, 1))
        btn_meta_from_batch = ttk.Button(
            row_meta_ops,
            text=self.tr("btn_t3_meta_from_batch"),
            command=self.t3_make_meta_from_batch_report,
        )
        btn_meta_from_batch.pack(side="left", padx=(3, 0))
        self._register_i18n_widget(btn_meta_from_batch, "btn_t3_meta_from_batch")

        self.add_tooltip(row_meta["entry"], "tip_t3_meta")
        self.add_tooltip(row_bg["entry"], "tip_t3_bg1d")
        self.add_tooltip(row_dark["entry"], "tip_t3_dark1d")
        self.add_tooltip(btn_meta_from_batch, "tip_t3_meta_from_batch")

        cb_meta_thk = ttk.Checkbutton(c3, text=self.tr("cb_t3_meta_thk"), variable=self.t3_use_meta_thk)
        cb_meta_thk.pack(anchor="w", padx=3, pady=(2, 1))
        self._register_i18n_widget(cb_meta_thk, "cb_t3_meta_thk")
        self.add_tooltip(cb_meta_thk, "tip_t3_meta_thk")
        cb_sync_bg = ttk.Checkbutton(
            c3,
            text=self.tr("cb_t3_sync_bg"),
            variable=self.t3_sync_bg_from_global,
            command=self.on_t3_sync_bg_toggle,
        )
        cb_sync_bg.pack(anchor="w", padx=3, pady=(0, 1))
        self._register_i18n_widget(cb_sync_bg, "cb_t3_sync_bg")
        self.add_tooltip(cb_sync_bg, "tip_t3_sync_bg")

        f_sample = ttk.Frame(c3)
        f_sample.pack(fill="x", pady=(2, 1))
        lbl_sp = ttk.Label(f_sample, text=self.tr("lbl_t3_sample_params"), style="Hint.TLabel")
        lbl_sp.grid(row=0, column=0, columnspan=6, sticky="w")
        self._register_i18n_widget(lbl_sp, "lbl_t3_sample_params")
        ttk.Label(f_sample, text="exp").grid(row=1, column=0, sticky="e")
        ttk.Entry(f_sample, textvariable=self.t3_sample_exp, width=7).grid(row=1, column=1, padx=2)
        ttk.Label(f_sample, text="i0").grid(row=1, column=2, sticky="e")
        ttk.Entry(f_sample, textvariable=self.t3_sample_i0, width=7).grid(row=1, column=3, padx=2)
        ttk.Label(f_sample, text="T").grid(row=1, column=4, sticky="e")
        ttk.Entry(f_sample, textvariable=self.t3_sample_t, width=7).grid(row=1, column=5, padx=2)

        f_bg = ttk.Frame(c3)
        f_bg.pack(fill="x", pady=(2, 1))
        lbl_bp = ttk.Label(f_bg, text=self.tr("lbl_t3_bg_params"), style="Hint.TLabel")
        lbl_bp.grid(row=0, column=0, columnspan=6, sticky="w")
        self._register_i18n_widget(lbl_bp, "lbl_t3_bg_params")
        ttk.Label(f_bg, text="exp").grid(row=1, column=0, sticky="e")
        self.t3_bg_entry_exp = ttk.Entry(f_bg, textvariable=self.t3_bg_exp, width=7)
        self.t3_bg_entry_exp.grid(row=1, column=1, padx=2)
        ttk.Label(f_bg, text="i0").grid(row=1, column=2, sticky="e")
        self.t3_bg_entry_i0 = ttk.Entry(f_bg, textvariable=self.t3_bg_i0, width=7)
        self.t3_bg_entry_i0.grid(row=1, column=3, padx=2)
        ttk.Label(f_bg, text="T").grid(row=1, column=4, sticky="e")
        self.t3_bg_entry_t = ttk.Entry(f_bg, textvariable=self.t3_bg_t, width=7)
        self.t3_bg_entry_t.grid(row=1, column=5, padx=2)

        # ---- Buffer/Solvent subtraction panel ----
        self.t3_buffer_enabled = tk.BooleanVar(value=False)
        self.t3_buffer_path = tk.StringVar()
        self.t3_alpha = tk.DoubleVar(value=1.0)
        self.t3_buffer_status = tk.StringVar(value=self.tr("lbl_t3_buffer_status"))

        buf_frame = ttk.LabelFrame(top, text=self.tr("lf_t3_buffer"), style="Group.TLabelframe")
        buf_frame.pack(side="left", fill="y", padx=5)
        self._register_i18n_widget(buf_frame, "lf_t3_buffer")
        cb_buf = ttk.Checkbutton(buf_frame, text=self.tr("cb_t3_buffer_enable"), variable=self.t3_buffer_enabled)
        cb_buf.pack(anchor="w", padx=3, pady=2)
        self._register_i18n_widget(cb_buf, "cb_t3_buffer_enable")
        row_buf = self.add_file_row(buf_frame, self.tr("lbl_t3_buffer_file"), self.t3_buffer_path, "*.dat *.txt *.csv *.xml")
        row_alpha = ttk.Frame(buf_frame); row_alpha.pack(fill="x", pady=1)
        lbl_alpha = ttk.Label(row_alpha, text=self.tr("lbl_t3_alpha"), width=15, anchor="e")
        lbl_alpha.pack(side="left")
        self._register_i18n_widget(lbl_alpha, "lbl_t3_alpha")
        ttk.Entry(row_alpha, textvariable=self.t3_alpha, width=8).pack(side="left", padx=5)
        ttk.Label(buf_frame, textvariable=self.t3_buffer_status, style="Hint.TLabel").pack(anchor="w", padx=3)

        # ---- Output format selector ----
        self.t3_output_format = tk.StringVar(value="tsv")
        fmt_row = ttk.Frame(buf_frame); fmt_row.pack(fill="x", pady=(4, 2))
        lbl_ofmt = ttk.Label(fmt_row, text=self.tr("lbl_output_format"), width=15, anchor="e")
        lbl_ofmt.pack(side="left")
        self._register_i18n_widget(lbl_ofmt, "lbl_output_format")
        self.t3_fmt_combo = ttk.Combobox(
            fmt_row,
            textvariable=self.t3_output_format,
            values=["tsv", "csv", "cansas_xml", "nxcansas_h5"],
            width=18,
            state="readonly",
        )
        self.t3_fmt_combo.current(0)
        self.t3_fmt_combo.pack(side="left", padx=5)

        mid = ttk.LabelFrame(p, text=self.tr("t3_mid_title"), style="Group.TLabelframe")
        self._register_i18n_widget(mid, "t3_mid_title")
        mid.pack(fill="both", expand=True, padx=10, pady=5)
        self.add_hint(mid, "hint_t3_queue")

        tb = ttk.Frame(mid)
        tb.pack(fill="x")
        btn_add = ttk.Button(tb, text=self.tr("t3_add_btn"), command=self.add_external_1d_files)
        self._register_i18n_widget(btn_add, "t3_add_btn")
        btn_add.pack(side="left")
        btn_clear = ttk.Button(tb, text=self.tr("t3_clear_btn"), command=self.clear_external_1d_files)
        self._register_i18n_widget(btn_clear, "t3_clear_btn")
        btn_clear.pack(side="left", padx=(4, 0))
        btn_check = ttk.Button(tb, text=self.tr("t3_check_btn"), command=self.dry_run_external_1d)
        self._register_i18n_widget(btn_check, "t3_check_btn")
        btn_check.pack(side="right")
        self.add_tooltip(btn_add, "tip_t3_add")
        self.add_tooltip(btn_clear, "tip_t3_clear")
        self.add_tooltip(btn_check, "tip_t3_check")

        ttk.Label(mid, textvariable=self.t3_queue_info, style="Hint.TLabel").pack(anchor="w", padx=5, pady=(2, 0))
        self.lb_ext1d = tk.Listbox(mid, height=9)
        self.lb_ext1d.pack(fill="both", expand=True, padx=5, pady=5)
        self._register_native_widget(self.lb_ext1d)
        self.add_tooltip(self.lb_ext1d, "tip_t3_listbox")

        bot = ttk.Frame(p)
        bot.pack(fill="x", padx=10, pady=10)
        btn_run = ttk.Button(bot, text=self.tr("t3_run_btn"), command=self.run_external_1d_batch, style="Accent.TButton")
        self._register_i18n_widget(btn_run, "t3_run_btn")
        btn_run.pack(fill="x", ipady=5)
        self.t3_prog_bar = ttk.Progressbar(bot, mode="determinate")
        self.t3_prog_bar.pack(fill="x", pady=5)
        row_out_dir = self.add_dir_row(bot, self.tr("lbl_t3_outdir"), self.t3_output_root)
        ttk.Label(bot, textvariable=self.t3_out_hint, style="Hint.TLabel").pack(anchor="w")
        self.add_tooltip(btn_run, "tip_t3_run")
        self.add_tooltip(self.t3_prog_bar, "tip_t3_progress")
        self.add_tooltip(row_out_dir["entry"], "tip_t3_outdir")

        self.global_vars["bg_exp"].trace_add("write", self.on_global_bg_changed_for_t3)
        self.global_vars["bg_i0"].trace_add("write", self.on_global_bg_changed_for_t3)
        self.global_vars["bg_t"].trace_add("write", self.on_global_bg_changed_for_t3)
        self.t3_output_root.trace_add("write", lambda *_: self.refresh_external_1d_status())
        self.on_t3_sync_bg_toggle()
        self.refresh_external_1d_status()

    def add_external_1d_files(self):
        fs = filedialog.askopenfilenames(
            filetypes=[("1D Files", "*.dat *.txt *.chi *.csv"), ("All Files", "*.*")]
        )
        for f in fs:
            if f not in self.t3_files:
                self.t3_files.append(f)
                self.lb_ext1d.insert(tk.END, Path(f).name)
        self.refresh_external_1d_status()

    def clear_external_1d_files(self):
        self.t3_files = []
        self.lb_ext1d.delete(0, tk.END)
        self.refresh_external_1d_status()

    def refresh_external_1d_status(self):
        if hasattr(self, "t3_queue_info"):
            total = len(getattr(self, "t3_files", []))
            uniq = len(dict.fromkeys(getattr(self, "t3_files", [])))
            self.t3_queue_info.set(self._fmt_queue_info(total, uniq))

        if hasattr(self, "t3_out_hint"):
            custom_root = self.t3_output_root.get().strip() if hasattr(self, "t3_output_root") else ""
            if custom_root:
                self.t3_out_hint.set(
                    f"{self.tr('out_write_prefix')}: {custom_root}\\processed_external_1d_abs "
                    f"(报告: {custom_root}\\processed_external_1d_reports)"
                )
            else:
                self.t3_out_hint.set(f"{self.tr('out_auto_prefix')}: processed_external_1d_abs")

    def sync_t3_bg_params_from_global(self):
        if not hasattr(self, "global_vars"):
            return
        try:
            self.t3_bg_exp.set(float(self.global_vars["bg_exp"].get()))
            self.t3_bg_i0.set(float(self.global_vars["bg_i0"].get()))
            self.t3_bg_t.set(float(self.global_vars["bg_t"].get()))
        except Exception:
            pass

    def on_global_bg_changed_for_t3(self, *_):
        if hasattr(self, "t3_sync_bg_from_global") and bool(self.t3_sync_bg_from_global.get()):
            self.sync_t3_bg_params_from_global()

    def on_t3_sync_bg_toggle(self):
        follow = bool(self.t3_sync_bg_from_global.get()) if hasattr(self, "t3_sync_bg_from_global") else False
        if follow:
            self.sync_t3_bg_params_from_global()
        state = "disabled" if follow else "normal"
        for w in [
            getattr(self, "t3_bg_entry_exp", None),
            getattr(self, "t3_bg_entry_i0", None),
            getattr(self, "t3_bg_entry_t", None),
        ]:
            if w is not None:
                try:
                    w.configure(state=state)
                except Exception:
                    pass

    def read_external_1d_profile(self, path):
        dfs = []
        errs = []
        read_trials = [
            {"sep": None, "engine": "python", "comment": "#"},
            {"sep": r"[,\s;]+", "engine": "python", "comment": "#"},
            {"sep": r"[,\s;]+", "engine": "python", "comment": "#", "header": None},
        ]

        for kw in read_trials:
            try:
                df = pd.read_csv(path, **kw)
                if df is not None and not df.empty and df.shape[1] >= 2:
                    dfs.append(df)
            except Exception as e:
                errs.append(str(e))

        if not dfs:
            raise ValueError(f"无法解析文件: {Path(path).name} ({'; '.join(errs[:2])})")

        best = None
        best_pts = -1

        for df in dfs:
            numeric_cols = {}
            for col in df.columns:
                s = pd.to_numeric(df[col], errors="coerce")
                arr = s.to_numpy(dtype=np.float64, na_value=np.nan)
                cnt = int(np.isfinite(arr).sum())
                if cnt >= 3:
                    numeric_cols[col] = s

            if len(numeric_cols) < 2:
                continue

            cols = list(numeric_cols.keys())

            def clean_name(value):
                return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())

            def match_score(name, exact, prefixes=(), suffixes=()):
                if name in exact:
                    return 300
                if any(name.startswith(prefix) and len(name) > len(prefix) for prefix in prefixes):
                    return 200
                if any(name.endswith(suffix) and len(name) > len(suffix) for suffix in suffixes):
                    return 150
                return 0

            def pick_named(used, *, exact, prefixes=(), suffixes=()):
                best = None
                best_score = 0
                for c in cols:
                    if c in used:
                        continue
                    score = match_score(clean_name(c), exact, prefixes, suffixes)
                    if score > best_score:
                        best = c
                        best_score = score
                return best, best_score > 0

            x_col, x_named = pick_named(
                set(),
                exact={"q", "chi", "radial", "2theta", "twotheta", "s", "x"},
                prefixes=("q", "chi", "radial", "twotheta"),
                suffixes=("q",),
            )
            if x_col is None:
                x_col = cols[0]

            i_col, i_named = pick_named(
                {x_col},
                exact={"i", "intensity", "irel", "iabs", "signal", "count", "counts", "y"},
                prefixes=("intensity", "signal", "count", "irel", "iabs"),
                suffixes=("intensity",),
            )
            if i_col is None:
                i_col = next((c for c in cols if c != x_col), None)
            if i_col is None:
                continue

            err_col, err_named = pick_named(
                {x_col, i_col},
                exact={"err", "error", "errors", "sigma", "std", "stdev", "unc", "uncertainty", "idev"},
                prefixes=("err", "error", "sigma", "std", "unc", "idev"),
                suffixes=("error", "sigma", "uncertainty"),
            )
            if err_col is None and len(cols) >= 3:
                err_col = next((c for c in cols if c not in {x_col, i_col}), None)

            x = pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
            i_rel = pd.to_numeric(df[i_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
            mask = np.isfinite(x) & np.isfinite(i_rel)
            if int(mask.sum()) < 3:
                continue

            x = x[mask]
            i_rel = i_rel[mask]
            if err_col is not None:
                err = pd.to_numeric(df[err_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)[mask]
                err = np.where(np.isfinite(err), err, np.nan)
            else:
                err = np.full_like(i_rel, np.nan, dtype=np.float64)

            order = np.argsort(x)
            x = x[order]
            i_rel = i_rel[order]
            err = err[order]

            pts = int(x.size)
            semantic_score = int(x_named) * 2 + int(i_named) * 3 + int(err_named)
            if (pts, semantic_score) > (best_pts, best.get("_semantic_score", -1) if best else -1):
                best_pts = pts
                best = {
                    "x": x,
                    "i_rel": i_rel,
                    "err_rel": err,
                    "x_col": str(x_col),
                    "i_col": str(i_col),
                    "err_col": str(err_col) if err_col is not None else "",
                    "_semantic_score": semantic_score,
                }

        if best is None:
            raise ValueError(f"无法从 {Path(path).name} 识别有效数值列（至少需要 X 和 I 两列）")
        best.pop("_semantic_score", None)
        return best

    def _regularize_xy_triplet(self, x, y, e=None, min_points=3, name="profile"):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        if e is None:
            e = np.full_like(y, np.nan, dtype=np.float64)
        else:
            e = np.asarray(e, dtype=np.float64)

        if x.shape != y.shape:
            raise ValueError(f"{name}: x/y 形状不一致。")
        if e.shape != x.shape:
            e = np.full_like(y, np.nan, dtype=np.float64)

        mask = np.isfinite(x) & np.isfinite(y)
        x = x[mask]
        y = y[mask]
        e = e[mask]
        if x.size < min_points:
            raise ValueError(f"{name}: 有效点数不足（<{min_points}）。")

        order = np.argsort(x)
        x = x[order]
        y = y[order]
        e = e[order]

        # Collapse duplicate x values by averaging to build a stable monotonic grid.
        ux, inv = np.unique(x, return_inverse=True)
        if ux.size != x.size:
            y_sum = np.zeros_like(ux, dtype=np.float64)
            cnt = np.zeros_like(ux, dtype=np.float64)
            e_sq_sum = np.zeros_like(ux, dtype=np.float64)
            e_cnt = np.zeros_like(ux, dtype=np.float64)
            for i, g in enumerate(inv):
                y_sum[g] += y[i]
                cnt[g] += 1.0
                if np.isfinite(e[i]):
                    e_sq_sum[g] += e[i] ** 2
                    e_cnt[g] += 1.0
            y = y_sum / np.clip(cnt, 1.0, None)
            # Proper error propagation for averaged duplicates:
            # sigma_avg = sqrt(sum(sigma_i^2)) / N
            e = np.where(
                e_cnt > 0,
                np.sqrt(e_sq_sum) / np.clip(e_cnt, 1.0, None),
                np.nan,
            )
            x = ux

        if x.size < min_points:
            raise ValueError(f"{name}: 去重后有效点数不足（<{min_points}）。")
        return x, y, e

    def infer_external_x_label(self, path, profile):
        mode = self.t3_x_mode.get().strip().lower()
        if mode == "q_a^-1":
            return "Q_A^-1"
        if mode == "chi_deg":
            return "Chi_deg"

        name = f"{profile.get('x_col', '')}".lower()
        fname = Path(path).name.lower()
        if ("chi" in name) or fname.endswith(".chi"):
            return "Chi_deg"
        return "Q_A^-1"

    def parse_mode_outputs(self, outputs_raw):
        if outputs_raw is None:
            return []
        if isinstance(outputs_raw, (int, float, np.number)) and not np.isfinite(outputs_raw):
            return []

        s = str(outputs_raw).strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return []

        out = []
        for part in s.split("|"):
            item = str(part).strip()
            if not item:
                continue
            m = re.match(
                r"^(1d_full|1d_sector(?:\[[^\]]+\])?|1d_sector_sum|radial_chi)\s*:\s*(.+)$",
                item,
                flags=re.IGNORECASE,
            )
            if m:
                item = m.group(2).strip()
            item = re.sub(r"\(existing\)\s*$", "", item, flags=re.IGNORECASE).strip()
            if item:
                out.append(item)
        return out

    def collect_external_meta_rows(self, df):
        if df is None or df.empty:
            return [], {}

        col_map = {}
        for c in df.columns:
            col_map[self._norm_key(c)] = c

        def pick(names):
            for n in names:
                if n in col_map:
                    return col_map[n]
            return None

        file_col = pick(["file", "filename", "name", "path", "sample", "samplename"])
        outputs_col = pick(["outputs", "output", "result", "results"])
        if file_col is None and outputs_col is None:
            raise ValueError("metadata CSV 缺少文件列（file/filename/name/path）或输出列（outputs）。")

        exp_col = pick(["exp", "exposure", "exposuretime", "exposures", "counttime", "time", "exposures"])
        mon_col = pick(["i0", "mon", "monitor", "beammonitor", "flux"])
        trans_col = pick(["trans", "transmission", "sampletransmission", "abs"])
        thk_mm_col = pick(["thkmm", "thicknessmm", "thickness", "dmm", "calcthkmm", "fixedthicknessmm"])
        thk_cm_col = pick(["thkcm", "thicknesscm", "dcm"])

        out_map = {}
        rows = []
        for _, row in df.iterrows():
            names = []

            if file_col is not None:
                raw_file = str(row.get(file_col, "")).strip()
                if raw_file:
                    names.append(raw_file)
            if outputs_col is not None:
                names.extend(self.parse_mode_outputs(row.get(outputs_col)))

            uniq_names = []
            seen = set()
            for nm in names:
                nm_s = str(nm).strip()
                if not nm_s:
                    continue
                nk = nm_s.lower()
                if nk in seen:
                    continue
                seen.add(nk)
                uniq_names.append(nm_s)

            if not uniq_names:
                continue

            raw_exp = row.get(exp_col) if exp_col is not None else None
            raw_mon = row.get(mon_col) if mon_col is not None else None
            raw_trans = row.get(trans_col) if trans_col is not None else None
            raw_thk_mm = row.get(thk_mm_col) if thk_mm_col is not None else None
            raw_thk_cm = row.get(thk_cm_col) if thk_cm_col is not None else None

            exp = self._extract_float(raw_exp)
            mon = self._extract_float(raw_mon)
            trans = self._extract_float(raw_trans)
            if trans is not None:
                trans = self._normalize_transmission(trans, raw=raw_trans, key=trans_col)

            thk_mm = self._extract_float(raw_thk_mm)
            if thk_mm is None:
                thk_cm = self._extract_float(raw_thk_cm)
                if thk_cm is not None:
                    thk_mm = thk_cm * 10.0

            meta = {"exp": exp, "mon": mon, "trans": trans, "thk_mm": thk_mm}
            for nm in uniq_names:
                p = Path(nm)
                aliases = {str(nm).lower(), p.name.lower(), p.stem.lower()}
                for a in aliases:
                    if a:
                        out_map[a] = meta
                rows.append({
                    "file": str(nm).strip(),
                    "exp": exp if exp is not None else np.nan,
                    "i0": mon if mon is not None else np.nan,
                    "trans": trans if trans is not None else np.nan,
                    "thk_mm": thk_mm if thk_mm is not None else np.nan,
                })

        if rows:
            df_rows = pd.DataFrame(rows)
            if "file" in df_rows.columns:
                df_rows["file"] = df_rows["file"].astype(str).str.strip()
                df_rows = df_rows[df_rows["file"] != ""]
                df_rows["_k"] = df_rows["file"].str.lower()
                df_rows = df_rows.drop_duplicates(subset=["_k"], keep="last").drop(columns=["_k"])
            rows = df_rows.to_dict("records")

        return rows, out_map

    def export_tab3_metadata_from_report(self, report_csv_path, stamp=None):
        report_path = Path(report_csv_path)
        if not report_path.exists():
            raise FileNotFoundError(f"未找到报告文件: {report_path}")

        try:
            df = pd.read_csv(report_path, sep=None, engine="python")
        except Exception:
            df = pd.read_csv(report_path)

        rows, _ = self.collect_external_meta_rows(df)
        if not rows:
            raise ValueError("未从报告中提取到可用 metadata 行。")

        out_df = pd.DataFrame(rows)
        for c in ["file", "exp", "i0", "trans", "thk_mm"]:
            if c not in out_df.columns:
                out_df[c] = np.nan
        out_df = out_df[["file", "exp", "i0", "trans", "thk_mm"]]

        out_df["file"] = out_df["file"].astype(str).str.strip()
        out_df = out_df[out_df["file"] != ""]
        if out_df.empty:
            raise ValueError("metadata 行为空：未识别到文件名。")

        out_df["_k"] = out_df["file"].str.lower()
        out_df = out_df.drop_duplicates(subset=["_k"], keep="last").drop(columns=["_k"])
        out_df = out_df.sort_values("file").reset_index(drop=True)

        if not stamp:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        out_dir = report_path.parent
        out_stamp = out_dir / f"metadata_for_tab3_{stamp}.csv"
        out_latest = out_dir / "metadata.csv"
        out_df.to_csv(out_stamp, index=False, encoding="utf-8-sig")
        out_df.to_csv(out_latest, index=False, encoding="utf-8-sig")
        return out_stamp, out_latest, int(len(out_df))

    def t3_make_meta_from_batch_report(self):
        try:
            report_path = filedialog.askopenfilename(
                filetypes=[("Batch Report", "batch_report_*.csv"), ("CSV", "*.csv"), ("All Files", "*.*")]
            )
            if not report_path:
                return
            out_stamp, out_latest, n_rows = self.export_tab3_metadata_from_report(report_path)
            self.t3_meta_csv_path.set(str(out_latest))
            messagebox.showinfo(
                "metadata 已生成",
                (
                    f"已从报告生成 metadata。\n"
                    f"行数: {n_rows}\n"
                    f"时间戳文件: {out_stamp.name}\n"
                    f"默认文件: {out_latest.name}\n"
                    f"Tab3 将使用: {out_latest}"
                ),
            )
        except Exception as e:
            self.show_error("msg_input_error_title", f"{e}\n{traceback.format_exc()}")

    def load_external_meta_map(self, csv_path):
        if not csv_path:
            return {}

        try:
            df = pd.read_csv(csv_path, sep=None, engine="python")
        except Exception:
            df = pd.read_csv(csv_path)

        if df is None or df.empty:
            return {}
        _, out_map = self.collect_external_meta_rows(df)
        return out_map

    def get_external_meta_for_file(self, meta_map, file_path):
        if not meta_map:
            return None
        p = Path(file_path)

        def norm_path(s):
            return str(s).strip().replace("\\", "/").lower()

        full_key = norm_path(file_path)
        if full_key in meta_map:
            return meta_map[full_key]

        # 兼容 metadata 使用相对路径（例如 sector_01/sample.dat），而实际文件是绝对路径。
        suffix_hits = []
        for k in meta_map.keys():
            ks = norm_path(k)
            if "/" not in ks:
                continue
            if full_key.endswith("/" + ks) or full_key.endswith(ks):
                suffix_hits.append((len(ks), k))
        if suffix_hits:
            suffix_hits.sort(reverse=True)
            return meta_map[suffix_hits[0][1]]

        candidates = [p.name.lower(), p.stem.lower()]
        for c in candidates:
            if c in meta_map:
                return meta_map[c]
        return None

    def parse_external_1d_header_meta(self, file_path):
        meta = {}
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for _ in range(200):
                    line = f.readline()
                    if not line:
                        break
                    s = line.strip()
                    if not s:
                        continue
                    if not s.startswith(("#", ";", "//")):
                        break
                    s = s.lstrip("#;/ ").strip()
                    if not s:
                        continue
                    if "=" in s:
                        k, v = s.split("=", 1)
                    elif ":" in s:
                        k, v = s.split(":", 1)
                    else:
                        parts = s.split(None, 1)
                        if len(parts) != 2:
                            continue
                        k, v = parts
                    nk = self._norm_key(k)
                    if nk:
                        meta[nk] = v.strip()
        except Exception:
            return {"exp": None, "mon": None, "trans": None, "thk_mm": None}

        exp_raw, exp_key = self.meta_get_raw(meta, ["exposuretime", "counttime", "acqtime", "exposure", "time", "exp"])
        mon_raw, _ = self.meta_get_raw(meta, ["monitor", "beammonitor", "ionchamber", "mon", "i0", "flux"])
        trans_raw, trans_key = self.meta_get_raw(meta, ["sampletransmission", "transmission", "trans", "abs"])
        thk_raw, _ = self.meta_get_raw(meta, ["thkmm", "thicknessmm", "thickness", "dmm"])

        exp = self._extract_float(exp_raw)
        if exp is not None:
            tag = f"{exp_key or ''} {exp_raw or ''}".lower()
            if "ms" in tag:
                exp /= 1000.0
            elif "us" in tag:
                exp /= 1_000_000.0
        mon = self._extract_float(mon_raw)
        trans = self._extract_float(trans_raw)
        if trans is not None:
            trans = self._normalize_transmission(trans, raw=trans_raw, key=trans_key)
        thk_mm = self._extract_float(thk_raw)

        return {"exp": exp, "mon": mon, "trans": trans, "thk_mm": thk_mm}

    def align_profile_to_x(self, x_target, ref_profile, name):
        x = np.asarray(x_target, dtype=np.float64)
        if not np.all(np.isfinite(x)):
            raise ValueError(f"{name} 目标 x 网格包含非有限值。")

        xr, yr, er = self._regularize_xy_triplet(
            ref_profile["x"],
            ref_profile["i_rel"],
            ref_profile.get("err_rel"),
            min_points=2,
            name=name,
        )

        if xr.size == x.size and np.allclose(xr, x, rtol=1e-7, atol=1e-9, equal_nan=False):
            y = yr
            e = er
        else:
            y = np.interp(x, xr, yr, left=np.nan, right=np.nan)
            finite_err = np.isfinite(er)
            if np.sum(finite_err) >= 2:
                e = np.interp(x, xr[finite_err], er[finite_err], left=np.nan, right=np.nan)
            else:
                e = np.full_like(y, np.nan)

        outside = int(np.sum(~np.isfinite(y)))
        return y, e, outside

    def resolve_external_sample_params(self, file_path, meta_map, monitor_mode):
        meta = self.get_external_meta_for_file(meta_map, file_path)
        hmeta = self.parse_external_1d_header_meta(file_path)

        exp = None
        mon = None
        trans = None
        thk_mm_meta = None
        source = "fixed"

        if meta is not None:
            if meta.get("exp") is not None:
                exp = meta["exp"]
            if meta.get("mon") is not None:
                mon = meta["mon"]
            if meta.get("trans") is not None:
                trans = meta["trans"]
            thk_mm_meta = meta.get("thk_mm")
            source = "meta"

        if hmeta is not None:
            if exp is None and hmeta.get("exp") is not None:
                exp = hmeta["exp"]
                if source != "meta":
                    source = "header"
            if mon is None and hmeta.get("mon") is not None:
                mon = hmeta["mon"]
                if source != "meta":
                    source = "header"
            if trans is None and hmeta.get("trans") is not None:
                trans = hmeta["trans"]
                if source != "meta":
                    source = "header"
            if thk_mm_meta is None and hmeta.get("thk_mm") is not None:
                thk_mm_meta = hmeta["thk_mm"]
                if source == "fixed":
                    source = "header"

        if exp is None:
            exp = self.t3_sample_exp.get()
        if mon is None:
            mon = self.t3_sample_i0.get()
        if trans is None:
            trans = self.t3_sample_t.get()

        norm = self.compute_norm_factor(exp, mon, trans, monitor_mode)
        return {
            "exp": exp,
            "mon": mon,
            "trans": trans,
            "norm": norm,
            "thk_mm_meta": thk_mm_meta,
            "source": source,
        }

    def dry_run_external_1d(self):
        if not self.t3_files:
            self.show_info("msg_preview_title", self.tr("msg_t3_queue_empty"))
            return

        rows = []
        files = list(dict.fromkeys(self.t3_files))
        failed_files = 0
        risky_files = 0
        pipeline_mode = self.t3_pipeline_mode.get().strip().lower()
        mode = self.t3_corr_mode.get()
        k = float(self.global_vars["k_factor"].get())
        thk_mm = float(self.t3_fixed_thk.get())
        monitor_mode = self.get_monitor_mode()
        warnings = []

        if k <= 0:
            warnings.append(self.tr("warn_k_le_zero"))
        if mode == "k_over_d" and thk_mm <= 0:
            warnings.append(self.tr("warn_kd_thk_le_zero"))

        meta_map = {}
        bg_prof = None
        dark_prof = None
        bg_norm = np.nan
        if pipeline_mode == "raw":
            meta_path = self.t3_meta_csv_path.get().strip()
            if meta_path:
                try:
                    meta_map = self.load_external_meta_map(meta_path)
                except Exception as e:
                    warnings.append(self.tr("warn_meta_read_fail").format(e=e))
            else:
                warnings.append(self.tr("warn_raw_no_meta"))

            bg_path = self.t3_bg1d_path.get().strip()
            if not bg_path:
                warnings.append(self.tr("warn_raw_no_bg1d"))
            else:
                try:
                    bg_prof = self.read_external_1d_profile(bg_path)
                except Exception as e:
                    warnings.append(self.tr("warn_bg1d_read_fail").format(e=e))

            dark_path = self.t3_dark1d_path.get().strip()
            if dark_path:
                try:
                    dark_prof = self.read_external_1d_profile(dark_path)
                except Exception as e:
                    warnings.append(self.tr("warn_dark1d_read_fail").format(e=e))

            bg_norm = self.compute_norm_factor(
                self.t3_bg_exp.get(), self.t3_bg_i0.get(), self.t3_bg_t.get(), monitor_mode
            )
            if (not np.isfinite(bg_norm) or bg_norm <= 0) and bg_path:
                bg_h = self.parse_external_1d_header_meta(bg_path)
                bg_norm = self.compute_norm_factor(bg_h.get("exp"), bg_h.get("mon"), bg_h.get("trans"), monitor_mode)
            if not np.isfinite(bg_norm) or bg_norm <= 0:
                warnings.append(self.tr("warn_bg_norm_invalid"))

        for fp in files:
            try:
                prof = self.read_external_1d_profile(fp)
                x_label = self.infer_external_x_label(fp, prof)
                status = self.tr("status_ok")
                reason = ""
                norm_s = np.nan
                thk_used = np.nan
                meta_src = "-"
                outside_bg = 0
                outside_dark = 0

                if pipeline_mode == "raw":
                    sp = self.resolve_external_sample_params(fp, meta_map, monitor_mode)
                    norm_s = sp["norm"]
                    meta_src = sp["source"]
                    if not np.isfinite(norm_s) or norm_s <= 0:
                        status = self.tr("status_fail")
                        reason = self.tr("reason_norm_invalid")
                    else:
                        if mode == "k_over_d":
                            thk_use_mm = thk_mm
                            if self.t3_use_meta_thk.get() and sp["thk_mm_meta"] is not None:
                                thk_use_mm = float(sp["thk_mm_meta"])
                            thk_used = thk_use_mm / 10.0 if np.isfinite(thk_use_mm) else np.nan
                            if not np.isfinite(thk_used) or thk_used <= 0:
                                status = self.tr("status_fail")
                                reason = self.tr("reason_thk_invalid")
                        else:
                            thk_used = np.nan

                        if status == self.tr("status_ok") and bg_prof is not None:
                            _, _, outside_bg = self.align_profile_to_x(prof["x"], bg_prof, "BG")
                            if outside_bg > 0:
                                risky_files += 1
                        if status == self.tr("status_ok") and dark_prof is not None:
                            _, _, outside_dark = self.align_profile_to_x(prof["x"], dark_prof, "Dark")
                            if outside_dark > 0:
                                risky_files += 1

                if status != self.tr("status_ok"):
                    failed_files += 1

                rows.append({
                    "File": Path(fp).name,
                    "Points": len(prof["x"]),
                    "XCol": prof.get("x_col", ""),
                    "ICol": prof.get("i_col", ""),
                    "ErrCol": prof.get("err_col", ""),
                    "XLabel": x_label,
                    "Norm_s": norm_s,
                    "Thk_cm": thk_used,
                    "MetaSrc": meta_src,
                    "BG_OutsidePts": outside_bg,
                    "Dark_OutsidePts": outside_dark,
                    "Status": status,
                    "Reason": reason,
                })
            except Exception as e:
                failed_files += 1
                rows.append({
                    "File": Path(fp).name,
                    "Points": 0,
                    "XCol": "",
                    "ICol": "",
                    "ErrCol": "",
                    "XLabel": "",
                    "Norm_s": np.nan,
                    "Thk_cm": np.nan,
                    "MetaSrc": "-",
                    "BG_OutsidePts": 0,
                    "Dark_OutsidePts": 0,
                    "Status": self.tr("status_fail"),
                    "Reason": str(e),
                })

        gate = self._evaluate_preflight_gate(
            total_files=len(files),
            failed_files=failed_files,
            warnings_count=len(warnings),
            risky_files=risky_files,
        )

        top = tk.Toplevel(self.root)
        top.title(self.tr("title_t3_dryrun"))
        txt = tk.Text(top, font=("Consolas", 9))
        txt.pack(fill="both", expand=True)
        self._register_native_widget(txt)
        txt.insert(tk.END, f"{self._preflight_label_text(gate)}\n")
        txt.insert(tk.END, f"{self.tr('pre_k_factor')} {k}\n")
        txt.insert(tk.END, f"{self.tr('pre_pipeline')} {pipeline_mode}\n")
        txt.insert(tk.END, f"{self.tr('pre_corr_mode')} {mode}\n")
        txt.insert(tk.END, f"{self.tr('pre_fixed_thk')} {thk_mm}\n")
        txt.insert(tk.END, f"{self.tr('pre_x_mode')} {self.t3_x_mode.get()}\n")
        if pipeline_mode == "raw":
            txt.insert(tk.END, f"{self.tr('pre_i0_semantic')} {monitor_mode} (norm={self.monitor_norm_formula(monitor_mode)})\n")
            txt.insert(tk.END, f"BG_Norm: {bg_norm if np.isfinite(bg_norm) else 'NaN'}\n")
        txt.insert(tk.END, "-" * 80 + "\n")
        if warnings:
            txt.insert(tk.END, f"{self.tr('pre_warning_header')}\n")
            for w in warnings:
                txt.insert(tk.END, f"- {w}\n")
            txt.insert(tk.END, "-" * 80 + "\n")
        else:
            txt.insert(tk.END, f"{self.tr('pre_pass_t3')}\n")
            txt.insert(tk.END, "-" * 80 + "\n")
        txt.insert(tk.END, pd.DataFrame(rows).to_string(index=False))

    def run_external_1d_batch(self):
        try:
            if not self.t3_files:
                raise ValueError("队列为空：请先添加外部1D文件。")

            files = list(dict.fromkeys(self.t3_files))
            if len(files) < len(self.t3_files):
                self.t3_files = files
                self.lb_ext1d.delete(0, tk.END)
                for f in self.t3_files:
                    self.lb_ext1d.insert(tk.END, Path(f).name)
                self.refresh_external_1d_status()

            k = float(self.global_vars["k_factor"].get())
            if not np.isfinite(k) or k <= 0:
                raise ValueError("K 因子无效（必须 > 0）。")

            pipeline_mode = self.t3_pipeline_mode.get().strip().lower()
            if pipeline_mode not in ("scaled", "raw"):
                raise ValueError(f"未知流程模式: {pipeline_mode}")

            corr_mode = self.t3_corr_mode.get().strip().lower()
            if corr_mode not in ("k_over_d", "k_only"):
                raise ValueError(f"未知校正模式: {corr_mode}")

            fixed_thk_mm = float(self.t3_fixed_thk.get())
            if corr_mode == "k_over_d" and fixed_thk_mm <= 0:
                raise ValueError("K/d 模式下固定厚度必须 > 0 mm。")

            fixed_thk_cm = fixed_thk_mm / 10.0 if corr_mode == "k_over_d" else np.nan
            scale_factor_global = (k / fixed_thk_cm) if corr_mode == "k_over_d" else k
            monitor_mode = self.get_monitor_mode()

            meta_map = {}
            bg_prof = None
            dark_prof = None
            bg_norm = np.nan
            if pipeline_mode == "raw":
                meta_path = self.t3_meta_csv_path.get().strip()
                if meta_path:
                    meta_map = self.load_external_meta_map(meta_path)

                bg_path = self.t3_bg1d_path.get().strip()
                if not bg_path:
                    raise ValueError("raw流程必须提供 BG 1D 文件。")
                bg_prof = self.read_external_1d_profile(bg_path)

                dark_path = self.t3_dark1d_path.get().strip()
                if dark_path:
                    dark_prof = self.read_external_1d_profile(dark_path)

                bg_norm = self.compute_norm_factor(
                    self.t3_bg_exp.get(), self.t3_bg_i0.get(), self.t3_bg_t.get(), monitor_mode
                )
                if (not np.isfinite(bg_norm) or bg_norm <= 0) and bg_path:
                    bg_h = self.parse_external_1d_header_meta(bg_path)
                    bg_norm = self.compute_norm_factor(bg_h.get("exp"), bg_h.get("mon"), bg_h.get("trans"), monitor_mode)
                if not np.isfinite(bg_norm) or bg_norm <= 0:
                    raise ValueError("raw流程下 BG 归一化因子无效，请检查 BG exp/i0/T。")

            custom_out_root = self.t3_output_root.get().strip() if hasattr(self, "t3_output_root") else ""
            if custom_out_root:
                out_root = Path(custom_out_root).expanduser()
                out_root.mkdir(parents=True, exist_ok=True)
            else:
                out_root = Path(files[0]).parent
            out_dir = out_root / "processed_external_1d_abs"
            report_dir = out_root / "processed_external_1d_reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            report_dir.mkdir(parents=True, exist_ok=True)

            resume = bool(self.t3_resume_enabled.get())
            overwrite = bool(self.t3_overwrite.get())
            if parse_run_policy is not None:
                run_policy = parse_run_policy(resume_enabled=resume, overwrite_existing=overwrite)
            else:
                run_policy = SimpleNamespace(
                    resume_enabled=resume,
                    overwrite_existing=overwrite,
                    mode=("overwrite" if overwrite else ("resume-skip" if resume else "always-run")),
                    should_skip_existing=lambda exists: bool(exists) and resume and (not overwrite),
                )
            self.log(f"[配置] Tab3 Existing-output 策略: {run_policy.mode} (resume={resume}, overwrite={overwrite})")
            stem_map = self.build_output_stem_map(files)

            self.t3_prog_bar["maximum"] = len(files)
            self.t3_prog_bar["value"] = 0

            rows = []
            ok = 0
            skip = 0
            fail = 0
            processed = 0

            for idx, fp in enumerate(files):
                fname = Path(fp).name
                reason = ""
                outputs = ""
                points = 0
                x_label = ""
                scale_factor = scale_factor_global if pipeline_mode == "scaled" else np.nan
                thk_cm_used = fixed_thk_cm if pipeline_mode == "scaled" else np.nan
                norm_s = np.nan
                meta_source = "-"
                outside_bg = 0
                outside_dark = 0
                try:
                    prof = self.read_external_1d_profile(fp)
                    points = len(prof["x"])
                    x_label = self.infer_external_x_label(fp, prof)
                    ext = ".chi" if x_label == "Chi_deg" else ".dat"
                    out_path = out_dir / f"{stem_map[fp]}{ext}"

                    if run_policy.should_skip_existing(out_path.exists()):
                        status = "已跳过"
                        reason = "输出已存在"
                        outputs = out_path.name
                        skip += 1
                    else:
                        if pipeline_mode == "scaled":
                            scale_factor = scale_factor_global
                            thk_cm_used = fixed_thk_cm
                            i_abs = np.asarray(prof["i_rel"], dtype=np.float64) * scale_factor
                            err_abs = np.asarray(prof["err_rel"], dtype=np.float64) * abs(scale_factor)
                        else:
                            sp = self.resolve_external_sample_params(fp, meta_map, monitor_mode)
                            norm_s = sp["norm"]
                            meta_source = sp["source"]
                            if not np.isfinite(norm_s) or norm_s <= 0:
                                raise ValueError("样品归一化因子无效（exp/i0/T）")

                            if corr_mode == "k_over_d":
                                thk_use_mm = fixed_thk_mm
                                if self.t3_use_meta_thk.get() and sp["thk_mm_meta"] is not None:
                                    thk_use_mm = float(sp["thk_mm_meta"])
                                thk_cm_used = float(thk_use_mm) / 10.0
                                if not np.isfinite(thk_cm_used) or thk_cm_used <= 0:
                                    raise ValueError("厚度无效（固定厚度或metadata thk_mm）")
                                scale_factor = k / thk_cm_used
                            else:
                                thk_cm_used = np.nan
                                scale_factor = k

                            s_i = np.asarray(prof["i_rel"], dtype=np.float64)
                            s_e = np.asarray(prof["err_rel"], dtype=np.float64)
                            x = np.asarray(prof["x"], dtype=np.float64)

                            bg_i, bg_e, outside_bg = self.align_profile_to_x(x, bg_prof, "BG")
                            if dark_prof is not None:
                                d_i, d_e, outside_dark = self.align_profile_to_x(x, dark_prof, "Dark")
                            else:
                                d_i = np.zeros_like(s_i)
                                d_e = np.full_like(s_i, np.nan)

                            net = (s_i - d_i) / norm_s - (bg_i - d_i) / bg_norm

                            if np.all(~np.isfinite(net)):
                                raise ValueError("净信号全部为无效值，无法输出。")

                            if np.any(np.isfinite(s_e)) or np.any(np.isfinite(bg_e)) or np.any(np.isfinite(d_e)):
                                s_term = (np.nan_to_num(s_e, nan=0.0) / norm_s) ** 2
                                bg_term = (np.nan_to_num(bg_e, nan=0.0) / bg_norm) ** 2
                                d_term = (np.nan_to_num(d_e, nan=0.0) * (1.0 / bg_norm - 1.0 / norm_s)) ** 2
                                net_err = np.sqrt(s_term + bg_term + d_term)
                                net_err[~np.isfinite(net)] = np.nan
                            else:
                                net_err = np.full_like(net, np.nan)

                            i_abs = net * scale_factor
                            err_abs = net_err * abs(scale_factor)

                            issue = self.profile_health_issue(i_abs)
                            if issue:
                                raise ValueError(issue)

                        # --- Buffer / solvent subtraction (post-calibration) ---
                        if (hasattr(self, "t3_buffer_enabled") and self.t3_buffer_enabled.get()
                                and self.t3_buffer_path.get().strip()):
                            if pipeline_mode == "raw":
                                raise ValueError(
                                    "raw 流程下启用 buffer 扣除要求 buffer 曲线已在与样品一致的绝对标度；"
                                    "当前版本为防止量纲误用已禁止该组合。"
                                )
                            buf_path = self.t3_buffer_path.get().strip()
                            buf_prof = self.read_external_1d_profile(buf_path)
                            buf_alpha = float(self.t3_alpha.get()) if hasattr(self, "t3_alpha") else 1.0
                            if subtract_buffer is not None:
                                buf_x = np.asarray(buf_prof["x"], dtype=np.float64)
                                buf_i = np.asarray(buf_prof["i_rel"], dtype=np.float64)
                                buf_e = np.asarray(buf_prof["err_rel"], dtype=np.float64)
                                result_buf = subtract_buffer(
                                    np.asarray(prof["x"], dtype=np.float64),
                                    i_abs, err_abs,
                                    buf_x, buf_i, buf_e,
                                    alpha=buf_alpha,
                                )
                                i_abs = result_buf.i_subtracted
                                err_abs = result_buf.err_subtracted
                            else:
                                # Fallback without library: subtraction + error propagation
                                _x_s = np.asarray(prof["x"], dtype=np.float64)
                                _x_b = np.asarray(buf_prof["x"], dtype=np.float64)
                                if not np.isfinite(buf_alpha) or buf_alpha <= 0:
                                    raise ValueError("Buffer scaling factor alpha must be finite and > 0")
                                order_b = np.argsort(_x_b)
                                _x_b = _x_b[order_b]
                                _buf_i = np.asarray(buf_prof["i_rel"], dtype=np.float64)[order_b]
                                _buf_e = np.asarray(buf_prof["err_rel"], dtype=np.float64)[order_b]
                                tol = max(
                                    1e-12,
                                    1e-9 * max(abs(_x_b[0]), abs(_x_b[-1]), abs(_x_s).max(initial=0.0))
                                )
                                if np.min(_x_s) < _x_b[0] - tol or np.max(_x_s) > _x_b[-1] + tol:
                                    raise ValueError(
                                        "sample q grid extends outside buffer q range "
                                        f"({_x_b[0]:.6g} to {_x_b[-1]:.6g})"
                                    )
                                buf_i_interp = np.interp(
                                    _x_s, _x_b, _buf_i,
                                )
                                buf_e_interp = np.interp(
                                    _x_s, _x_b, _buf_e,
                                )
                                i_abs = i_abs - buf_alpha * buf_i_interp
                                err_abs = np.sqrt(err_abs**2 + (buf_alpha * buf_e_interp)**2)

                        _ofmt = self.t3_output_format.get() if hasattr(self, "t3_output_format") else "tsv"
                        self.save_profile_table(out_path, prof["x"], i_abs, err_abs, x_label, output_format=_ofmt)
                        status = "成功"
                        outputs = out_path.name
                        ok += 1

                except Exception as e:
                    status = "失败"
                    reason = str(e)
                    fail += 1

                rows.append({
                    "Index": idx,
                    "File": fname,
                    "Status": status,
                    "Reason": reason,
                    "Points": points,
                    "XLabel": x_label,
                    "PipelineMode": pipeline_mode,
                    "CorrMode": corr_mode,
                    "K": k,
                    "Thickness_cm": thk_cm_used if np.isfinite(thk_cm_used) else np.nan,
                    "Norm_s": norm_s if np.isfinite(norm_s) else np.nan,
                    "BG_Norm": bg_norm if np.isfinite(bg_norm) else np.nan,
                    "MetaSource": meta_source,
                    "BG_OutsidePts": outside_bg,
                    "Dark_OutsidePts": outside_dark,
                    "ScaleFactor": scale_factor,
                    "Output": outputs,
                })

                processed += 1
                self.t3_prog_bar["value"] = processed
                self.root.update_idletasks()

            rows.sort(key=lambda x: x.get("Index", 0))
            for r in rows:
                r.pop("Index", None)

            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            report_path = report_dir / f"external1d_report_{stamp}.csv"
            pd.DataFrame(rows).to_csv(report_path, index=False, encoding="utf-8-sig")

            meta = {
                "timestamp": stamp,
                "files_total": len(files),
                "k_factor": k,
                "pipeline_mode": pipeline_mode,
                "corr_mode": corr_mode,
                "scale_factor_global": scale_factor_global,
                "fixed_thickness_mm": fixed_thk_mm if corr_mode == "k_over_d" else None,
                "x_mode": self.t3_x_mode.get(),
                "monitor_mode": monitor_mode,
                "monitor_norm_formula": self.monitor_norm_formula(monitor_mode),
                "meta_csv": self.t3_meta_csv_path.get().strip(),
                "bg_1d_path": self.t3_bg1d_path.get().strip(),
                "dark_1d_path": self.t3_dark1d_path.get().strip(),
                "bg_norm": float(bg_norm) if np.isfinite(bg_norm) else None,
                "resume_enabled": resume,
                "overwrite": overwrite,
                "existing_output_policy": run_policy.mode,
                "output_root": str(out_root),
                "output_root_custom": bool(custom_out_root),
                "output_dir": str(out_dir),
                "report_csv": str(report_path),
                "summary": {"success": ok, "skipped": skip, "failed": fail},
            }
            meta_path = report_dir / f"external1d_meta_{stamp}.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            self.show_info(
                "msg_ext_done_title",
                self.tr("msg_ext_done_body").format(
                    ok=ok, skip=skip, fail=fail,
                    out_dir=out_dir, report=report_path.name, meta=meta_path.name,
                ),
            )

        except Exception as e:
            self.show_error("msg_ext_error_title", f"{e}\n{traceback.format_exc()}")

    def init_tab_help(self):
        p = self.tab_help

        head = ttk.LabelFrame(p, text=self.tr("help_panel_title"), style="Group.TLabelframe")
        self._register_i18n_widget(head, "help_panel_title")
        head.pack(fill="x", padx=10, pady=(8, 4))
        lbl_intro = ttk.Label(
            head,
            text=self.tr("help_panel_intro"),
            justify="left",
            style="Hint.TLabel",
        )
        self._register_i18n_widget(lbl_intro, "help_panel_intro")
        lbl_intro.pack(fill="x", padx=5, pady=4)

        bar = ttk.Frame(p)
        bar.pack(fill="x", padx=10, pady=(0, 4))
        lbl_scroll = ttk.Label(bar, text=self.tr("help_scroll_label"), style="Bold.TLabel")
        self._register_i18n_widget(lbl_scroll, "help_scroll_label")
        lbl_scroll.pack(side="left")

        text_wrap = ttk.Frame(p)
        text_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        y_scroll = ttk.Scrollbar(text_wrap, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        txt = tk.Text(
            text_wrap,
            font=("Consolas", 9),
            wrap="word",
            yscrollcommand=y_scroll.set,
            padx=8,
            pady=8,
        )
        self._register_native_widget(txt)
        txt.pack(side="left", fill="both", expand=True)
        y_scroll.config(command=txt.yview)

        help_text = """
==============================
BL19B2 SAXS Workstation 使用帮助
==============================

[一] 程序做什么
1. Tab1：用标准样（推荐 GC）做 K 因子标定。
2. Tab2：把 2D 图像批处理成绝对强度 1D 结果（含误差列）。
3. Tab3：把外部软件积分后的 1D 相对强度批量转换为绝对强度。
4. 输出包含报告文件，便于复现实验流程。

----------------------------------------
[二] 第一次使用的最短路径（建议按顺序）
----------------------------------------
Step 1. 先做 Tab1 标定（只需一组 Std/BG/Dark/poni）
1) 选择文件：标准样、背景、暗场、poni。
2) 检查 Time/I0/T 是否自动带入正确（必要时手工改）。
3) 选择 I0 语义：
   - rate：I0 是每秒计数率，归一化用 exp * I0 * T
   - integrated：I0 是积分计数，归一化用 I0 * T
4) 填标准样厚度(mm)，点击“运行 K 因子标定”。
5) 重点看报告中的：
   - Points Used（越多越稳）
   - Std Dev（越小越稳）
   - Q overlap（要有足够重叠区间）
6) 标定成功后，K 会自动写入全局并保存历史。

Step 2. 再做 Tab2 批处理
1) 确认 K 因子 > 0；BG/Dark/poni 路径正确。
2) 选择厚度策略：
   - 自动厚度：d = -ln(T)/mu
   - 固定厚度：所有样品同一厚度
3) 选择积分模式（可多选）：
   - I-Q 全环
   - I-Q 扇区（支持多扇区：如 -25~25;45~65）
   - I-chi 织构（q 区间）
4) 选择修正项（推荐）：
   - 开启 Solid Angle
   - 误差模型选 azimuthal（常用）
   - 有掩膜就加载 Mask
   - 注意：Tab2 的 Solid Angle 必须与 Tab1 标定时一致，否则 K 因子不可直接使用
5) 参考模式：
   - 固定 BG/Dark（新手推荐，最稳定）
   - 自动匹配 BG/Dark（高级用法）
6) 先点“预检查”，确认没有关键警告。
7) 如需集中管理结果，可在底部“输出根目录”指定自定义路径。
8) 点击“开始稳健批处理”。

Step 3. 如果你已在外部软件完成积分（可选）
1) 进入 Tab3，导入外部 1D 文件（.dat/.txt/.chi/.csv）。
2) 选择流程：
   - 仅比例缩放：外部1D已完成本底/归一化
   - 原始1D完整校正：外部1D是原始积分结果，需要提供 BG1D/Dark1D 和 exp/I0/T
   - metadata 来源优先级：metadata.csv > 文件注释头 > Tab3 固定参数
   - BG固定参数默认跟随 Tab1 全局；可取消“BG参数跟随”后手动覆盖
   - metadata.csv 可以直接用 Tab2 的 batch_report.csv，或点“由 Tab2 报告生成 metadata”
3) 选择公式：
   - K/d：外部 1D 还未除厚度
   - K：外部 1D 已除厚度
4) 先预检查，再批量运行。
5) 如需集中管理结果，可在底部“输出根目录”指定自定义路径。

----------------------------------------
[三] 核心参数解释（新手必看）
----------------------------------------
1) Time(s)
   曝光时间。若 I0 语义是 rate，Time 会参与归一化；若是 integrated，不参与。

2) I0(Mon)
   入射强度监测值。请确认是“计数率”还是“积分计数”，并与 I0 语义一致。

3) Trans(T)
   透过率，推荐范围 (0, 1]。
   程序会对 1~2 的值做保护处理（视为漂移并夹到 1.0），
   仅对明确百分号或明显百分数字面量（>2）才按百分数换算。

4) mu（自动厚度模式）
   单位 cm^-1。mu 错会导致厚度和绝对强度整体偏差。

5) Polarization
   范围 [-1, 1]。不确定时先用 0。

6) 扇区角度（Tab2 azimuth_range）
   程序使用 pyFAI chi 定义：
   - 0° 向右
   - +90° 向下
   - -90° 向上
   - ±180° 向左
   支持跨 ±180° 扇区，例如 sec_min=170, sec_max=-170。
   多扇区可在“多扇区”中写为 `-25~25;45~65`（留空则使用单扇区输入框）。
   可点击“预览I-Q”在2D图上确认全环/多扇区积分区域。

----------------------------------------
[四] 程序内置的防错机制（你会看到的告警）
----------------------------------------
1) BG_Norm 与样品 Norm_s 量级异常
   若差异过大，固定 BG 模式会直接阻断，避免“过扣背景导致全负值”。

2) 积分结果健康检查
   若某条输出几乎全为非正值，模式会被判失败并提示检查归一化/BG。

3) 仪器一致性检查
   可检查能量、波长、距离、像素、尺寸是否一致。

----------------------------------------
[五] 常见问题与处理
----------------------------------------
Q1：整条曲线几乎全负？
A1：
  - 先看 batch_report 里的 Norm_s 和 BG_Norm 是否同量级。
  - 检查 BG 的 Time/I0/T 是否填写正确。
  - 检查 I0 语义（rate/integrated）是否选错。
  - 用“固定 BG/Dark + 预检查”先跑通。

Q2：为什么程序提示缺少 exp/mon/trans？
A2：
  - 头字段没读到或命名不标准。
  - 可手工在界面填入参数（尤其是 Tab1）。
  - 建议先用少量样品 dry_run 验证。

Q3：I-chi 结果看起来不对？
A3：
  - 检查 qmin/qmax 是否合理。
  - 程序已对 radial q 单位做兼容处理，但仍需确认 q 区间与物理预期一致。
  - 可点击“预览I-chi”在2D图上核对 q 环带范围。

Q4：Origin 导入不方便？
A4：
  - 当前输出是表头+制表符格式（TSV风格），列名包含坐标、I_abs、Error，直接按列导入。

Q5：pyFAI 导出的 1D 文件能直接读出 exp/I0/T 吗？
A5：
  - 多数情况下只能稳定读出 X/I/(可选Error) 列。
  - exp/I0/T 是否可读，取决于文件注释头是否写入了这些字段。
  - 程序会尝试从注释头读取；若读不到，请提供 metadata CSV 或固定参数。

Q6：metadata.csv 从哪来？
A6：
  - 推荐直接使用 Tab2 输出目录（默认样品目录，或你设置的自定义输出根目录）`processed_robust_reports` 中自动生成的：
    `metadata_for_tab3_*.csv` 或 `metadata.csv`。
  - 也可在 Tab3 点“由 Tab2 报告生成 metadata”，从 `batch_report_*.csv` 一键生成。

Q7：Tab2 扇区角度不确定怎么办？
A7：
  - 在 Tab2 扇区输入框旁点击“预览I-Q”。
  - 弹窗会叠加单扇区/多扇区掩膜与边界线，并显示角度定义（0°右、+90°下）。

----------------------------------------
[六] 输出文件说明
----------------------------------------
1) Tab1 输出
   - calibration_check.csv：标定后的参考曲线（含误差列）
   - k_factor_history.csv：K 历史与关键参数

2) Tab2 输出
   （根目录默认在样品目录，也可在 Tab2 底部自定义）
   - processed_robust_1d_full/*.dat
   - processed_robust_1d_sector/*.dat（单扇区）
   - processed_robust_1d_sector/sector_*/*.dat（多扇区分别保存）
   - processed_robust_1d_sector_combined/*.dat（扇区合并保存，若勾选）
   - processed_robust_radial_chi/*.chi
   每个文件均为：坐标列 + I_abs_cm^-1 + Error_cm^-1
   - processed_robust_reports/batch_report_*.csv
   - processed_robust_reports/metadata_for_tab3_*.csv
   - processed_robust_reports/metadata.csv
   - processed_robust_reports/run_meta_*.json

3) Tab3 输出
   （根目录默认在首个输入文件目录，也可在 Tab3 底部自定义）
   - processed_external_1d_abs/*.dat 或 *.chi
   - processed_external_1d_reports/external1d_report_*.csv
   - processed_external_1d_reports/external1d_meta_*.json

----------------------------------------
[七] 新手执行检查清单（每次开跑前）
----------------------------------------
[ ] K 因子来自最近一次可信标定（Tab1）
[ ] I0 语义确认无误（rate 或 integrated）
[ ] BG/Dark/poni 来自同一实验条件
[ ] 先做预检查（dry_run）再正式批处理
[ ] 看 batch_report：成功/失败原因是否合理

----------------------------------------
[八] 推荐工作习惯（减少返工）
----------------------------------------
1) 先用 3~5 个样品试跑，确认流程正确再全量跑。
2) 批处理时优先开启断点续跑，避免中断后重算全部。
3) 每批次保留 run_meta 与 batch_report，方便追溯与审稿说明。

（帮助页版本：v2，适配 Tab2->Tab3 直连 metadata 流程）
"""

        help_text_zh = help_text.strip() + "\n"

        if self.language == "en":
            help_text = """
==============================
SAXSAbs Workbench User Guide
==============================

[1] What this program does
1. Tab1: estimate K factor using a standard sample (GC recommended).
2. Tab2: batch-process 2D images into absolute-intensity 1D outputs with error columns.
3. Tab3: convert external 1D relative intensities into absolute intensities.
4. Export reports for reproducibility and audit.

[2] Minimal first-use workflow
1) Run Tab1 calibration with Std/BG/Dark/poni.
2) Verify Time/I0/T and monitor mode (rate or integrated).
3) Run robust K calibration and check Points Used, Std Dev, and Q overlap.
4) Go to Tab2 for batch processing; run dry-check before full run.
5) Use Tab3 only when external 1D conversion is needed.

[3] Critical checks before batch runs
- K factor is valid and recent.
- BG/Dark/poni are from compatible conditions.
- Dry-check reports no critical warnings.
- Monitor mode matches beamline data semantics.

[4] Outputs
- Tab1: calibration_check.csv, k_factor_history.csv
- Tab2: processed_robust_* and batch_report/metadata/run_meta
- Tab3: processed_external_1d_abs and external1d_report/meta

For advanced details, keep the Chinese help mode or refer to repository docs.
"""

        self.help_text_widget = txt
        self.help_text_content_zh = help_text_zh
        self.help_text_content = help_text.strip() + "\n"
        txt.insert(tk.END, self.help_text_content)
        txt.config(state="disabled")

        def copy_help():
            self.root.clipboard_clear()
            self.root.clipboard_append(self.help_text_content)
            self.root.update()
            self.show_info("msg_help_title", self.tr("msg_help_copied"))

        btn_copy = ttk.Button(bar, text=self.tr("help_copy_btn"), command=copy_help)
        self._register_i18n_widget(btn_copy, "help_copy_btn")
        btn_copy.pack(side="right")
        self.add_tooltip(btn_copy, self.tr("help_copy_tooltip"))

    def refresh_help_text(self):
        txt = getattr(self, "help_text_widget", None)
        if txt is None:
            return
        if self.language == "en":
            content = """
==============================
SAXSAbs Workbench User Guide
==============================

[1] What this program does
1. Tab1: estimate K factor using a standard sample (GC recommended).
2. Tab2: batch-process 2D images into absolute-intensity 1D outputs with error columns.
3. Tab3: convert external 1D relative intensities into absolute intensities.
4. Export reports for reproducibility and audit.

[2] Minimal first-use workflow
1) Run Tab1 calibration with Std/BG/Dark/poni.
2) Verify Time/I0/T and monitor mode (rate or integrated).
3) Run robust K calibration and check Points Used, Std Dev, and Q overlap.
4) Go to Tab2 for batch processing; run dry-check before full run.
5) Use Tab3 only when external 1D conversion is needed.

[3] Critical checks before batch runs
- K factor is valid and recent.
- BG/Dark/poni are from compatible conditions.
- Dry-check reports no critical warnings.
- Monitor mode matches beamline data semantics.

[4] Outputs
- Tab1: calibration_check.csv, k_factor_history.csv
- Tab2: processed_robust_* and batch_report/metadata/run_meta
- Tab3: processed_external_1d_abs and external1d_report/meta

For advanced details, keep the Chinese help mode or refer to repository docs.
""".strip() + "\n"
        else:
            content = getattr(self, "help_text_content_zh", "")
        txt.config(state="normal")
        txt.delete("1.0", tk.END)
        txt.insert(tk.END, content)
        txt.config(state="disabled")
        self.help_text_content = content

    # =========================================================================
    # Logic: K-Calibration (ROBUST + Error)
    # =========================================================================
    def run_calibration(self):
        try:
            files = {k: v.get() for k, v in self.t1_files.items()}
            if not all(files.values()): raise ValueError("文件不完整：请先选择标准样、背景、暗场和 poni。")
            p = {k: v.get() for k, v in self.t1_params.items()}
            if p["std_thk"] <= 0: raise ValueError("标准样厚度必须 > 0 mm。")
            monitor_mode = self.get_monitor_mode()
            apply_solid_angle = bool(self.global_vars["apply_solid_angle"].get())

            self.report(self.tr("rpt_start_calib"))
            self.report(self.tr("rpt_i0_norm_mode").format(mode=monitor_mode, formula=self.monitor_norm_formula(monitor_mode)))
            self.report(self.tr("rpt_solid_angle").format(state='ON' if apply_solid_angle else 'OFF'))
            
            ai = pyFAI.load(files["poni"])
            d_std = fabio.open(files["std"]).data.astype(np.float64)
            d_dark = fabio.open(files["dark"]).data.astype(np.float64)
            self._assert_same_shape(d_std, d_dark, "std", "dark")

            bg_paths = self.split_path_list(files["bg"])
            if not bg_paths:
                raise ValueError("未提供背景图像。")

            # --- 2D Subtraction (Physics Correct) ---
            norm_std = self.compute_norm_factor(
                p["std_exp"], p["std_i0"], p["std_t"], monitor_mode
            )
            bg_net, bg_norms, bg_used_paths = self.build_composite_bg_net(
                bg_paths=bg_paths,
                d_dark=d_dark,
                monitor_mode=monitor_mode,
                fallback_triplet=(p["bg_exp"], p["bg_i0"], p["bg_t"]),
                ref_shape=d_std.shape,
            )
            norm_bg = float(np.nanmedian(np.asarray(bg_norms, dtype=np.float64)))
            
            if norm_std <= 0 or norm_bg <= 0: raise ValueError("归一化因子 <= 0，请检查 Time/I0/T。")
            norm_ratio = norm_bg / max(norm_std, 1e-12)
            if norm_ratio < 0.01 or norm_ratio > 100.0:
                self.report(
                    f"[警告] 标定中 BG_Norm 与 Std_Norm 量级差异过大 "
                    f"(BG/Std={norm_ratio:.3g})，请复核 BG 的 Time/I0/T 与 I0 语义。"
                )
            
            # Net Signal 2D (Intensity/sec/unit_flux)
            img_net = (d_std - d_dark)/norm_std - bg_net
            
            # Integrate (Enable Error Propagation via Azimuthal Variance)
            # error_model="azimuthal" computes the sigma (std dev) of pixels in bin
            res = ai.integrate1d(
                img_net,
                1000,
                unit="q_A^-1",
                error_model="azimuthal",
                correctSolidAngle=apply_solid_angle,
            )

            q = np.asarray(res.radial, dtype=np.float64)
            i_1d = np.asarray(res.intensity, dtype=np.float64)
            if q.size < 3:
                raise ValueError("积分结果点数过少，无法完成标定。")

            thk_cm = p["std_thk"] / 10.0
            i_net_vol = i_1d / thk_cm

            # Extract Error (Azimuthal StdDev scaled by thickness)
            if getattr(res, "sigma", None) is None:
                sigma_net_vol = np.full_like(i_net_vol, np.nan)
            else:
                sigma_net_vol = np.asarray(res.sigma, dtype=np.float64) / thk_cm
            
            q_ref, i_ref = self._get_std_reference_data()
            std_key = self.t1_std_type.get()
            is_water = (std_key == "Water_20C")

            if is_water:
                # Water: flat signal — use median in q_window
                q_lo_w, q_hi_w = 0.01, 0.2
                win_mask = (q >= q_lo_w) & (q <= q_hi_w) & np.isfinite(i_net_vol) & (i_net_vol > 1e-9)
                if win_mask.sum() < 3:
                    raise ValueError("q 窗口内测量信号不足，无法用水标准标定。")
                water_dsdw_val = float(i_ref[0])  # flat value
                ratios = water_dsdw_val / np.asarray(i_net_vol[win_mask], dtype=np.float64)
                ratios = ratios[np.isfinite(ratios) & (ratios > 0)]
                if ratios.size < 3:
                    raise ValueError("水标准有效比值点数不足，无法稳健估计 K。")
                r_med = float(np.nanmedian(ratios))
                r_mad = float(np.nanmedian(np.abs(ratios - r_med)))
                ratios_used = ratios
                if np.isfinite(r_mad) and r_mad > 0:
                    robust_sigma = 1.4826 * r_mad
                    inlier = np.abs(ratios - r_med) <= 3.0 * robust_sigma
                    if int(np.sum(inlier)) >= 3:
                        ratios_used = ratios[inlier]
                k_val = float(np.nanmedian(ratios_used))
                k_std = float(np.nanstd(ratios_used))
                q_min = float(q[win_mask][0])
                q_max = float(q[win_mask][-1])
                points_total = int(win_mask.sum())
            else:
                # Normal q-I curve standard (SRM3600, Lupolen, Custom)
                mask_w = (q_ref >= 0.01) & (q_ref <= 0.2)
                q_ref_w = q_ref[mask_w] if mask_w.any() else q_ref
                i_ref_w = i_ref[mask_w] if mask_w.any() else i_ref
                q_min = max(np.nanmin(q), np.nanmin(q_ref_w))
                q_max = min(np.nanmax(q), np.nanmax(q_ref_w))
                q_mask = (q_ref_w >= q_min) & (q_ref_w <= q_max)
                q_ref_used = q_ref_w[q_mask]
                i_ref_used = i_ref_w[q_mask]
                if q_ref_used.size < 3:
                    raise ValueError("与参考曲线的 q 重叠区间不足，无法可靠标定。")

                if estimate_k_factor_robust is not None:
                    k_res = estimate_k_factor_robust(
                        q_meas=q,
                        i_meas_per_cm=i_net_vol,
                        q_ref=q_ref_used,
                        i_ref=i_ref_used,
                        q_window=(float(np.nanmin(q_ref_used)), float(np.nanmax(q_ref_used))),
                        positive_floor=1e-9,
                        min_points=3,
                    )
                    k_val = float(k_res.k_factor)
                    k_std = float(k_res.k_std)
                    q_min = float(k_res.q_min_overlap)
                    q_max = float(k_res.q_max_overlap)
                    ratios_used = np.asarray(k_res.ratios_used, dtype=np.float64)
                    points_total = int(k_res.points_total)
                else:
                    i_meas_interp = np.interp(q_ref_used, q, i_net_vol)
                    valid_idx = np.isfinite(i_meas_interp) & (i_meas_interp > 1e-9)
                    if np.sum(valid_idx) < 3:
                        raise ValueError("扣背景后信号过弱或为负，无法标定。")
                    ratios = i_ref_used[valid_idx] / i_meas_interp[valid_idx]
                    ratios = ratios[np.isfinite(ratios) & (ratios > 0)]
                    if ratios.size < 3:
                        raise ValueError("有效比值点数不足，无法稳健估计 K。")
                    r_med = np.nanmedian(ratios)
                    r_mad = np.nanmedian(np.abs(ratios - r_med))
                    ratios_used = ratios
                    if np.isfinite(r_mad) and r_mad > 0:
                        robust_sigma = 1.4826 * r_mad
                        inlier = np.abs(ratios - r_med) <= 3.0 * robust_sigma
                        if np.sum(inlier) >= 3:
                            ratios_used = ratios[inlier]
                    k_val = np.nanmedian(ratios_used)
                    k_std = np.nanstd(ratios_used)
                    points_total = len(q_ref_used)

            if k_val <= 0: raise ValueError(f"计算得到的 K <= 0 ({k_val})，请检查本底缩放和参数。")

            self.global_vars["k_factor"].set(k_val)
            self.global_vars["k_solid_angle"].set("on" if apply_solid_angle else "off")
            
            # Report
            self.report("-" * 30)
            self.report(self.tr("rpt_calib_ok"))
            self.report(f"K-Factor: {k_val:.4f}")
            self.report(f"Q overlap : {q_min:.4f} to {q_max:.4f} A^-1")
            self.report(f"Points Used: {len(ratios_used)}/{points_total}")
            self.report(f"BG files used: {len(bg_used_paths)}")
            rel_std = (k_std / k_val * 100) if k_val != 0 else np.nan
            self.report(f"Std Dev : {k_std:.4f} ({rel_std:.1f}%)")
            self.report("-" * 30)
            
            # Plot
            self.ax1.clear()
            self.ax1.loglog(q, i_net_vol, 'k--', alpha=0.4, label="Measured Net")
            self.ax1.loglog(q, i_net_vol * k_val, 'b-', label="Corrected")
            std_label = STANDARD_REGISTRY[std_key].name if (STANDARD_REGISTRY and std_key in STANDARD_REGISTRY) else std_key
            if not is_water:
                self.ax1.loglog(q_ref, i_ref, 'ro', mfc='none', label=std_label)
            else:
                self.ax1.axhline(float(i_ref[0]), color='r', ls='--', alpha=0.6, label=std_label)
            self.ax1.set_xlabel("q ($A^{-1}$)")
            self.ax1.set_ylabel("Absolute Intensity ($cm^{-1}$)")
            self.ax1.set_title(f"K={k_val:.2f}")
            self.ax1.legend()
            self.canvas1.draw()
            
            # Save Check File with Error
            save_path = Path(files["std"]).parent / "calibration_check.csv"
            # We save the full profile with error bars
            df = pd.DataFrame({
                "Q": q,
                "I_Abs": i_net_vol * k_val,
                "Error": sigma_net_vol * k_val
            })
            df.to_csv(save_path, index=False)
            self.report(f"Saved profile: {save_path.name}")

            self.append_k_history(
                files=files,
                params=p,
                monitor_mode=monitor_mode,
                apply_solid_angle=apply_solid_angle,
                k_val=k_val,
                k_std=k_std,
                points_used=len(ratios_used),
                q_min=q_min,
                q_max=q_max,
            )
            self.report("K history updated.")
            
        except Exception as e:
            self.show_error("msg_calib_error_title", str(e))
            self.report(f"[ERROR] {str(e)}")

    def append_k_history(self, files, params, monitor_mode, apply_solid_angle, k_val, k_std, points_used, q_min, q_max):
        hist_path = Path(__file__).resolve().parent / "k_factor_history.csv"
        std_norm = self.compute_norm_factor(
            params.get("std_exp", np.nan),
            params.get("std_i0", np.nan),
            params.get("std_t", np.nan),
            monitor_mode,
        )
        bg_norm = self.compute_norm_factor(
            params.get("bg_exp", np.nan),
            params.get("bg_i0", np.nan),
            params.get("bg_t", np.nan),
            monitor_mode,
        )
        row = {
            "Timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "Norm_Mode": monitor_mode,
            "Norm_Formula": self.monitor_norm_formula(monitor_mode),
            "SolidAngle_On": bool(apply_solid_angle),
            "K_Factor": float(k_val),
            "K_Std": float(k_std),
            "RelStd_pct": float((k_std / k_val * 100) if k_val else np.nan),
            "PointsUsed": int(points_used),
            "Q_Min": float(q_min),
            "Q_Max": float(q_max),
            "Std_File": files.get("std", ""),
            "BG_File": files.get("bg", ""),
            "Dark_File": files.get("dark", ""),
            "Poni_File": files.get("poni", ""),
            "Std_Thk_mm": float(params.get("std_thk", np.nan)),
            "Std_Norm": float(std_norm) if np.isfinite(std_norm) else np.nan,
            "BG_Norm": float(bg_norm) if np.isfinite(bg_norm) else np.nan,
        }
        df_row = pd.DataFrame([row])
        if hist_path.exists():
            try:
                old = pd.read_csv(hist_path)
                out = pd.concat([old, df_row], ignore_index=True)
            except Exception:
                out = df_row
        else:
            out = df_row
        out.to_csv(hist_path, index=False, encoding="utf-8-sig")

    def open_k_history(self):
        hist_path = Path(__file__).resolve().parent / "k_factor_history.csv"
        if not hist_path.exists():
            self.show_info("msg_k_history_title", self.tr("msg_k_history_empty"))
            return

        try:
            df = pd.read_csv(hist_path)
            if df.empty:
                self.show_info("msg_k_history_title", self.tr("msg_k_history_file_empty"))
                return
        except Exception as e:
            self.show_error("msg_k_history_title", self.tr("msg_k_history_read_error").format(e=e))
            return

        top = tk.Toplevel(self.root)
        top.title(self.tr("title_k_history"))
        top.geometry("980x640")

        upper = ttk.Frame(top)
        upper.pack(fill="both", expand=True)
        lower = ttk.Frame(top)
        lower.pack(fill="both", expand=True)

        fig = Figure(figsize=(7.2, 3.4), dpi=100)
        ax = fig.add_subplot(111)
        x = np.arange(len(df))
        y = pd.to_numeric(df["K_Factor"], errors="coerce").to_numpy(dtype=np.float64)
        e = pd.to_numeric(df.get("K_Std", np.nan), errors="coerce").to_numpy(dtype=np.float64)

        if np.any(np.isfinite(e)):
            ax.errorbar(x, y, yerr=e, fmt="o-", capsize=3, label="K ± Std")
        else:
            ax.plot(x, y, "o-", label="K")
        ax.set_xlabel("Run Index")
        ax.set_ylabel("K Factor")
        ax.set_title("K Drift Monitor")
        ax.grid(alpha=0.3)
        ax.legend()

        canvas = FigureCanvasTkAgg(fig, master=upper)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()

        txt = tk.Text(lower, font=("Consolas", 9))
        txt.pack(fill="both", expand=True)
        self._register_native_widget(txt)
        show_cols = [c for c in ["Timestamp", "Norm_Mode", "SolidAngle_On", "K_Factor", "K_Std", "RelStd_pct", "PointsUsed", "Q_Min", "Q_Max"] if c in df.columns]
        txt.insert(tk.END, df[show_cols].to_string(index=False))

    def report(self, msg):
        if hasattr(self, "txt_report"):
            line = self._localize_runtime_text(msg)
            # Semantic tag highlighting in report text widget
            tag = None
            msg_lower = msg.lower()
            if any(kw in msg_lower for kw in ("error", "fail", "失败", "错误", "blocked")):
                tag = "error"
            elif any(kw in msg_lower for kw in ("success", "done", "完成", "成功", "ready")):
                tag = "success"
            elif any(kw in msg_lower for kw in ("warning", "caution", "注意", "警告")):
                tag = "warning"
            start_idx = self.txt_report.index(tk.END)
            self.txt_report.insert(tk.END, line + "\n")
            if tag:
                end_idx = self.txt_report.index(tk.END)
                self.txt_report.tag_add(tag, start_idx, end_idx)
            self.txt_report.see(tk.END)
        # Mirror last message to status bar with semantic colour
        if hasattr(self, "_status_bar"):
            short = msg.strip()[:120]
            self._status_var.set(short)
            msg_lower = msg.lower()
            if any(kw in msg_lower for kw in ("error", "fail", "失败", "错误", "blocked")):
                self._status_bar.configure(foreground="#dc2626")
            elif any(kw in msg_lower for kw in ("success", "done", "完成", "成功", "ready")):
                self._status_bar.configure(foreground="#16a34a")
            elif any(kw in msg_lower for kw in ("warning", "caution", "注意", "警告")):
                self._status_bar.configure(foreground="#d97706")
            else:
                try:
                    import sv_ttk as _sv
                    _hint_fg = "#9ca3af" if _sv.get_theme() == "dark" else "#6b7280"
                except Exception:
                    _hint_fg = "#6b7280"
                self._status_bar.configure(foreground=_hint_fg)

    def log(self, msg):
        print(msg)
        self.report(msg)

    def get_selected_modes(self):
        modes = []
        if hasattr(self, "t2_mode_full") and self.t2_mode_full.get():
            modes.append("1d_full")
        if hasattr(self, "t2_mode_sector") and self.t2_mode_sector.get():
            modes.append("1d_sector")
        if hasattr(self, "t2_mode_chi") and self.t2_mode_chi.get():
            modes.append("radial_chi")
        return modes

    def add_bg_library_files(self):
        fs = filedialog.askopenfilenames(filetypes=[("Image", "*.tif *.tiff *.edf *.cbf")])
        for f in fs:
            if f not in self.t2_bg_candidates:
                self.t2_bg_candidates.append(f)
        self.t2_bg_lib_info.set(self.tr("var_bg_lib").format(n=len(self.t2_bg_candidates)))

    def add_dark_library_files(self):
        fs = filedialog.askopenfilenames(filetypes=[("Image", "*.tif *.tiff *.edf *.cbf")])
        for f in fs:
            if f not in self.t2_dark_candidates:
                self.t2_dark_candidates.append(f)
        self.t2_dark_lib_info.set(self.tr("var_dark_lib").format(n=len(self.t2_dark_candidates)))

    def clear_reference_libraries(self):
        self.t2_bg_candidates = []
        self.t2_dark_candidates = []
        self.t2_bg_lib_info.set(self.tr("var_bg_lib").format(n=0))
        self.t2_dark_lib_info.set(self.tr("var_dark_lib").format(n=0))

    def process_sample_task(self, idx, fpath, out_stem, context):
        logs = []
        mode_stats = {m: {"ok": 0, "fail": 0, "skip": 0} for m in context["selected_modes"]}

        def log_line(msg):
            logs.append(msg)

        def load_data(path):
            if context["parallel"]:
                return fabio.open(path).data.astype(np.float64)
            with context["cache_lock"]:
                if path in context["image_cache"]:
                    return context["image_cache"][path]
            d = fabio.open(path).data.astype(np.float64)
            with context["cache_lock"]:
                context["image_cache"][path] = d
            return d

        fname = Path(fpath).name
        exp = np.nan
        mon = np.nan
        trans = np.nan
        thk_cm = np.nan
        norm_s = np.nan
        bg_norm_used = np.nan
        bg_path_used = ""
        dark_path_used = ""
        bg_score = np.nan
        dark_score = np.nan
        outputs = []
        mode_errors = []
        status = "失败"
        reason = ""

        try:
            run_policy = context.get("run_policy")
            if run_policy is None:
                run_policy = SimpleNamespace(
                    resume_enabled=bool(context.get("resume", False)),
                    overwrite_existing=bool(context.get("overwrite", False)),
                    mode=(
                        "overwrite"
                        if bool(context.get("overwrite", False))
                        else ("resume-skip" if bool(context.get("resume", False)) else "always-run")
                    ),
                    should_skip_existing=lambda exists: bool(exists)
                    and bool(context.get("resume", False))
                    and (not bool(context.get("overwrite", False))),
                )

            expected_targets = self.build_sample_output_targets(context, out_stem)
            if expected_targets and should_skip_all_existing(
                [p.exists() for _, p in expected_targets],
                run_policy,
            ):
                    for mode_tag, p in expected_targets:
                        mode_key = "1d_sector" if mode_tag.startswith("1d_sector") else mode_tag
                        mode_stats[mode_key]["skip"] += 1
                        outputs.append(f"{mode_tag}:{p.name}(existing)")
                    status = "已跳过"
                    reason = "所有模式输出已存在"
                    log_line(f"[跳过] {fname}: 所有输出已存在")
                    row = {
                        "Index": idx,
                        "File": fname,
                        "Status": status,
                        "Reason": reason,
                        "Norm_Mode": context["monitor_mode"],
                        "Exposure_s": exp,
                        "Monitor": mon,
                        "Trans": trans,
                        "Thk_cm": thk_cm,
                        "Norm_s": norm_s,
                        "BG_Norm": bg_norm_used,
                        "BG_Used": bg_path_used,
                        "Dark_Used": dark_path_used,
                        "BG_Score": bg_score,
                        "Dark_Score": dark_score,
                        "ModesSelected": ",".join(context["selected_modes"]),
                        "Outputs": " | ".join(outputs),
                    }
                    return {"row": row, "logs": logs, "mode_stats": mode_stats}

            ai = context["ai_shared"] if not context["parallel"] else pyFAI.load(context["poni_path"])
            sample = fabio.open(fpath)
            d_s = sample.data.astype(np.float64)
            sample_header = getattr(sample, "header", {})

            exp, mon, trans = self.parse_header(fpath, header_dict=sample_header)
            monitor_mode = context["monitor_mode"]
            missing = []
            if mon is None:
                missing.append("mon")
            if trans is None:
                missing.append("trans")
            if monitor_mode == "rate" and exp is None:
                missing.append("exp")
            if missing:
                raise ValueError(f"文件头缺少关键字段: {', '.join(missing)}")

            exp = float(exp) if exp is not None else np.nan
            mon = float(mon)
            trans = float(trans)
            if not (np.isfinite(mon) and np.isfinite(trans) and (np.isfinite(exp) or monitor_mode == "integrated")):
                raise ValueError("文件头参数存在非法值（非有限数）")
            if monitor_mode == "rate" and exp <= 0:
                raise ValueError(f"曝光时间非法: exp={exp}")
            if mon <= 0:
                raise ValueError(f"I0 非法: mon={mon}")
            if not (0 < trans <= 1):
                raise ValueError(f"透过率超范围 (0,1]: {trans}")

            sample_meta = {
                "exp": exp if np.isfinite(exp) else None,
                "mon": mon,
                "trans": trans,
                "mtime": Path(fpath).stat().st_mtime if Path(fpath).exists() else None,
                "shape": tuple(d_s.shape),
            }

            if context["ref_mode"] == "fixed":
                d_dark = context["fixed_dark_data"]
                bg_norm = context["fixed_bg_norm"]
                img_bg_net = context["fixed_bg_net"]
                bg_path_used = context["fixed_bg_path"]
                dark_path_used = context["fixed_dark_path"]
            else:
                bg_ref, bg_score = self.select_best_reference(sample_meta, context["bg_library"], kind="bg")
                dark_ref, dark_score = self.select_best_reference(sample_meta, context["dark_library"], kind="dark")
                if bg_ref is None or dark_ref is None:
                    raise ValueError("自动匹配失败：BG/Dark 库为空或不兼容")

                bg_path_used = bg_ref["path"]
                dark_path_used = dark_ref["path"]
                d_bg = load_data(bg_path_used)
                d_dark = load_data(dark_path_used)
                bg_norm = self.compute_norm_factor(
                    bg_ref.get("exp"),
                    bg_ref.get("mon"),
                    bg_ref.get("trans"),
                    monitor_mode,
                )
                if not np.isfinite(bg_norm) or bg_norm <= 0:
                    bg_norm = context["fixed_bg_norm"]
                    log_line(f"[警告] {fname}: 匹配到的 BG 头参数不完整，回退全局 BG 归一化因子")
                img_bg_net = (d_bg - d_dark) / bg_norm

            self._assert_same_shape(d_s, d_dark, "sample", "dark")
            self._assert_same_shape(d_s, img_bg_net, "sample", "bg_net")
            bg_norm_used = bg_norm

            mask_arr = context["mask_arr"]
            flat_arr = context["flat_arr"]
            if mask_arr is not None and tuple(mask_arr.shape) != tuple(d_s.shape):
                raise ValueError(f"Mask 尺寸不匹配: {mask_arr.shape} vs {d_s.shape}")
            if flat_arr is not None and tuple(flat_arr.shape) != tuple(d_s.shape):
                raise ValueError(f"Flat 尺寸不匹配: {flat_arr.shape} vs {d_s.shape}")

            # --- Thickness Logic ---
            if context["calc_mode"] == "auto":
                if trans >= 0.999 or trans <= 0.001:
                    raise ValueError(f"透过率不适合自动厚度计算: {trans}")
                thk_cm = -math.log(trans) / context["mu"]
            else:
                thk_cm = context["fixed_thk_cm"]
            if not np.isfinite(thk_cm) or thk_cm <= 0:
                raise ValueError(f"厚度计算结果非法: {thk_cm}")

            norm_s = self.compute_norm_factor(exp if np.isfinite(exp) else None, mon, trans, monitor_mode)
            if not np.isfinite(norm_s) or norm_s <= 0:
                raise ValueError(f"样品归一化因子非法: {norm_s}")

            img_net = (d_s - d_dark) / norm_s - context.get("bg_alpha", 1.0) * img_bg_net

            integ_kwargs_common = {
                "correctSolidAngle": context["apply_solid_angle"],
            }
            if context["error_model"] != "none":
                integ_kwargs_common["error_model"] = context["error_model"]
            if mask_arr is not None:
                integ_kwargs_common["mask"] = mask_arr
            if flat_arr is not None:
                integ_kwargs_common["flat"] = flat_arr
            if context["polarization"] is not None:
                integ_kwargs_common["polarization_factor"] = context["polarization"]

            mode_success = 0
            mode_skip = 0
            scale_factor = context["k_factor"] / thk_cm
            expected_total = len(self.build_sample_output_targets(context, out_stem))
            if expected_total <= 0:
                expected_total = len(context["selected_modes"])

            for mode in context["selected_modes"]:
                out_path = self.mode_output_path(context["save_dirs"], mode, out_stem)
                try:
                    if mode != "1d_sector" and run_policy.should_skip_existing(out_path.exists()):
                        outputs.append(f"{mode}:{out_path.name}(existing)")
                        mode_stats[mode]["skip"] += 1
                        mode_skip += 1
                        continue

                    if mode == "1d_full":
                        res = ai.integrate1d(
                            img_net,
                            1000,
                            unit="q_A^-1",
                            **integ_kwargs_common,
                        )
                        i_abs = np.asarray(res.intensity, dtype=np.float64) * scale_factor
                        if getattr(res, "sigma", None) is None:
                            i_err = np.full_like(i_abs, np.nan)
                        else:
                            i_err = np.asarray(res.sigma, dtype=np.float64) * scale_factor
                        issue = self.profile_health_issue(i_abs)
                        if issue:
                            raise ValueError(issue)
                        self.save_profile_table(out_path, res.radial, i_abs, i_err, "Q_A^-1", output_format=context.get("output_format", "tsv"))
                        outputs.append(f"{mode}:{out_path.name}")
                        mode_stats[mode]["ok"] += 1
                        mode_success += 1

                    elif mode == "1d_sector":
                        sector_specs = context["sector_specs"]
                        save_each = bool(context.get("sector_save_each", True))
                        save_sum = bool(context.get("sector_save_combined", False))
                        sector_results = {}
                        multi_sector = len(sector_specs) > 1

                        sum_out_path = None
                        sum_need_write = False
                        if save_sum:
                            sum_out_path = context["sector_combined_dir"] / f"{out_stem}.dat"
                            if run_policy.should_skip_existing(sum_out_path.exists()):
                                outputs.append(f"1d_sector_sum:{sum_out_path.name}(existing)")
                                mode_stats[mode]["skip"] += 1
                                mode_skip += 1
                            else:
                                sum_need_write = True

                        for spec in sector_specs:
                            spec_tag = f"1d_sector{spec['label']}"
                            each_out_path = None
                            need_each_write = False
                            if save_each:
                                each_dir = context["sector_save_dirs"].get(spec["key"])
                                if each_dir is None:
                                    mode_stats[mode]["fail"] += 1
                                    mode_errors.append(f"{spec_tag}: 缺少输出目录映射")
                                    continue
                                each_out_path = each_dir / f"{out_stem}.dat"
                                each_disp = (
                                    f"{each_out_path.parent.name}/{each_out_path.name}"
                                    if multi_sector else each_out_path.name
                                )
                                if run_policy.should_skip_existing(each_out_path.exists()):
                                    outputs.append(f"{spec_tag}:{each_disp}(existing)")
                                    mode_stats[mode]["skip"] += 1
                                    mode_skip += 1
                                else:
                                    need_each_write = True

                            need_result = need_each_write or sum_need_write
                            if not need_result:
                                continue

                            try:
                                res, sec_min_n, sec_max_n, sec_wrap = self.integrate1d_sector(
                                    ai,
                                    img_net,
                                    1000,
                                    spec["sec_min"],
                                    spec["sec_max"],
                                    **integ_kwargs_common,
                                )
                                sector_results[spec["key"]] = res

                                if need_each_write and each_out_path is not None:
                                    i_abs = np.asarray(res.intensity, dtype=np.float64) * scale_factor
                                    if getattr(res, "sigma", None) is None:
                                        i_err = np.full_like(i_abs, np.nan)
                                    else:
                                        i_err = np.asarray(res.sigma, dtype=np.float64) * scale_factor
                                    issue = self.profile_health_issue(i_abs)
                                    if issue:
                                        raise ValueError(issue)
                                    self.save_profile_table(each_out_path, res.radial, i_abs, i_err, "Q_A^-1", output_format=context.get("output_format", "tsv"))
                                    outputs.append(f"{spec_tag}:{each_disp}")
                                    mode_stats[mode]["ok"] += 1
                                    mode_success += 1

                                if sec_wrap:
                                    log_line(
                                        f"[提示] {fname} {spec['label']}: 跨±180°，按 [{sec_min_n:.2f},180] 与 [-180,{sec_max_n:.2f}] 合并积分"
                                    )
                            except Exception as sector_err:
                                mode_stats[mode]["fail"] += 1
                                mode_errors.append(f"{spec_tag}: {sector_err}")

                        if sum_need_write and sum_out_path is not None:
                            missing = [s for s in sector_specs if s["key"] not in sector_results]
                            if missing:
                                miss_lbl = ",".join([m["label"] for m in missing[:3]])
                                if len(missing) > 3:
                                    miss_lbl += ",..."
                                mode_stats[mode]["fail"] += 1
                                mode_errors.append(f"1d_sector_sum: 扇区结果不完整，无法合并 ({miss_lbl})")
                            else:
                                try:
                                    merge = self.merge_integrate1d_results(
                                        [sector_results[s["key"]] for s in sector_specs]
                                    )
                                    i_abs = np.asarray(merge.intensity, dtype=np.float64) * scale_factor
                                    if getattr(merge, "sigma", None) is None:
                                        i_err = np.full_like(i_abs, np.nan)
                                    else:
                                        i_err = np.asarray(merge.sigma, dtype=np.float64) * scale_factor
                                    issue = self.profile_health_issue(i_abs)
                                    if issue:
                                        raise ValueError(issue)
                                    self.save_profile_table(sum_out_path, merge.radial, i_abs, i_err, "Q_A^-1", output_format=context.get("output_format", "tsv"))
                                    outputs.append(f"1d_sector_sum:{sum_out_path.name}")
                                    mode_stats[mode]["ok"] += 1
                                    mode_success += 1
                                except Exception as sum_err:
                                    mode_stats[mode]["fail"] += 1
                                    mode_errors.append(f"1d_sector_sum: {sum_err}")

                    elif mode == "radial_chi":
                        qmin = context["qmin"]
                        qmax = context["qmax"]
                        try:
                            res = ai.integrate_radial(
                                img_net,
                                360,
                                unit="chi_deg",
                                radial_unit="q_A^-1",
                                radial_range=(qmin, qmax),
                                **integ_kwargs_common,
                            )
                        except TypeError as radial_err:
                            if "radial_unit" not in str(radial_err):
                                raise
                            # 兼容旧版 pyFAI: 默认 radial_range 单位是 q_nm^-1
                            res = ai.integrate_radial(
                                img_net,
                                360,
                                unit="chi_deg",
                                radial_range=(qmin * 10.0, qmax * 10.0),
                                **integ_kwargs_common,
                            )
                            log_line(f"[警告] {fname}: pyFAI 不支持 radial_unit，q 区间已按 A^-1->nm^-1 转换")
                        i_abs = np.asarray(res.intensity, dtype=np.float64) * scale_factor
                        if getattr(res, "sigma", None) is None:
                            i_err = np.full_like(i_abs, np.nan)
                        else:
                            i_err = np.asarray(res.sigma, dtype=np.float64) * scale_factor
                        issue = self.profile_health_issue(i_abs)
                        if issue:
                            raise ValueError(issue)
                        self.save_profile_table(out_path, res.radial, i_abs, i_err, "Chi_deg", output_format=context.get("output_format", "tsv"))
                        outputs.append(f"{mode}:{out_path.name}")
                        mode_stats[mode]["ok"] += 1
                        mode_success += 1

                    else:
                        raise ValueError(f"不支持的积分模式: {mode}")

                except Exception as mode_err:
                    mode_stats[mode]["fail"] += 1
                    mode_errors.append(f"{mode}: {mode_err}")

            if mode_skip == expected_total and mode_success == 0 and not mode_errors:
                status = "已跳过"
                reason = "所有模式输出已存在"
                log_line(f"[跳过] {fname}: 所有输出已存在")
            elif mode_success > 0 and not mode_errors:
                status = "成功"
                log_line(f"[成功] {fname} -> {', '.join(outputs)}")
            elif mode_success > 0:
                status = "部分成功"
                reason = " | ".join(mode_errors)
                log_line(f"[部分成功] {fname} -> {', '.join(outputs)}")
                log_line(f"[模式失败] {fname}: {reason}")
            else:
                status = "失败"
                reason = " | ".join(mode_errors) if mode_errors else "无输出"
                log_line(f"[失败] {fname}: {reason}")

        except Exception as file_err:
            status = "失败"
            reason = str(file_err)
            log_line(f"[失败] {fname}: {reason}")

        row = {
            "Index": idx,
            "File": fname,
            "Status": status,
            "Reason": reason,
            "Norm_Mode": context["monitor_mode"],
            "Exposure_s": exp,
            "Monitor": mon,
            "Trans": trans,
            "Thk_cm": thk_cm,
            "Norm_s": norm_s,
            "BG_Norm": bg_norm_used,
            "BG_Used": bg_path_used,
            "Dark_Used": dark_path_used,
            "BG_Score": bg_score,
            "Dark_Score": dark_score,
            "ModesSelected": ",".join(context["selected_modes"]),
            "Outputs": " | ".join(outputs),
        }
        return {"row": row, "logs": logs, "mode_stats": mode_stats}

    # =========================================================================
    # Logic: Batch (2D Subtraction Kernel + Error)
    # =========================================================================
    def run_batch(self):
        try:
            if not self.t2_files: raise ValueError("队列为空：请先添加样品文件。")
            k = float(self.global_vars["k_factor"].get())
            bg_p = self.global_vars["bg_path"].get()
            dk_p = self.global_vars["dark_path"].get()
            poni = self.global_vars["poni_path"].get()
            
            if k <= 0: raise ValueError("K 因子无效（必须 > 0）。")
            if not all([bg_p, dk_p, poni]): raise ValueError("缺少背景/暗场/poni 文件。")
            monitor_mode = self.get_monitor_mode()
            self.log(f"[配置] I0 归一化模式: {monitor_mode} (norm={self.monitor_norm_formula(monitor_mode)})")
            self.log(f"[配置] SolidAngle 修正: {'ON' if bool(self.t2_apply_solid_angle.get()) else 'OFF'}")

            files = list(dict.fromkeys(self.t2_files))
            if len(files) < len(self.t2_files):
                self.log(f"[提示] 队列去重：移除重复文件 {len(self.t2_files) - len(files)} 个")
                self.t2_files = files
                self.lb_batch.delete(0, tk.END)
                for f in self.t2_files:
                    self.lb_batch.insert(tk.END, Path(f).name)
                self.refresh_queue_status()

            selected_modes = self.get_selected_modes()
            if not selected_modes:
                raise ValueError("未选择积分模式：请至少勾选一种（全环/扇区/织构）。")

            apply_solid_angle = bool(self.t2_apply_solid_angle.get())
            k_solid_state = str(self.global_vars["k_solid_angle"].get()).strip().lower()
            if k_solid_state in ("on", "off"):
                k_solid_bool = (k_solid_state == "on")
                if apply_solid_angle != k_solid_bool:
                    raise ValueError(
                        "SolidAngle 设置与 K 因子标定状态不一致："
                        f"K 使用 {'ON' if k_solid_bool else 'OFF'}，当前批处理为 {'ON' if apply_solid_angle else 'OFF'}。"
                        "请切换为一致设置，或重新运行 Tab1 标定。"
                    )
            else:
                self.log("[警告] 当前 K 因子缺少 SolidAngle 状态信息，无法自动校验一致性。建议重新标定 K。")

            ai = pyFAI.load(poni)
            if "radial_chi" in selected_modes and not hasattr(ai, "integrate_radial"):
                raise RuntimeError("当前 pyFAI 不支持 integrate_radial，请取消织构模式或升级 pyFAI。")
            sector_specs = []
            sector_save_each = bool(self.t2_sector_save_each.get())
            sector_save_combined = bool(self.t2_sector_save_combined.get())
            if "1d_sector" in selected_modes:
                sector_specs = self.get_t2_sector_specs()
                if not sector_save_each and not sector_save_combined:
                    raise ValueError("已启用扇区模式，但未选择任何扇区输出（请勾选“分扇区分别保存”或“扇区合并保存”）。")
                sec_brief = "; ".join([f"{s['index']}:{s['label']}" for s in sector_specs[:6]])
                if len(sector_specs) > 6:
                    sec_brief += "; ..."
                self.log(f"[配置] 扇区列表({len(sector_specs)}): {sec_brief}")
            if "radial_chi" in selected_modes and self.t2_rad_qmin.get() >= self.t2_rad_qmax.get():
                raise ValueError("织构 q 范围无效：qmin 必须 < qmax。")

            fixed_dark_data = fabio.open(dk_p).data.astype(np.float64)
            bg_paths = self.split_path_list(bg_p)
            if not bg_paths:
                raise ValueError("缺少背景文件。")
            fixed_bg_net, bg_norm_list, bg_used_paths = self.build_composite_bg_net(
                bg_paths=bg_paths,
                d_dark=fixed_dark_data,
                monitor_mode=monitor_mode,
                fallback_triplet=(
                    self.global_vars["bg_exp"].get(),
                    self.global_vars["bg_i0"].get(),
                    self.global_vars["bg_t"].get(),
                ),
                ref_shape=fixed_dark_data.shape,
            )
            fixed_bg_norm = float(np.nanmedian(np.asarray(bg_norm_list, dtype=np.float64)))
            if not np.isfinite(fixed_bg_norm) or fixed_bg_norm <= 0:
                raise ValueError("背景归一化因子 <= 0，请检查 BG 的 Time/I0/T。")

            ref_mode = self.t2_ref_mode.get()
            if ref_mode not in ("fixed", "auto"):
                raise ValueError(f"未知参考模式: {ref_mode}")

            # 防止 BG 归一化因子量级异常导致过扣背景（例如 T 被误判成百分数）
            probe_norms = []
            for fp in files[: min(20, len(files))]:
                try:
                    e, m, t = self.parse_header(fp)
                    n = self.compute_norm_factor(e, m, t, monitor_mode)
                    if np.isfinite(n) and n > 0:
                        probe_norms.append(float(n))
                except Exception:
                    continue
            if probe_norms:
                med_sample_norm = float(np.nanmedian(np.asarray(probe_norms, dtype=np.float64)))
                if np.isfinite(med_sample_norm) and med_sample_norm > 0:
                    bg_ratio = fixed_bg_norm / med_sample_norm
                    if bg_ratio < 0.01 or bg_ratio > 100.0:
                        msg = (
                            "BG_Norm 与样品 Norm_s 量级差异过大 "
                            f"(BG/样品中位={bg_ratio:.3g}, BG_Norm={fixed_bg_norm:.6g}, "
                            f"SampleMed={med_sample_norm:.6g})，请检查 BG 的 Time/I0/T、I0 语义或头字段映射。"
                        )
                        if ref_mode == "fixed":
                            raise ValueError(msg)
                        self.log(f"[警告] {msg}")

            bg_library = self.build_reference_library(self.t2_bg_candidates)
            dark_library = self.build_reference_library(self.t2_dark_candidates)
            if ref_mode == "auto":
                if not bg_library:
                    raise ValueError("自动匹配模式下 BG 库为空。")
                if not dark_library:
                    raise ValueError("自动匹配模式下 Dark 库为空。")

            if self.t2_strict_instrument.get():
                tol_pct = self.t2_instr_tol_pct.get()
                issues = self.check_instrument_consistency(files, poni_path=poni, tol_pct=tol_pct)
                if issues:
                    preview = "\n".join(issues[:10])
                    tail = "\n..." if len(issues) > 10 else ""
                    raise ValueError(f"仪器一致性检查失败（前10项）:\n{preview}{tail}")

            mask_arr = self.load_optional_array(self.t2_mask_path.get().strip(), "Mask")
            if mask_arr is not None:
                mask_arr = np.asarray(mask_arr) != 0
            flat_arr = self.load_optional_array(self.t2_flat_path.get().strip(), "Flat")
            if flat_arr is not None:
                flat_arr = np.asarray(flat_arr, dtype=np.float64)

            pol = self.t2_polarization.get()
            if not np.isfinite(pol) or pol < -1.0 or pol > 1.0:
                raise ValueError("Polarization 因子必须在 [-1, 1]。")
            error_model = self.t2_error_model.get().strip().lower()
            if error_model not in ("azimuthal", "poisson", "none"):
                raise ValueError("误差模型仅支持 azimuthal / poisson / none。")

            custom_out_root = self.t2_output_root.get().strip() if hasattr(self, "t2_output_root") else ""
            if custom_out_root:
                out_root = Path(custom_out_root).expanduser()
                out_root.mkdir(parents=True, exist_ok=True)
                self.log(f"[配置] 输出根目录(自定义): {out_root}")
            else:
                out_root = Path(files[0]).parent
                self.log(f"[配置] 输出根目录(默认样品目录): {out_root}")
            save_dirs = {}
            sector_save_dirs = {}
            sector_combined_dir = None
            for mode in selected_modes:
                if mode == "1d_sector":
                    base = out_root / "processed_robust_1d_sector"
                    base.mkdir(exist_ok=True)
                    save_dirs[mode] = base
                    if sector_save_each:
                        multi = len(sector_specs) > 1
                        for spec in sector_specs:
                            d = base / spec["key"] if multi else base
                            d.mkdir(exist_ok=True)
                            sector_save_dirs[spec["key"]] = d
                    if sector_save_combined:
                        sector_combined_dir = out_root / "processed_robust_1d_sector_combined"
                        sector_combined_dir.mkdir(exist_ok=True)
                else:
                    d = out_root / f"processed_robust_{mode}"
                    d.mkdir(exist_ok=True)
                    save_dirs[mode] = d
            report_dir = out_root / "processed_robust_reports"
            report_dir.mkdir(exist_ok=True)
            stem_map = self.build_output_stem_map(files)

            self.prog_bar["maximum"] = len(files)
            self.prog_bar["value"] = 0
            mu = self.t2_mu.get()
            if self.t2_calc_mode.get() == "auto" and mu <= 0:
                raise ValueError("自动厚度模式要求 mu > 0。")
            if self.t2_calc_mode.get() == "fixed" and self.t2_fixed_thk.get() <= 0:
                raise ValueError("固定厚度必须 > 0 mm。")
            fixed_thk_cm = self.t2_fixed_thk.get() / 10.0

            try:
                workers = max(1, int(self.t2_workers.get()))
            except Exception:
                raise ValueError("并行线程数必须为正整数。")
            overwrite = bool(self.t2_overwrite.get())
            resume = bool(self.t2_resume_enabled.get())
            if parse_run_policy is not None:
                run_policy = parse_run_policy(resume_enabled=resume, overwrite_existing=overwrite)
            else:
                run_policy = SimpleNamespace(
                    resume_enabled=resume,
                    overwrite_existing=overwrite,
                    mode=("overwrite" if overwrite else ("resume-skip" if resume else "always-run")),
                    should_skip_existing=lambda exists: bool(exists) and resume and (not overwrite),
                )
            self.log(f"[配置] Existing-output 策略: {run_policy.mode} (resume={resume}, overwrite={overwrite})")

            context = {
                "selected_modes": selected_modes,
                "save_dirs": save_dirs,
                "poni_path": poni,
                "ai_shared": ai,
                "parallel": workers > 1,
                "cache_lock": threading.Lock(),
                "image_cache": {},
                "k_factor": k,
                "monitor_mode": monitor_mode,
                "calc_mode": self.t2_calc_mode.get(),
                "mu": mu,
                "fixed_thk_cm": fixed_thk_cm,
                "fixed_bg_net": fixed_bg_net,
                "fixed_dark_data": fixed_dark_data,
                "fixed_bg_norm": fixed_bg_norm,
                "fixed_bg_path": ";".join(bg_used_paths),
                "fixed_dark_path": dk_p,
                "ref_mode": ref_mode,
                "bg_library": bg_library,
                "dark_library": dark_library,
                "mask_arr": mask_arr,
                "flat_arr": flat_arr,
                "error_model": error_model,
                "apply_solid_angle": bool(self.t2_apply_solid_angle.get()),
                "polarization": float(pol),
                "sector_specs": sector_specs,
                "sector_save_each": sector_save_each,
                "sector_save_combined": sector_save_combined,
                "sector_save_dirs": sector_save_dirs,
                "sector_combined_dir": sector_combined_dir,
                "qmin": float(self.t2_rad_qmin.get()),
                "qmax": float(self.t2_rad_qmax.get()),
                "overwrite": overwrite,
                "resume": resume,
                "run_policy": run_policy,
                "bg_alpha": float(self.t2_alpha.get()) if self.t2_alpha_enabled.get() else 1.0,
                "output_format": self.t2_output_format.get() if hasattr(self, "t2_output_format") else "tsv",
            }

            rows = []
            sample_success = 0
            sample_partial = 0
            sample_fail = 0
            sample_skip = 0
            mode_ok_count = {m: 0 for m in selected_modes}
            mode_fail_count = {m: 0 for m in selected_modes}
            mode_skip_count = {m: 0 for m in selected_modes}

            tasks = [(idx, fpath, stem_map[fpath]) for idx, fpath in enumerate(files)]
            processed = 0

            if workers == 1:
                for idx, fpath, out_stem in tasks:
                    result = self.process_sample_task(idx, fpath, out_stem, context)
                    rows.append(result["row"])
                    for line in result["logs"]:
                        self.log(line)

                    for m in selected_modes:
                        mode_ok_count[m] += result["mode_stats"][m]["ok"]
                        mode_fail_count[m] += result["mode_stats"][m]["fail"]
                        mode_skip_count[m] += result["mode_stats"][m]["skip"]

                    st = result["row"]["Status"]
                    if st == "成功":
                        sample_success += 1
                    elif st == "部分成功":
                        sample_partial += 1
                    elif st == "已跳过":
                        sample_skip += 1
                    else:
                        sample_fail += 1

                    processed += 1
                    self.prog_bar["value"] = processed
                    self.root.update_idletasks()
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                    futures = {
                        ex.submit(self.process_sample_task, idx, fpath, out_stem, context): (idx, fpath)
                        for idx, fpath, out_stem in tasks
                    }
                    for fut in concurrent.futures.as_completed(futures):
                        result = fut.result()
                        rows.append(result["row"])
                        for line in result["logs"]:
                            self.log(line)

                        for m in selected_modes:
                            mode_ok_count[m] += result["mode_stats"][m]["ok"]
                            mode_fail_count[m] += result["mode_stats"][m]["fail"]
                            mode_skip_count[m] += result["mode_stats"][m]["skip"]

                        st = result["row"]["Status"]
                        if st == "成功":
                            sample_success += 1
                        elif st == "部分成功":
                            sample_partial += 1
                        elif st == "已跳过":
                            sample_skip += 1
                        else:
                            sample_fail += 1

                        processed += 1
                        self.prog_bar["value"] = processed
                        self.root.update_idletasks()

            rows.sort(key=lambda x: x.get("Index", 0))
            for r in rows:
                r.pop("Index", None)

            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            report_path = report_dir / f"batch_report_{stamp}.csv"
            pd.DataFrame(rows).to_csv(report_path, index=False, encoding="utf-8-sig")

            tab3_meta_stamp = None
            tab3_meta_latest = None
            tab3_meta_rows = 0
            try:
                tab3_meta_stamp, tab3_meta_latest, tab3_meta_rows = self.export_tab3_metadata_from_report(
                    report_path,
                    stamp=stamp,
                )
            except Exception as e:
                self.log(f"[警告] 自动导出 Tab3 metadata 失败: {e}")

            meta_path = report_dir / f"run_meta_{stamp}.json"
            output_dirs_meta = {}
            for m in selected_modes:
                if m != "1d_sector":
                    output_dirs_meta[m] = str(save_dirs[m])
                    continue
                output_dirs_meta["1d_sector_base"] = str(save_dirs[m])
                if sector_save_each:
                    output_dirs_meta["1d_sector_each"] = {
                        spec["label"]: str(sector_save_dirs.get(spec["key"], save_dirs[m]))
                        for spec in sector_specs
                    }
                if sector_save_combined and sector_combined_dir is not None:
                    output_dirs_meta["1d_sector_sum"] = str(sector_combined_dir)

            meta = {
                "timestamp": stamp,
                "selected_modes": selected_modes,
                "files_total": len(files),
                "workers": workers,
                "k_factor": k,
                "monitor_mode": monitor_mode,
                "norm_formula": self.monitor_norm_formula(monitor_mode),
                "calc_mode": self.t2_calc_mode.get(),
                "mu_cm^-1": mu,
                "fixed_thickness_mm": self.t2_fixed_thk.get(),
                "reference_mode": ref_mode,
                "fixed_bg_path": bg_p,
                "fixed_dark_path": dk_p,
                "bg_library_count": len(bg_library),
                "dark_library_count": len(dark_library),
                "error_model": error_model,
                "correct_solid_angle": bool(self.t2_apply_solid_angle.get()),
                "k_solid_angle_state": str(self.global_vars["k_solid_angle"].get()),
                "polarization_factor": pol,
                "mask_path": self.t2_mask_path.get().strip(),
                "flat_path": self.t2_flat_path.get().strip(),
                "resume_enabled": resume,
                "overwrite": overwrite,
                "existing_output_policy": run_policy.mode,
                "strict_instrument": bool(self.t2_strict_instrument.get()),
                "instrument_tol_pct": float(self.t2_instr_tol_pct.get()),
                "sector_specs": sector_specs,
                "sector_save_each": sector_save_each,
                "sector_save_combined": sector_save_combined,
                "output_root": str(out_root),
                "output_root_custom": bool(custom_out_root),
                "output_dirs": output_dirs_meta,
                "report_csv": str(report_path),
                "tab3_metadata_csv": str(tab3_meta_stamp) if tab3_meta_stamp else None,
                "tab3_metadata_latest": str(tab3_meta_latest) if tab3_meta_latest else None,
                "tab3_metadata_rows": int(tab3_meta_rows),
                "sample_summary": {
                    "success": sample_success,
                    "partial": sample_partial,
                    "skipped": sample_skip,
                    "failed": sample_fail,
                },
                "mode_summary": {
                    m: {"ok": mode_ok_count[m], "skip": mode_skip_count[m], "fail": mode_fail_count[m]}
                    for m in selected_modes
                },
                "versions": {
                    "numpy": np.__version__,
                    "pandas": pd.__version__,
                    "pyFAI": getattr(pyFAI, "__version__", "unknown"),
                    "fabio": getattr(fabio, "__version__", "unknown"),
                },
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            mode_summary = "\n".join(
                [f"{m}: 成功{mode_ok_count[m]} / 跳过{mode_skip_count[m]} / 失败{mode_fail_count[m]}" for m in selected_modes]
            )
            dir_lines = []
            for m in selected_modes:
                if m != "1d_sector":
                    dir_lines.append(f"{m} -> {save_dirs[m]}")
                    continue
                if sector_save_each:
                    if len(sector_specs) > 1:
                        dir_lines.append(f"1d_sector(each) -> {save_dirs[m]}/sector_*")
                    else:
                        dir_lines.append(f"1d_sector(each) -> {save_dirs[m]}")
                if sector_save_combined and sector_combined_dir is not None:
                    dir_lines.append(f"1d_sector_sum -> {sector_combined_dir}")
            dir_summary = "\n".join(dir_lines)

            messagebox.showinfo(
                "批处理完成",
                (
                    "稳健批处理完成。\n"
                    f"样品成功: {sample_success}\n"
                    f"样品部分成功: {sample_partial}\n"
                    f"样品已跳过: {sample_skip}\n"
                    f"样品失败: {sample_fail}\n"
                    f"模式统计:\n{mode_summary}\n"
                    f"输出目录:\n{dir_summary}\n"
                    f"报告: {report_path.name}\n"
                    f"Tab3 metadata: {tab3_meta_stamp.name if tab3_meta_stamp else '导出失败'}\n"
                    f"元数据: {meta_path.name}"
                ),
            )

        except Exception as e:
            self.show_error("msg_batch_error_title", f"{e}\n{traceback.format_exc()}")

    # --- Helpers ---
    def refresh_queue_status(self):
        if hasattr(self, "t2_queue_info"):
            total = len(getattr(self, "t2_files", []))
            uniq = len(dict.fromkeys(getattr(self, "t2_files", [])))
            self.t2_queue_info.set(self._fmt_queue_info(total, uniq))

        if hasattr(self, "t2_out_hint_var"):
            modes = self.get_selected_modes()
            if not modes:
                self.t2_out_hint_var.set(self.tr("out_none_mode"))
            else:
                dirs = []
                for m in modes:
                    if m != "1d_sector":
                        dirs.append(f"processed_robust_{m}")
                        continue
                    dirs.append("processed_robust_1d_sector")
                    if hasattr(self, "t2_sector_save_combined") and self.t2_sector_save_combined.get():
                        dirs.append("processed_robust_1d_sector_combined")
                sec_note = ""
                if "1d_sector" in modes:
                    try:
                        n_sec = len(self.get_t2_sector_specs())
                        sec_note = f"（扇区数={n_sec}）"
                    except Exception:
                        sec_note = "（扇区配置待确认）"
                custom_root = self.t2_output_root.get().strip() if hasattr(self, "t2_output_root") else ""
                if custom_root:
                    self.t2_out_hint_var.set(
                        f"{self.tr('out_write_prefix')} {custom_root}: {', '.join(dirs)}{sec_note}"
                    )
                else:
                    self.t2_out_hint_var.set(f"{self.tr('out_auto_prefix')}: {', '.join(dirs)}{sec_note}")

    def _evaluate_preflight_gate(self, total_files, failed_files, warnings_count, risky_files=0):
        if evaluate_preflight_gate is not None:
            return evaluate_preflight_gate(
                total_files=total_files,
                failed_files=failed_files,
                warning_count=warnings_count,
                risky_files=risky_files,
            )

        score = int(failed_files) * 5 + int(risky_files) * 2 + int(warnings_count)
        if int(total_files) <= 0 or int(failed_files) > 0:
            level = "BLOCKED"
        elif score > 0:
            level = "CAUTION"
        else:
            level = "READY"
        return SimpleNamespace(
            level=level,
            score=score,
            total_files=int(total_files),
            failed_files=int(failed_files),
            warning_count=int(warnings_count),
            risky_files=int(risky_files),
        )

    def _preflight_label_text(self, gate):
        if self.language == "en":
            return (
                f"Preflight Gate: {gate.level} | score={gate.score} | "
                f"files={gate.total_files}, failed={gate.failed_files}, "
                f"warnings={gate.warning_count}, risky={gate.risky_files}"
            )
        return (
            f"预检关卡: {gate.level} | score={gate.score} | "
            f"文件={gate.total_files}, 失败={gate.failed_files}, "
            f"警告={gate.warning_count}, 风险={gate.risky_files}"
        )

    def dry_run(self):
        if not self.t2_files: return
        files = list(dict.fromkeys(self.t2_files))
        rows = []
        failed_files = 0
        risky_files = 0
        mu = self.t2_mu.get()
        monitor_mode = self.get_monitor_mode()
        mode = self.t2_calc_mode.get()
        selected_modes = self.get_selected_modes()
        warnings = []
        inst_issues = []
        sample_norms = []
        bg_norm = self.compute_norm_factor(
            self.global_vars["bg_exp"].get(),
            self.global_vars["bg_i0"].get(),
            self.global_vars["bg_t"].get(),
            monitor_mode,
        )

        if not selected_modes:
            warnings.append(self.tr("warn_no_integ_mode"))
        sector_specs = []
        if "1d_sector" in selected_modes:
            try:
                sector_specs = self.get_t2_sector_specs()
                if not self.t2_sector_save_each.get() and not self.t2_sector_save_combined.get():
                    warnings.append(self.tr("warn_sector_no_output"))
            except Exception as e:
                warnings.append(self.tr("warn_sector_angle_invalid").format(e=e))
        if "radial_chi" in selected_modes and self.t2_rad_qmin.get() >= self.t2_rad_qmax.get():
            warnings.append(self.tr("warn_texture_q_invalid"))
        if mode == "auto" and mu <= 0:
            warnings.append(self.tr("warn_auto_thk_mu"))
        if self.t2_calc_mode.get() == "fixed" and self.t2_fixed_thk.get() <= 0:
            warnings.append(self.tr("warn_fix_thk_le_zero"))
        if self.t2_ref_mode.get() == "auto":
            if not self.t2_bg_candidates:
                warnings.append(self.tr("warn_auto_bg_empty"))
            if not self.t2_dark_candidates:
                warnings.append(self.tr("warn_auto_dark_empty"))
        if self.t2_strict_instrument.get():
            inst_issues = self.check_instrument_consistency(
                files,
                poni_path=self.global_vars["poni_path"].get(),
                tol_pct=self.t2_instr_tol_pct.get(),
            )
            if inst_issues:
                warnings.append(self.tr("warn_inst_issues").format(n=len(inst_issues)))

        bg_library = self.build_reference_library(self.t2_bg_candidates) if self.t2_ref_mode.get() == "auto" else []
        dark_library = self.build_reference_library(self.t2_dark_candidates) if self.t2_ref_mode.get() == "auto" else []

        for fp in files:
            e, m, t = self.parse_header(fp)
            stat = self.tr("status_ok")
            d_mm = np.nan
            bg_match = "-"
            dark_match = "-"

            missing = []
            if m is None:
                missing.append("MON")
            if t is None:
                missing.append("T")
            if monitor_mode == "rate" and e is None:
                missing.append("EXP")

            if missing:
                stat = f"Missing header fields: {','.join(missing)}" if self.language == "en" else f"缺少文件头字段: {','.join(missing)}"
            else:
                if e is not None:
                    e = float(e)
                m = float(m)
                t = float(t)
                n = self.compute_norm_factor(e if e is not None else None, m, t, monitor_mode)
                if np.isfinite(n) and n > 0:
                    sample_norms.append(float(n))
                if monitor_mode == "rate" and e <= 0:
                    stat = "Error: EXP <= 0" if self.language == "en" else "错误: EXP <= 0"
                elif m <= 0:
                    stat = "Error: MON <= 0" if self.language == "en" else "错误: MON <= 0"
                elif not (0 < t <= 1):
                    stat = "Error: T outside (0,1]" if self.language == "en" else "错误: T 超出 (0,1]"
                elif mode == "auto":
                    if mu <= 0:
                        stat = "Error: MU <= 0" if self.language == "en" else "错误: MU <= 0"
                    elif t >= 0.999 or t <= 0.001:
                        stat = "Error: T unsuitable for auto-thickness" if self.language == "en" else "错误: T 不适合自动厚度"
                    else:
                        d_mm = (-math.log(t) / mu) * 10.0
                else:
                    d_mm = self.t2_fixed_thk.get()

            if self.t2_ref_mode.get() == "auto":
                try:
                    img = fabio.open(fp)
                    smeta = {
                        "exp": e if (e is not None and np.isfinite(e)) else None,
                        "mon": m if m is not None else None,
                        "trans": t if t is not None else None,
                        "mtime": Path(fp).stat().st_mtime if Path(fp).exists() else None,
                        "shape": tuple(img.data.shape),
                    }
                    bg_ref, _ = self.select_best_reference(smeta, bg_library, kind="bg")
                    dk_ref, _ = self.select_best_reference(smeta, dark_library, kind="dark")
                    bg_match = Path(bg_ref["path"]).name if bg_ref else self.tr("status_no_match")
                    dark_match = Path(dk_ref["path"]).name if dk_ref else self.tr("status_no_match")
                    if bg_ref is None or dk_ref is None:
                        risky_files += 1
                except Exception:
                    bg_match = self.tr("status_match_fail")
                    dark_match = self.tr("status_match_fail")
                    risky_files += 1

            if stat != self.tr("status_ok"):
                failed_files += 1

            rows.append({
                "File": Path(fp).name,
                "Exp_s": e if e is not None else np.nan,
                "Mon": m if m is not None else np.nan,
                "Trans": t if t is not None else np.nan,
                "CalcThk_mm": round(d_mm, 4) if np.isfinite(d_mm) else np.nan,
                "BG_Match": bg_match,
                "Dark_Match": dark_match,
                "Status": stat,
            })

        if np.isfinite(bg_norm) and bg_norm > 0 and sample_norms:
            med_sample_norm = float(np.nanmedian(np.asarray(sample_norms, dtype=np.float64)))
            if np.isfinite(med_sample_norm) and med_sample_norm > 0:
                ratio = bg_norm / med_sample_norm
                if ratio < 0.01 or ratio > 100.0:
                    warnings.append(
                        self.tr("warn_bg_norm_mismatch").format(
                            ratio=ratio, bg_norm=bg_norm, med=med_sample_norm,
                        )
                    )

        gate = self._evaluate_preflight_gate(
            total_files=len(files),
            failed_files=failed_files,
            warnings_count=len(warnings),
            risky_files=risky_files,
        )
        
        top = tk.Toplevel(self.root)
        top.title(self.tr("title_t2_dryrun"))
        txt = tk.Text(top, font=("Consolas",9)); txt.pack(fill="both", expand=True)
        self._register_native_widget(txt)
        txt.insert(tk.END, f"{self._preflight_label_text(gate)}\n")
        txt.insert(tk.END, f"{self.tr('pre_i0_norm')} {monitor_mode} (norm={self.monitor_norm_formula(monitor_mode)})\n")
        txt.insert(tk.END, f"{self.tr('pre_integ_mode')} {','.join(selected_modes) if selected_modes else self.tr('pre_integ_none')}\n")
        if "1d_sector" in selected_modes:
            txt.insert(
                tk.END,
                f"{self.tr('pre_sector_output')} each={'ON' if self.t2_sector_save_each.get() else 'OFF'}, "
                f"sum={'ON' if self.t2_sector_save_combined.get() else 'OFF'}\n",
            )
            if sector_specs:
                sec_short = "; ".join([f"{s['index']}:{s['label']}" for s in sector_specs[:8]])
                if len(sector_specs) > 8:
                    sec_short += "; ..."
                txt.insert(tk.END, f"{self.tr('pre_sector_list')} {sec_short}\n")
        txt.insert(tk.END, f"{self.tr('pre_ref_mode')} {self.t2_ref_mode.get()}\n")
        txt.insert(tk.END, f"{self.tr('pre_error_model')} {self.t2_error_model.get()}\n")
        txt.insert(tk.END, f"{self.tr('pre_workers')} {self.t2_workers.get()}\n")
        txt.insert(tk.END, "-"*80 + "\n")
        if warnings:
            txt.insert(tk.END, f"{self.tr('pre_warning_header')}\n")
            for w in warnings:
                txt.insert(tk.END, f"- {w}\n")
            if inst_issues:
                for issue in inst_issues[:20]:
                    txt.insert(tk.END, f"  * {issue}\n")
                if len(inst_issues) > 20:
                    txt.insert(tk.END, "  * ...\n")
        else:
            txt.insert(tk.END, f"{self.tr('pre_pass_t2')}\n")
        txt.insert(tk.END, "-"*80 + "\n")
        txt.insert(tk.END, pd.DataFrame(rows).to_string(index=False))

    def get_t2_preview_sample_path(self):
        # 优先使用列表当前选中项；未选中时使用队列第一个；仍为空则弹文件选择。
        try:
            sel = self.lb_batch.curselection() if hasattr(self, "lb_batch") else ()
            if sel:
                idx = int(sel[0])
                if 0 <= idx < len(self.t2_files):
                    return self.t2_files[idx]
        except Exception:
            pass

        if getattr(self, "t2_files", None):
            fs = list(dict.fromkeys(self.t2_files))
            if fs:
                return fs[0]

        return filedialog.askopenfilename(
            filetypes=[("Image", "*.tif *.tiff *.edf *.cbf"), ("All Files", "*.*")]
        )

    def _compute_t2_chi_map_deg(self, ai, shape):
        # 与 pyFAI azimuth_range 定义一致：0°右、+90°下、-90°上、±180°左
        try:
            chi_rad = np.asarray(ai.center_array(shape, unit="chi_rad"), dtype=np.float64)
        except Exception:
            chi_rad = np.asarray(ai.chiArray(shape), dtype=np.float64)
        chi_deg = np.rad2deg(chi_rad)
        chi_deg = ((chi_deg + 180.0) % 360.0) - 180.0
        return chi_deg

    def _compute_t2_q_map_a_inv(self, ai, shape):
        # 优先显式 A^-1；旧版兼容退回 qArray(nm^-1) 再 /10。
        try:
            q_map = np.asarray(ai.center_array(shape, unit="q_A^-1"), dtype=np.float64)
            return q_map, "q_A^-1"
        except Exception:
            q_map = np.asarray(ai.qArray(shape), dtype=np.float64) / 10.0
            return q_map, "q_nm^-1/10"

    def _get_t2_preview_context(self):
        sample_path = self.get_t2_preview_sample_path()
        if not sample_path:
            return None

        poni_path = self.global_vars["poni_path"].get().strip()
        if not poni_path:
            raise ValueError("请先在 Tab1/Tab2 设置 poni 文件。")

        ai = pyFAI.load(poni_path)
        data = fabio.open(sample_path).data.astype(np.float64)
        if data.ndim != 2:
            raise ValueError(f"样品图像维度错误: {data.shape}")

        valid_mask = np.isfinite(data)
        mask_path = self.t2_mask_path.get().strip() if hasattr(self, "t2_mask_path") else ""
        if mask_path:
            mask_arr = np.asarray(self.load_optional_array(mask_path, "Mask")) != 0
            if mask_arr.shape != data.shape:
                raise ValueError(f"Mask 尺寸不匹配: mask{mask_arr.shape} vs image{data.shape}")
            valid_mask &= ~mask_arr

        finite = data[valid_mask]
        if finite.size == 0:
            raise ValueError("可用图像像素为空（可能被 mask 全部屏蔽）。")

        lo = float(np.nanpercentile(finite, 1.0))
        hi = float(np.nanpercentile(finite, 99.5))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo = float(np.nanmin(finite))
            hi = float(np.nanmax(finite))
            if hi <= lo:
                hi = lo + 1.0
        show_img = np.clip(data, lo, hi)
        show_img = np.where(np.isfinite(show_img), show_img, lo)

        try:
            cy = float(ai.poni1 / ai.pixel1)
            cx = float(ai.poni2 / ai.pixel2)
            if not (np.isfinite(cy) and np.isfinite(cx)):
                raise ValueError("center invalid")
        except Exception:
            cy = (data.shape[0] - 1) / 2.0
            cx = (data.shape[1] - 1) / 2.0

        return {
            "sample_path": sample_path,
            "ai": ai,
            "data": data,
            "valid_mask": valid_mask,
            "show_img": show_img,
            "cx": cx,
            "cy": cy,
        }

    def preview_iq_window_t2(self):
        try:
            ctx = self._get_t2_preview_context()
            if ctx is None:
                return

            use_sector = bool(self.t2_mode_sector.get())
            sector_specs = []
            chi_deg = None

            if use_sector:
                sector_specs = self.get_t2_sector_specs()
                chi_deg = self._compute_t2_chi_map_deg(ctx["ai"], ctx["data"].shape)
                iq_mask = np.zeros_like(ctx["valid_mask"], dtype=bool)
                for spec in sector_specs:
                    m, _, _, _ = self.build_sector_mask(chi_deg, spec["sec_min"], spec["sec_max"])
                    iq_mask |= m
                iq_mask = iq_mask & ctx["valid_mask"]
                sec_desc = "; ".join([f"S{s['index']}{s['label']}" for s in sector_specs[:6]])
                if len(sector_specs) > 6:
                    sec_desc += "; ..."
                mode_desc = self.tr("info_iq_sector").format(n=len(sector_specs), desc=sec_desc)
            else:
                iq_mask = np.asarray(ctx["valid_mask"], dtype=bool)
                mode_desc = self.tr("info_iq_full")

            if not np.any(iq_mask):
                raise ValueError("I-Q 预览区域为空，请检查扇区范围或 mask。")

            top = tk.Toplevel(self.root)
            top.title(self.tr("title_iq_preview").format(name=Path(ctx['sample_path']).name))
            info = ttk.Label(
                top,
                text=(
                    self.tr("info_iq_line1").format(name=Path(ctx['sample_path']).name, mode=mode_desc, pct=np.mean(iq_mask)*100) + "\n"
                    + self.tr("info_iq_line2")
                ),
                justify="left",
                style="Hint.TLabel",
            )
            info.pack(fill="x", padx=8, pady=(8, 4))

            fig = Figure(figsize=(7.2, 6.0), dpi=100)
            ax = fig.add_subplot(111)
            im = ax.imshow(ctx["show_img"], cmap="gray", origin="upper", interpolation="nearest")
            ov = np.ma.masked_where(~iq_mask, np.ones_like(ctx["show_img"]))
            ax.imshow(ov, cmap="autumn", origin="upper", interpolation="nearest", alpha=0.28, vmin=0.0, vmax=1.0)

            ax.plot(ctx["cx"], ctx["cy"], marker="+", color="cyan", ms=12, mew=2, label="Beam center")
            if use_sector:
                ray_len = float(max(ctx["data"].shape) * 0.75)
                palette = [
                    "#00d1ff", "#ff4d4d", "#3cb371", "#ff8c00", "#9370db",
                    "#ffd700", "#20b2aa", "#dc143c", "#1e90ff", "#8b4513",
                ]
                for i, spec in enumerate(sector_specs):
                    color = palette[i % len(palette)]
                    for j, ang_deg in enumerate([spec["sec_min"], spec["sec_max"]]):
                        ang = math.radians(float(ang_deg))
                        x2 = ctx["cx"] + math.cos(ang) * ray_len
                        y2 = ctx["cy"] + math.sin(ang) * ray_len
                        lbl = None
                        if j == 0 and i < 8:
                            lbl = f"S{spec['index']} {spec['label']}"
                        ax.plot(
                            [ctx["cx"], x2],
                            [ctx["cy"], y2],
                            color=color,
                            lw=1.5,
                            ls="-" if j == 0 else "--",
                            label=lbl,
                        )

            ax.set_title(self.tr("info_iq_title"))
            ax.set_xlabel("Pixel X")
            ax.set_ylabel("Pixel Y")
            ax.legend(loc="upper right", fontsize=8)

            cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            cb.set_label("Intensity (clipped)")

            canvas = FigureCanvasTkAgg(fig, master=top)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=6)
            canvas.draw()
            toolbar = NavigationToolbar2Tk(canvas, top)
            toolbar.update()

        except Exception as e:
            self.show_error("msg_iq_preview_error_title", f"{e}\n{traceback.format_exc()}")

    def preview_ichi_window_t2(self):
        try:
            ctx = self._get_t2_preview_context()
            if ctx is None:
                return

            qmin = float(self.t2_rad_qmin.get())
            qmax = float(self.t2_rad_qmax.get())
            if not (np.isfinite(qmin) and np.isfinite(qmax) and qmin < qmax):
                raise ValueError("I-chi 预览 q 范围无效：qmin 必须 < qmax。")

            q_map, q_src = self._compute_t2_q_map_a_inv(ctx["ai"], ctx["data"].shape)
            q_mask = np.isfinite(q_map) & (q_map >= qmin) & (q_map <= qmax) & ctx["valid_mask"]
            if not np.any(q_mask):
                raise ValueError("I-chi q 环带为空，请检查 q 范围、poni 或 mask。")

            top = tk.Toplevel(self.root)
            top.title(self.tr("title_ichi_preview").format(name=Path(ctx['sample_path']).name))
            info = ttk.Label(
                top,
                text=(
                    self.tr("info_ichi_line1").format(name=Path(ctx['sample_path']).name, qmin=qmin, qmax=qmax, pct=np.mean(q_mask)*100) + "\n"
                    + self.tr("info_ichi_line2").format(src=q_src)
                ),
                justify="left",
                style="Hint.TLabel",
            )
            info.pack(fill="x", padx=8, pady=(8, 4))

            fig = Figure(figsize=(7.2, 6.0), dpi=100)
            ax = fig.add_subplot(111)
            im = ax.imshow(ctx["show_img"], cmap="gray", origin="upper", interpolation="nearest")
            ov = np.ma.masked_where(~q_mask, np.ones_like(ctx["show_img"]))
            ax.imshow(ov, cmap="spring", origin="upper", interpolation="nearest", alpha=0.30, vmin=0.0, vmax=1.0)

            ax.plot(ctx["cx"], ctx["cy"], marker="+", color="cyan", ms=12, mew=2, label="Beam center")
            try:
                contours = ax.contour(
                    q_map,
                    levels=[qmin, qmax],
                    colors=["#00d1ff", "#ff4d4d"],
                    linewidths=1.2,
                )
                if contours is not None:
                    ax.clabel(contours, inline=True, fontsize=8, fmt=lambda v: f"{v:.3g} A^-1")
            except Exception:
                pass

            ax.set_title(self.tr("info_ichi_title"))
            ax.set_xlabel("Pixel X")
            ax.set_ylabel("Pixel Y")
            ax.legend(loc="upper right", fontsize=8)

            cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            cb.set_label("Intensity (clipped)")

            canvas = FigureCanvasTkAgg(fig, master=top)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=6)
            canvas.draw()
            toolbar = NavigationToolbar2Tk(canvas, top)
            toolbar.update()

        except Exception as e:
            self.show_error("msg_ichi_preview_error_title", f"{e}\n{traceback.format_exc()}")

    def preview_sector_window_t2(self):
        # 兼容旧按钮/旧调用入口：转到 I-Q 预览
        self.preview_iq_window_t2()

    def open_mu_tool(self):
        top = tk.Toplevel(self.root)
        top.title(self.tr("title_mu_tool"))
        top.geometry("520x480")

        # --- Energy / wavelength ---
        frm_energy = ttk.LabelFrame(top, text=self.tr("lbl_mu_energy"))
        frm_energy.pack(fill="x", padx=8, pady=4)

        energy_var = tk.DoubleVar(value=30.0)
        wl_var = tk.DoubleVar(value=round(HC_KEV_A / 30.0, 4))

        def _sync_wl(*_a):
            try:
                e = energy_var.get()
                if e > 0:
                    wl_var.set(round(HC_KEV_A / e, 4))
            except Exception:
                pass

        def _sync_energy(*_a):
            try:
                w = wl_var.get()
                if w > 0:
                    energy_var.set(round(HC_KEV_A / w, 4))
            except Exception:
                pass

        row_e = ttk.Frame(frm_energy); row_e.pack(fill="x", pady=2)
        ttk.Label(row_e, text="E (keV):").pack(side="left", padx=4)
        e_energy = ttk.Entry(row_e, textvariable=energy_var, width=10)
        e_energy.pack(side="left")
        e_energy.bind("<FocusOut>", _sync_wl)
        ttk.Label(row_e, text=self.tr("lbl_mu_energy_or_wl")).pack(side="left", padx=(12, 4))
        e_wl = ttk.Entry(row_e, textvariable=wl_var, width=10)
        e_wl.pack(side="left")
        e_wl.bind("<FocusOut>", _sync_energy)

        # Try to auto-fill from PONI wavelength
        try:
            poni_path = self.global_vars["poni_path"].get()
            if poni_path:
                ai = pyFAI.load(poni_path)
                wl_m = ai.wavelength  # metres
                wl_A = wl_m * 1e10
                e_keV = HC_KEV_A / wl_A
                energy_var.set(round(e_keV, 4))
                wl_var.set(round(wl_A, 4))
        except Exception:
            pass

        # --- Material preset ---
        frm_mat = ttk.LabelFrame(top, text=self.tr("lbl_mu_preset"))
        frm_mat.pack(fill="x", padx=8, pady=4)

        preset_keys = list(MATERIAL_PRESETS.keys()) if MATERIAL_PRESETS else []
        preset_names = [MATERIAL_PRESETS[k][0] for k in preset_keys] if MATERIAL_PRESETS else []
        preset_var = tk.StringVar(value=preset_names[0] if preset_names else "")
        cb_preset = ttk.Combobox(frm_mat, values=preset_names, textvariable=preset_var, width=30, state="readonly")
        cb_preset.pack(side="left", padx=4, pady=4)
        if preset_names:
            cb_preset.current(0)

        # --- Density ---
        rho_var = tk.DoubleVar(value=4.43)
        row_rho = ttk.Frame(frm_mat); row_rho.pack(fill="x", pady=2)
        ttk.Label(row_rho, text=self.tr("lbl_mu_density")).pack(side="left", padx=4)
        e_rho = ttk.Entry(row_rho, textvariable=rho_var, width=8)
        e_rho.pack(side="left")

        # --- Custom composition ---
        frm_comp = ttk.LabelFrame(top, text=self.tr("lbl_mu_custom_comp"))
        frm_comp.pack(fill="x", padx=8, pady=4)

        comp_var = tk.StringVar(value="")
        ttk.Label(frm_comp, text="e.g. Fe:0.69, Cr:0.19, Ni:0.10").pack(anchor="w", padx=4)
        e_comp = ttk.Entry(frm_comp, textvariable=comp_var, width=50)
        e_comp.pack(fill="x", padx=4, pady=2)

        def _fill_from_preset(*_a):
            sel = preset_var.get()
            for k in preset_keys:
                if MATERIAL_PRESETS[k][0] == sel:
                    comp_dict = MATERIAL_PRESETS[k][1]
                    rho_var.set(MATERIAL_PRESETS[k][2])
                    comp_var.set(", ".join(f"{el}:{w}" for el, w in comp_dict.items()))
                    break
        cb_preset.bind("<<ComboboxSelected>>", _fill_from_preset)
        _fill_from_preset()  # initialize

        # --- Result display ---
        frm_res = ttk.LabelFrame(top, text=self.tr("lbl_mu_contrib"))
        frm_res.pack(fill="both", expand=True, padx=8, pady=4)

        result_text = tk.Text(frm_res, height=8, width=55, state="disabled", font=("Consolas", 9))
        result_text.pack(fill="both", expand=True, padx=4, pady=4)
        self._register_native_widget(result_text)

        def do_calc():
            try:
                e_keV = energy_var.get()
                rho = rho_var.get()
                comp_str = comp_var.get().strip()
                if not comp_str:
                    raise ValueError("请输入成分或选择预设材料。")
                if calculate_mu is None:
                    raise ImportError("xraydb 未安装，无法计算。")

                comp = parse_composition_string(comp_str)
                res = calculate_mu(comp, rho, e_keV)

                result_text.config(state="normal")
                result_text.delete("1.0", "end")
                result_text.insert("end", f"Energy: {e_keV:.2f} keV  |  ρ = {rho:.3f} g/cm³\n")
                result_text.insert("end", f"μ/ρ(mix) = {res.mu_rho_cm2_g:.4f} cm²/g\n")
                result_text.insert("end", f"μ_linear = {res.mu_linear_cm_inv:.4f} cm⁻¹\n")
                result_text.insert("end", "-" * 40 + "\n")
                result_text.insert("end", f"{'Element':<8} {'wt-frac':<10} {'μ/ρ':<12} {'Contrib.':<12}\n")
                for el, contrib in res.element_contributions.items():
                    wf = res.composition.get(el, 0)
                    murho_i = contrib / wf if wf > 0 else 0
                    result_text.insert("end", f"{el:<8} {wf:<10.4f} {murho_i:<12.4f} {contrib:<12.4f}\n")
                result_text.config(state="disabled")

                self.t2_mu.set(round(res.mu_linear_cm_inv, 2))
            except Exception as exc:
                self.show_error("msg_input_error_title", self.tr("msg_mu_fail").format(e=exc))

        ttk.Button(top, text=self.tr("btn_mu_apply"), command=do_calc).pack(pady=8)

    def add_file_row(self, p, l, v, pat, cmd=None):
        f = ttk.Frame(p); f.pack(fill="x", pady=3)
        lbl = ttk.Label(f, text=l, width=16, anchor="e")
        lbl.pack(side="left", padx=(0, 6))
        ent = ttk.Entry(f, textvariable=v)
        ent.pack(side="left", fill="x", expand=True, padx=(0, 4))
        def b():
            fp = filedialog.askopenfilename(filetypes=[("File", pat)])
            if fp: v.set(fp); cmd(fp) if cmd else None
        btn = ttk.Button(f, text="...", width=3, command=b)
        btn.pack(side="left")
        return {"frame": f, "label": lbl, "entry": ent, "button": btn}

    def add_dir_row(self, p, l, v):
        f = ttk.Frame(p); f.pack(fill="x", pady=3)
        lbl = ttk.Label(f, text=l, width=16, anchor="e")
        lbl.pack(side="left", padx=(0, 6))
        ent = ttk.Entry(f, textvariable=v)
        ent.pack(side="left", fill="x", expand=True, padx=(0, 4))
        def b():
            dp = filedialog.askdirectory()
            if dp:
                v.set(dp)
        btn = ttk.Button(f, text="...", width=3, command=b)
        btn.pack(side="left")
        return {"frame": f, "label": lbl, "entry": ent, "button": btn}

    def add_grid_entry(self, p, v, r, c):
        e = ttk.Entry(p, textvariable=v, width=8, justify="center")
        e.grid(row=r, column=c, padx=3, pady=3)
        return e

    def _on_std_type_changed(self, event=None):
        """Show/hide water temp and ref-curve rows based on standard selection."""
        sel_text = self.t1_std_combo.get()
        key = self._t1_std_option_map.get(sel_text, "SRM3600")
        self.t1_std_type.set(key)

        # Hide both conditional rows first
        self.t1_water_row.pack_forget()
        self.t1_ref_row["frame"].pack_forget()

        if key == "Water_20C":
            # Show water temperature entry, hide standard file row
            self.t1_water_row.pack(fill="x", pady=1, before=self.t1_ref_row["frame"])
        elif key in ("Lupolen", "Custom"):
            # Show reference curve file row
            self.t1_ref_row["frame"].pack(fill="x", pady=1)

    def _get_std_reference_data(self):
        """Return (q_ref, i_ref) based on the current standard selection.

        For SRM3600: built-in 15-point curve.
        For Water: flat curve at user-specified temperature.
        For Lupolen/Custom: load from user-supplied file.
        """
        key = self.t1_std_type.get()

        if get_reference_data is not None:
            if key in ("Lupolen", "Custom"):
                ref_path = self.t1_std_ref_path.get()
                if not ref_path:
                    raise ValueError("请选择标准参考曲线文件。")
                from saxsabs.io.parsers import read_external_1d_profile
                prof = read_external_1d_profile(ref_path)
                q_user = prof["x"]
                i_user = prof["i_rel"]
                return get_reference_data(key, q_user=q_user, i_user=i_user)
            elif key == "Water_20C":
                temp_c = self.t1_water_temp.get()
                return get_reference_data(key, temperature_C=temp_c)
            else:
                return get_reference_data(key)
        else:
            # Fallback: only SRM3600 available
            return NIST_SRM3600_DATA[:, 0], NIST_SRM3600_DATA[:, 1]

    def on_load_std_t1(self, fp):
        e, m, t = self.parse_header(fp)
        if e is not None: self.t1_params["std_exp"].set(e)
        if m is not None: self.t1_params["std_i0"].set(m)
        if t is not None: self.t1_params["std_t"].set(t)
    def on_load_bg_t1(self, fp):
        e, m, t = self.parse_header(fp)
        if e is not None: self.t1_params["bg_exp"].set(e)
        if m is not None: self.t1_params["bg_i0"].set(m)
        if t is not None: self.t1_params["bg_t"].set(t)

    def select_multi_bg_t1(self):
        fs = filedialog.askopenfilenames(filetypes=[("Image", "*.tif *.tiff *.edf *.cbf")])
        if not fs:
            return
        self.global_vars["bg_path"].set(";".join(fs))
        self.on_load_bg_t1(fs[0])

    def add_batch_files(self):
        fs = filedialog.askopenfilenames(filetypes=[("TIFF", "*.tif *.tiff")])
        for f in fs:
            if f not in self.t2_files:
                self.t2_files.append(f)
                self.lb_batch.insert(tk.END, Path(f).name)
        self.refresh_queue_status()
    def clear_batch_files(self):
        self.t2_files = []; self.lb_batch.delete(0, tk.END)
        self.refresh_queue_status()

    def apply_session(self, session_path: str):
        try:
            sess = load_session(session_path)
        except Exception as e:
            self.show_error("session_error_title", self.tr("session_error_body").format(err=e))
            return

        notes = []
        geom = session_geometry(sess)
        if geom:
            px_mm = geom.get("px_mm")
            wl_a = geom.get("wl_A")
            dist_mm = geom.get("dist_mm")
            self.session_geometry_fallback = {
                "wavelength_a": float(wl_a) if wl_a is not None else None,
                "distance_m": (float(dist_mm) / 1000.0) if dist_mm is not None else None,
                "pixel1_m": (float(px_mm) / 1000.0) if px_mm is not None else None,
                "pixel2_m": (float(px_mm) / 1000.0) if px_mm is not None else None,
                "energy_kev": (HC_KEV_A / float(wl_a)) if (wl_a is not None and float(wl_a) > 0) else None,
            }
            notes.append("Session geometry loaded (used as consistency fallback when headers are missing).")

        # Optional calibration paths from session payload (forward-compatible)
        cal = sess.get("calibration", {}) if isinstance(sess.get("calibration", {}), dict) else {}
        candidate_paths = {
            "poni": str(cal.get("poni_path", sess.get("poni_path", ""))).strip(),
            "bg": str(cal.get("bg_path", sess.get("bg_path", ""))).strip(),
            "dark": str(cal.get("dark_path", sess.get("dark_path", ""))).strip(),
            "std": str(cal.get("std_path", sess.get("std_path", ""))).strip(),
        }
        if candidate_paths["poni"] and Path(candidate_paths["poni"]).is_file():
            self.global_vars["poni_path"].set(candidate_paths["poni"])
            notes.append(f"PONI loaded from session: {Path(candidate_paths['poni']).name}")
        if candidate_paths["bg"] and Path(candidate_paths["bg"]).is_file():
            self.global_vars["bg_path"].set(candidate_paths["bg"])
            notes.append(f"Background loaded from session: {Path(candidate_paths['bg']).name}")
        if candidate_paths["dark"] and Path(candidate_paths["dark"]).is_file():
            self.global_vars["dark_path"].set(candidate_paths["dark"])
            notes.append(f"Dark loaded from session: {Path(candidate_paths['dark']).name}")
        if candidate_paths["std"] and Path(candidate_paths["std"]).is_file():
            self.t1_files["std"].set(candidate_paths["std"])
            self.on_load_std_t1(candidate_paths["std"])
            notes.append(f"Std image loaded from session std_path: {Path(candidate_paths['std']).name}")

        data_path = str(sess.get("data_path", "")).strip()
        if data_path:
            p = Path(data_path)
            if p.is_file() and p.suffix.lower() in (".tif", ".tiff"):
                self.t1_files["std"].set(str(p))
                self.on_load_std_t1(str(p))
                notes.append(f"Std image loaded from session: {p.name}")
            elif p.is_file():
                notes.append(f"Session data is not TIFF, skipped for Std: {p.name}")
            else:
                notes.append(f"Session data path not found: {data_path}")

        if not notes:
            notes.append("Session loaded.")
        self.show_info("session_loaded_title", "\n".join(notes))


BL19B2_RobustApp = SAXSAbsWorkbenchApp


def main(argv=None):
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--session", type=str, default="", help="Path to session json")
    parser.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default="en", help="UI language")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    args = parser.parse_args(argv)

    root = tk.Tk()
    app = SAXSAbsWorkbenchApp(root, language=args.lang)
    if args.session:
        root.after(80, lambda: app.apply_session(args.session))
    root.mainloop()

if __name__ == "__main__":
    main()
