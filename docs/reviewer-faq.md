# Reviewer FAQ

## Why keep the legacy GUI file?

The legacy GUI reflects production beamline operations. Core logic is being incrementally extracted to avoid behavior drift while improving reproducibility.

## How can this be tested without GUI?

Core logic is exposed as importable APIs and CLI commands. Tests run headlessly in CI.

## Data cannot be fully public. How is reproducibility addressed?

The repository includes synthetic examples, a deterministic minimal 2D
end-to-end package (`examples/minimal_2d/`), and automated tests. A manual
verification checklist documents exact commands and expected acceptance ranges.

## Can reviewers verify an end-to-end 2D workflow without beamline data?

Yes. Run:

```bash
python examples/minimal_2d/run_minimal_2d_pipeline.py
```

The script produces deterministic outputs (CSV/TSV/canSAS XML and optional
NXcanSAS HDF5) and writes `summary.json` with an expected `k_factor` range of
`[1.99, 2.01]`.

## What is the software boundary?

`saxsabs` is a reusable SAXS absolute-calibration software package validated on a beamline workflow, not only a site-local script.
