<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="saxsabs: SAXS absolute intensity calibration workbench.">
</p>

# saxsabs

[![CI](https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/actions/workflows/ci.yml/badge.svg)](https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19687104.svg)](https://doi.org/10.5281/zenodo.19687104)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](LICENSE)

**SAXS absolute intensity calibration** · desktop app **SAXSAbs Workbench** · DOI https://doi.org/10.5281/zenodo.19687104

<p align="center">
  <img src="paper/fig_workflow.png" width="92%" alt="SAXSAbs workflow figure.">
</p>

<p align="center">
  <img src="paper/fig_gui.png" width="46%" alt="SAXSAbs Workbench GUI.">
  &nbsp;
  <img src="paper/fig_kfactor_demo.png" width="46%" alt="K-factor calibration demo.">
</p>

<p align="center">
  <img src="assets/readme/section-01-workbench.svg" width="100%" alt="01 Workbench: K-factor, batch 2D, external 1D.">
</p>

| Tab | Input | Role |
|-----|-------|------|
| 1 K-Factor | **2D** | Calibrate K (GC / water) |
| 2 Batch | **2D** | 2D → absolute 1D (pyFAI integrate + absolute scale) |
| 3 External 1D | **1D** | Absolute scaling only when contracts met |
| 4 Help | — | Guide |

**Rule:** raw 2D → Tab 1+2 · only integrated 1D → Tab 3 when provenance OK.

Also: multi-standard registry · robust K (median/MAD) · traceable μ · buffer subtraction · preflight READY/CAUTION/BLOCKED · canSAS / NXcanSAS · bilingual GUI.

<p align="center">
  <img src="assets/readme/section-02-gates.svg" width="100%" alt="02 Gates: fail-closed formal output.">
</p>

Formal output is **fail-closed**: verified calibration records, unit-checked axes, fixed-thickness Tab 2 path, read-only K/μ from records, Dry Check fingerprints. Workbench is not yet a full substitute for the strict BL19B2 campaign runner — see `docs/`.

```bash
pytest -q
# examples/minimal_2d/ · examples/manual-verification.md
```

Cite: https://doi.org/10.5281/zenodo.19687104 · BSD-3-Clause
