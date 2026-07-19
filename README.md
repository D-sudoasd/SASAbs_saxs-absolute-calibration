<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="saxsabs / SAXSAbs Workbench: SAXS absolute intensity calibration with K-factor, batch processing, and provenance gates.">
</p>

# saxsabs

[![CI](https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/actions/workflows/ci.yml/badge.svg)](https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19687104.svg)](https://doi.org/10.5281/zenodo.19687104)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

**SAXS absolute intensity calibration** and robust external 1D profile parsing.

Standalone desktop app: **SAXSAbs Workbench** · Archived DOI: https://doi.org/10.5281/zenodo.19687104

## Proof

<p align="center">
  <img src="paper/fig_workflow.png" width="90%" alt="SAXSAbs workflow overview figure."><br>
  <img src="paper/fig_gui.png" width="45%" alt="SAXSAbs Workbench GUI.">
  &nbsp;
  <img src="paper/fig_kfactor_demo.png" width="45%" alt="K-factor calibration demo figure.">
</p>

## What it provides

- **Multi-standard calibration** — NIST SRM 3600 glassy carbon, liquid water (T-dependent dΣ/dΩ), user standards  
- **Robust K-factor** — median / MAD outlier filtering  
- **Traceable μ models** — bundled NIST 30 keV composition snapshot (BL19B2 workflow) + diagnostic Elam/xraydb calculator  
- **Buffer / solvent subtraction** — α-scaling with error propagation for BioSAXS  
- **Preflight gate** — READY / CAUTION / BLOCKED before batch runs  
- **Execution policy** — resume / overwrite / skip for interrupted jobs  
- **Exports** — TSV, CSV, canSAS 1D XML, NXcanSAS HDF5  
- **Monitor-mode-aware normalization** (`rate` vs `integrated`)  
- **Headless CLI** + bilingual GUI (中文 / English, light/dark)

## Workbench tabs

| Tab | Name | Input | Role |
|-----|------|-------|------|
| 1 | K-Factor Calibration | **2D images** | Calibrate K from GC or water standards |
| 2 | Batch Processing | **2D images** | 2D → absolute 1D (dark/BG + pyFAI azimuthal integrate + absolute scale) |
| 3 | External 1D → Absolute | **Already integrated 1D** | Apply absolute scaling only |
| 4 | Help | — | Usage guide |

**Rule of thumb**

- Have raw **2D** detector images → **Tab 1 + Tab 2**  
- Only external **1D** curves → **Tab 3** when provenance/ledger contracts are met; otherwise inspect-only  

```text
2D images? ──yes──► need K? ──yes──► Tab 1 ──► Tab 2
                 └──no───────────────► Tab 2
           └──no (1D only)───────────► Tab 3 (if contracts OK)
```

## Version 2.0 safety boundaries (summary)

Formal output is **fail-closed** when provenance is incomplete. Highlights:

- Tab 2/3 formal output needs a **source-verified calibration record**; legacy/incomplete/manual K and incompatible external 1D profiles are inspection-only.  
- Q / 2θ / chi axes are unit-checked; named-axis conflicts and cross-axis subtraction fail closed; `q_nm^-1` converts explicitly to `Å^-1`.  
- Tab 2 formal path: **fixed thickness only**; K and μ fields are read-only from verified records / calculators; Dry Check approval is required and invalidated on tracked mutations.  
- Tab 3: formal K and K/d require explicit machine-readable `relative` state and correction ledger; buffer subtraction requires absolute input + matching `CalibrationContext` fingerprint.  
- Workbench is **not** yet an exact front end to the strict BL19B2 campaign runner; campaign atomicity and some covariance terms remain documented open boundaries.

Full detail: earlier release notes and `docs/` (including scientific safety audits when present in the tree).

## Install & verify

```bash
pip install -e ".[dev]"   # or project-documented install path
pytest -q
```

Minimal 2D reproducibility package: `examples/minimal_2d/`.  
Manual checklist: `examples/manual-verification.md`.

## Documentation

- `docs/architecture.md` · `docs/reviewer-faq.md` · `CONTRIBUTING.md` · `CODE_OF_CONDUCT.md`  
- `CITATION.cff` · `CHANGELOG.md`  
- JOSS draft: `paper/paper.md`, `paper/paper.bib`

## Citation

https://doi.org/10.5281/zenodo.19687104

## License

BSD-3-Clause — see [LICENSE](LICENSE).
