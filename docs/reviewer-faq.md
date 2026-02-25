# Reviewer FAQ

## Why keep the legacy GUI file?

The legacy GUI reflects production beamline operations. Core logic is being incrementally extracted to avoid behavior drift while improving reproducibility.

## How can this be tested without GUI?

Core logic is exposed as importable APIs and CLI commands. Tests run headlessly in CI.

## Data cannot be fully public. How is reproducibility addressed?

The repository includes synthetic examples and deterministic test cases. A manual verification checklist documents expected outputs and tolerances.

## What is the software boundary?

`saxsabs` is a reusable SAXS absolute-calibration software package validated on a beamline workflow, not only a site-local script.
