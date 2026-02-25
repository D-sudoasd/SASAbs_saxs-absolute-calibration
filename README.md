# saxsabs

SAXS absolute intensity calibration and robust external 1D profile parsing utilities.

Standalone desktop app name: **SAXSAbs Workbench**.

This repository is being migrated from a single-file GUI application into an installable, testable, and reproducible research software package suitable for JOSS submission.

## Current status

- Legacy GUI implementation is preserved in `SASAbs.py` and wrapped by `saxsabs_workbench.py`.
- Reusable core functions are extracted into `src/saxsabs`.
- Basic CLI, tests, and CI are included.

## Installation

```bash
pip install -e .
```

## Launch as standalone desktop program (Windows)

Double-click one of the following files in repository root:

- `Start_SAXSAbs_Workbench.bat`
- `saxsabs_workbench.pyw`

Or run:

```bash
python saxsabs_workbench.py
```

Developer tools:

```bash
pip install -e .[dev]
```

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

- `saxsabs.compute_norm_factor`
- `saxsabs.parse_header_values`
- `saxsabs.read_external_1d_profile`
- `saxsabs.estimate_k_factor_robust`

## Verification

```bash
pytest -q
```

Manual workflow verification checklist is in `examples/manual-verification.md`.

Additional review-oriented docs:

- `docs/architecture.md`
- `docs/reviewer-faq.md`
- `docs/joss-submission-checklist.md`
- `docs/impact-evidence-template.md`
- `CONTRIBUTING.md`
- `CITATION.cff`

Impact metrics CSV template:

- `examples/impact_metrics_template.csv`

## JOSS paper

Paper draft files:

- `paper/paper.md`
- `paper/paper.bib`
