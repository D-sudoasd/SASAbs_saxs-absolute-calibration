# Changelog

## [1.0.0] - 2026-02-26

### Added
- **Multi-standard calibration registry**: pluggable `STANDARD_REGISTRY` ships with NIST SRM 3600 glassy carbon and liquid water (temperature-dependent dΣ/dΩ model). Users can register custom reference datasets.
- **Universal μ calculator**: computes linear attenuation coefficients from arbitrary chemical compositions and photon energies using the XCOM database via xraydb. Includes preset alloy/compound library and interactive GUI dialog.
- **Buffer / solvent subtraction**: α-scaling subtraction with full error propagation for BioSAXS workflows. Available in both GUI (Tab 3) and core API.
- **canSAS 1D XML output**: standards-compliant XML export following the canSAS 1D/1.1 schema.
- **NXcanSAS HDF5 output**: NeXus-compliant HDF5 export following the NXcanSAS application definition.
- **GUI modernisation (Sun Valley theme)**: sv_ttk-based Windows 11 appearance with light / dark mode toggle, unified Segoe UI typography hierarchy, accent-styled primary action buttons, scrollable Tab 2 / Tab 3, and a bottom status bar.
- Python 3.13 added to CI test matrix (3 OS × 4 Python versions = 12 jobs).
- 50 automated tests (up from 15) covering calibration, normalization, parsing, I/O formats, μ calculator, and buffer subtraction.

### Changed
- Version bumped to 1.0.0 (production-ready).
- `paper/paper.md` substantially rewritten: expanded Summary, Statement of Need, State of the Field (13-row comparison table), Software Design (new modules), Mathematical Formulation (μ and buffer subtraction equations), and Research Impact (interoperability dimension). Added author ORCID.
- `paper/paper.bib`: added `orthaber2000` (water standard) and `newville_xraydb` (xraydb) citations; added DOI to `srm3600`; fixed `glatter_kratky` from `@article` to `@book`; removed unused `dawn` entry.
- Development Status classifier upgraded to `5 - Production/Stable`.
- `sv-ttk` moved from core dependencies to `[gui]` optional group.
- `pyproject.toml` optional dependency groups restructured: `[gui]`, `[io]`, `[hdf5]`, `[dev]`.

### Removed
- Legacy script `02_绝对强度校正.py` (functionality fully superseded by SASAbs.py).
- Stale test output files (`test_output*.txt`, `test_results*.txt`).
- `paper/saxsabs_joss_paper.docx` (unnecessary Word duplicate).
- Unused `dawn` BibTeX entry from `paper.bib`.

## [0.2.0] - 2026-02-26

### Added
- Full bilingual (中文 / English) internationalisation across all GUI tabs, dialogs, and messages.
- Multi-background capillary subtraction support in the GUI.
- `__version__` attribute in the `saxsabs` package for programmatic version access.
- `__main__.py` entry point — `python -m saxsabs` now works.
- `--version` flag for the `saxsabs` CLI.
- Comprehensive Google-style docstrings for all core and I/O modules.
- CI matrix expanded to Python 3.10/3.11/3.12 on Ubuntu/Windows/macOS.
- JOSS paper PDF build validation via `openjournals/paperdraft` in CI.
- `codemeta.json` for software metadata interoperability.
- `[project.urls]` in `pyproject.toml` with Homepage, Repository, Issues, Changelog links.
- README badges (CI status, license).
- Expanded synthetic example data (36-point profile replaces 3-point placeholder).

### Changed
- Unified version across all metadata files to `0.2.0`.
- Replaced placeholder author ("BL19B2 Team") with real author info in pyproject.toml, CITATION.cff, and paper.md.
- Replaced placeholder repository URL in CITATION.cff with real GitHub URL.
- Upgraded `paper.bib` with full DOI-bearing citations for pyFAI, SasView, Dioptas, and added irena, DAWN, BioXTAS RAW, SRM 3600, Glatter & Kratky references.
- Strengthened State of the field section with concrete tool comparison table.
- Enriched Research impact statement with real deployment context.
- Expanded AI usage disclosure per JOSS 2025 policy.

### Removed
- Stale `src/saxsabs.egg-info/` build cache (was incorrectly tracked; now only in `.gitignore`).
- Self-referencing placeholder `@article{joss}` entry from `paper.bib`.

## [0.1.0] - 2026-02-25

- Initialized installable package structure under `src/saxsabs`.
- Extracted normalization and parser logic from legacy GUI script.
- Added robust K-factor estimation core API.
- Added CLI for normalization, parsing, and headless K estimation.
- Added pytest test suite and GitHub Actions CI workflow.
- Added JOSS paper skeleton and manual verification template.
