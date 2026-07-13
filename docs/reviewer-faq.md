# Reviewer FAQ

## Why keep the legacy GUI file?

The legacy GUI reflects production beamline operations. Core logic is being incrementally extracted to avoid behavior drift while improving reproducibility.

## How can this be tested without GUI?

Core logic is exposed as importable APIs and CLI commands. Tests run headlessly in CI.

## Data cannot be fully public. How is reproducibility addressed?

The repository includes synthetic examples, an independent deterministic raw-frame
validation package (`examples/minimal_2d/`), and automated tests. A manual
verification checklist documents exact commands and expected acceptance ranges.

## Can reviewers verify the numerical 2D chain without beamline data?

Yes. Run:

```bash
python examples/minimal_2d/run_minimal_2d_pipeline.py
```

The script constructs independent dark, blank, SRM 3600, and sample frames,
produces deterministic outputs (CSV/TSV/canSAS XML and optional NXcanSAS HDF5),
and writes numerical K and sample-intensity errors to `summary.json`. This is a
software golden test, not a substitute for measured beamline validation.

## What is the software boundary?

`saxsabs` is a reusable SAXS absolute-calibration package with deterministic
software validation and a documented protocol for separate beamline acceptance.
