# saxsabs

[![CI](https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/actions/workflows/ci.yml/badge.svg)](https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/actions/workflows/ci.yml)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

SAXS absolute intensity calibration and robust external 1D profile parsing utilities.

Standalone desktop app name: **SAXSAbs Workbench**.

## Overview

`saxsabs` is an open-source Python package for reproducible small-angle X-ray
scattering (SAXS) absolute-intensity calibration workflows. It provides:

- **Multi-standard calibration** — pluggable registry with NIST SRM 3600 glassy
  carbon, liquid water (temperature-dependent dΣ/dΩ), and user-supplied
  reference data
- **Robust K-factor estimation** against any registered standard using
  median / MAD outlier filtering
- **Universal μ calculator** — linear attenuation coefficients from arbitrary
  chemical compositions and photon energies (XCOM via xraydb)
- **Buffer / solvent subtraction** — α-scaling with full error propagation for
  BioSAXS workflows
- **Preflight gate** — automated pre-batch risk scoring (READY / CAUTION / BLOCKED)
  to catch missing headers, invalid transmission, or unreliable thickness before
  processing starts
- **Execution policy** — resume / overwrite / skip semantics for batch processing
  to safely restart interrupted jobs
- **Multi-format output** — TSV, CSV, canSAS 1D XML, NXcanSAS HDF5
- **Monitor-mode-aware normalization** (`rate` vs. `integrated`) with explicit
  formulae
- **Robust header parsing** for heterogeneous instrument metadata
- **Format-agnostic 1D profile ingestion** (CSV, space-delimited,
  semicolon-delimited)
- **Headless CLI** for batch processing and CI-driven validation
- **Bilingual GUI** (中文 / English) with Sun Valley (Win 11) theme and
  light / dark mode toggle

## Highlights of recent improvements

### Scientific accuracy

- **Transmission validation** — T > 1 is now rejected with an explicit warning
  (physically impossible for standard absorption)
- **Dark-current error propagation** — corrected the partial derivative sign in
  the `(S−D)/Ns − (BG−D)/Nb` formula to use `(1/Nb − 1/Ns)` instead of
  `(1/Ns + 1/Nb)`
- **Water standard K uncertainty** — replaced hardcoded `k_std = 0` with the
  same MAD-based robust dispersion used for the glassy carbon path
- **canSAS / NXcanSAS export guard** — blocks export when the x-axis is not
  momentum-transfer Q (e.g. chi-angle data), preventing silent unit mismatch
- **Buffer subtraction fallback** — the no-library fallback path now correctly
  propagates buffer uncertainty: σ² = σ\_s² + α² σ\_b²
- **Duplicate x-point error merging** — fixed from arithmetic averaging
  (Σσᵢ / N) to proper quadrature (√Σσᵢ² / N)

### GUI polish

- Tab labels carry icon prefixes (📐 📦 📈 ❓) for quick visual navigation
- Primary action buttons simplified from `>>> Run ... <<<` to clean
  `▶  Run ...` labels styled via the Accent theme
- **Semantic status bar** — error → red, success → green, warning → amber,
  with automatic keyword detection
- **Report text highlighting** — error / success / warning lines are
  colour-coded in the analysis report pane
- Font consistency fix (replaced stray Arial with the global Segoe UI style)
- Dark-mode foreground fix for the BG path label

## Installation

Core library (CLI + API):

```bash
pip install -e .
```

With GUI dependencies:

```bash
pip install -e .[gui]
```

With all optional I/O formats:

```bash
pip install -e .[gui,hdf5]
```

Developer tools:

```bash
pip install -e .[dev]
```

## Launch as standalone desktop program (Windows)

Double-click one of the following files in repository root:

- `Start_SAXSAbs_Workbench.bat`
- `saxsabs_workbench.pyw`

Or run:

```bash
python saxsabs_workbench.py
```

Language selection:

```bash
python saxsabs_workbench.py --lang en
python saxsabs_workbench.py --lang zh
```

Installed launcher command:

```bash
saxsabs-workbench --version
saxsabs-workbench --lang zh
```

Note: `saxsabs-workbench` expects `SASAbs.py` to be available in the current
repository workspace.

## Quick CLI examples

Compute normalization factor:

```bash
saxsabs norm-factor --mode rate --exp 1.0 --mon 100000 --trans 0.8
```

Parse header values from JSON:

```bash
saxsabs parse-header --header-json examples/header_example.json
```

Parse external 1D profile:

```bash
saxsabs parse-external1d --input examples/profile_example.csv
```

Estimate robust K-factor from measured/reference curves:

```bash
saxsabs estimate-k --meas examples/k_measured.csv --ref examples/k_reference.csv --qmin 0.01 --qmax 0.2
```

## Public API

### Calibration & normalization

- `saxsabs.compute_norm_factor` — monitor normalization factor
- `saxsabs.estimate_k_factor_robust` — robust K-factor with MAD filtering
- `saxsabs.STANDARD_REGISTRY` — pluggable standard-reference registry
- `saxsabs.get_reference_data` — retrieve reference data by name
- `saxsabs.water_dsdw` — temperature-dependent water dΣ/dΩ

### μ calculator

- `saxsabs.calculate_mu` — linear attenuation coefficient from composition
- `saxsabs.mu_rho_single` — mass attenuation coefficient for a single element
- `saxsabs.parse_composition_string` — parse `"Fe:0.9,Cr:0.1"` notation

### Buffer subtraction

- `saxsabs.subtract_buffer` — α-scaling subtraction with error propagation

### Batch workflow helpers

- `saxsabs.evaluate_preflight_gate` — pre-batch risk scoring (READY / CAUTION / BLOCKED)
- `saxsabs.PreflightGateSummary` — result container for preflight evaluation
- `saxsabs.parse_run_policy` — parse resume / overwrite execution policy
- `saxsabs.should_skip_all_existing` — check if all outputs already exist

### I/O

- `saxsabs.parse_header_values` — heterogeneous header parsing
- `saxsabs.read_external_1d_profile` — format-agnostic 1D ingestion
- `saxsabs.write_cansas1d_xml` — canSAS 1D XML export
- `saxsabs.write_nxcansas_h5` — NXcanSAS HDF5 export

## Verification

```bash
pytest -q
```

66 automated tests across 3 OS × 4 Python versions (3.10–3.13).

Manual workflow verification checklist is in `examples/manual-verification.md`.

Minimal anonymized 2D end-to-end reproducibility package:

- `examples/minimal_2d/README.md`
- `python examples/minimal_2d/run_minimal_2d_pipeline.py`

## Documentation

- `docs/architecture.md` — software architecture and design decisions
- `docs/reviewer-faq.md` — FAQ for JOSS reviewers
- `docs/joss-submission-checklist.md` — submission readiness checklist
- `docs/impact-evidence-template.md` — research impact evidence
- `CONTRIBUTING.md` — contribution guidelines
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1
- `CITATION.cff` — citation metadata
- `CHANGELOG.md` — version history

## JOSS paper

Paper draft files:

- `paper/paper.md`
- `paper/paper.bib`
