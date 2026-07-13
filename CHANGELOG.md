# Changelog

## [Unreleased]

## [2.0.0] - 2026-07-13

### Added
- Explicit `bl19b2-abs2d-v1-legacy` migration command with acknowledgement flags for historical assumptions.
- Calibration-record schema v2 binds and verifies portable standard, background, dark, reference, operator, integration, and robust-estimator sources used to derive K.
- **Same-机时 (beamtime) automatic grouping** — new core `cluster_by_acquisition_time` + `AcquisitionGroup` in `saxsabs.core.session_grouper`. Tab2 now has a "检测机时分组 / Detect Groups" button that clusters files by timestamp (header preferred, mtime fallback) with a 90-minute default gap. Groups are exposed to the batch report path and can drive future per-run output subdirectories and smarter auto BG/Dark matching.
- **Core extraction & deduplication** — `reference_matching` (build/score/select best BG/Dark) and improved header timestamp extraction now live in `src/saxsabs/core` and `io/parsers`. The GUI delegates to them when available, reducing ~150 LOC of duplicated logic.
- New public re-exports: `evaluate_preflight_gate`, `RunPolicy`, `build_reference_library`, `AcquisitionGroup`, `cluster_by_acquisition_time`, `extract_acquisition_timestamp`, etc.
- Two new test modules: `test_session_grouper.py` and `test_reference_matching.py`.

### Changed
- Promoted the BL19B2 workflow to an explicit safety-first CLI contract. Historical v1 assumptions require the dedicated legacy migration command and explicit acknowledgement.
- Schema v1 calibration records remain readable but are provenance-incomplete and cannot authorize formal Tab 2/Tab 3 output.
- Combined uncertainty remains explicitly partial while shared calibration-background raw-count and dark covariance are unquantified.
- Ambiguous attenuation-composition scales are rejected; normalized fractions and complete percentages remain supported.
- Tooltip system hardened (smarter screen-edge positioning, slightly better dark-mode contrast, safer error handling).
- `parse_header` and `compute_norm_factor` in the Workbench now prefer the canonical core implementations (with legacy fallback for safety).

### Fixed
- Preserved public positional-call compatibility for calibration and buffer-subtraction APIs.
- Made generated rerun commands preserve all scientific and execution options.
- Hardened calibrated-2D and PONI resume checks against incomplete, corrupt, stale, or context-incompatible output packages; multi-file publication is transactional.
- Bound BL19B2 output metadata to stable source snapshots and made schema-v4 K/QC contracts fail closed on missing or invalid fields.
- Prevented untrusted K factors, operator-incompatible external profiles, cross-axis subtraction, and mislabeled Q/2theta/chi units from entering formal Tab 3 output.
- Made Tab 2 dry-run reuse the formal calibration gate, fixed auto-reference independence from fixed paths, and made K-history updates atomic and no-clobber on damaged history.
- Added safe Cal2D rerun package IDs, bounded batch workers and output stems, and removed current-working-directory launcher shadowing.
- Separated reference-certificate coverage from the final system uncertainty coverage contract.
- Minor robustness improvements in header timestamp parsing for grouping use-case.

### Release archive note
- `submission/softwarex/` is retained as the historical 1.1.1 submission snapshot; it is not the authoritative 2.0.0 runtime metadata.

## [1.1.1] - 2026-04-22

### Fixed
- **1D profile column inference** (HIGH): the parser no longer misidentifies metadata columns such as `index` or `id` as the scattering axis or intensity column when `q` / `intensity` are present.
- **Buffer subtraction validity checks** (HIGH): non-positive `alpha` now raises an explicit error, and interpolation now rejects sample grids that extend outside the buffer q-range instead of silently extrapolating endpoint values.
- **Export shape validation** (HIGH): canSAS / NXcanSAS writers now reject mismatched q/intensity/error array lengths before writing malformed files; the NXcanSAS reader also reports dataset-length mismatches explicitly.
- **Transmission parsing consistency** (MEDIUM): header parsing now rejects non-physical transmission values (`T <= 0` or `T > 1`) so parsing and normalization follow the same acceptance rules.
- **Release metadata sync** (MEDIUM): package version, launcher version, citation metadata, and submission metadata are now aligned for the new patch release.

### Added
- 7 regression tests covering parser column selection, invalid transmission handling, negative buffer scaling, q-range overreach during interpolation, and malformed export inputs; total automated tests now 66.
- GitHub Release automation: pushing a `v*` tag now builds wheel / sdist artifacts and publishes them to the corresponding GitHub Release.

## [1.1.0] - 2026-02-26

### Added
- **Preflight gate** (`evaluate_preflight_gate`): automated pre-batch risk scoring (READY / CAUTION / BLOCKED) to catch missing headers, invalid parameters, or unreliable thickness before processing starts.
- **Execution policy** (`RunPolicy`, `parse_run_policy`, `should_skip_all_existing`): unified resume / overwrite / skip semantics for Tab 2 and Tab 3 batch processing.
- **Semantic status bar**: error (red), success (green), warning (amber) colour indicators with automatic keyword detection.
- **Report text highlighting**: error / success / warning lines in the analysis report pane are now colour-coded via `tk.Text` tags.
- Tab labels with icon prefixes (📐 📦 📈 ❓) for quick visual navigation.
- `logging` module integrated in the main GUI for diagnostic messages (e.g. T > 1 warnings).
- 9 new tests (`test_preflight.py`, `test_execution_policy.py`, updated `test_normalization.py`); total now 59.

### Fixed
- **Dark-current error propagation sign** (HIGH): corrected the partial derivative coefficient from `(1/Ns + 1/Nb)²` to `(1/Nb − 1/Ns)²` in the Tab 3 raw workflow.
- **Transmission T > 1 rejection** (MEDIUM): `compute_norm_factor` now explicitly rejects T > 1.0 with a `logger.warning` instead of silently returning NaN.
- **Water standard K uncertainty** (MEDIUM): point-wise ratio dispersion is now computed using the same MAD-based robust estimator as the glassy carbon path; previously hardcoded to `k_std = 0`.
- **canSAS / NXcanSAS export guard** (HIGH): export is blocked when the x-axis is χ (azimuthal angle), preventing silent unit mismatch.
- **Raw + buffer combination block** (HIGH): raw pipeline mode + buffer subtraction now raises an explicit error to prevent unit-scale mismatch.
- **Buffer subtraction fallback error propagation** (MEDIUM): the no-library fallback path now correctly propagates buffer uncertainty (σ² = σ_s² + α² σ_b²).
- **Duplicate x-point error merging** (MEDIUM): fixed from arithmetic averaging (Σσᵢ / N) to proper quadrature (√Σσᵢ² / N) in `_regularize_xy_triplet`.

### Changed
- Primary action buttons simplified from `>>> Run ... <<<` to clean `▶  Run ...` labels.
- Hardcoded `font=("Arial", 8)` replaced with global `Hint.TLabel` style.
- Hardcoded `foreground="gray"` replaced with theme-aware `Hint.TLabel` style for dark-mode compatibility.
- Removed unused `scipy` import.

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
- JOSS paper PDF build validation added to CI.
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
