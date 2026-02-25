# Architecture

## Layers

- `SASAbs.py`: legacy production GUI workflow (kept for continuity).
- `src/saxsabs/core`: pure computation logic (testable, headless).
- `src/saxsabs/io`: robust input parsing for metadata and external 1D profiles.
- `src/saxsabs/cli.py`: reproducible command-line entry points.

## Design goals

1. Preserve scientific behavior from the legacy workflow.
2. Make core math independent from GUI toolkits.
3. Enable CI validation and reviewer reproducibility.

## Current migration status

- Done: normalization, header parsing, external 1D parsing, robust K estimation.
- Next: extraction of full calibration/batch orchestration from GUI callbacks.
