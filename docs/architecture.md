# Architecture

## Layers

```
┌─────────────────────────────────────────────────┐
│  saxsabs_workbench.py   (launcher + logging)    │
│  SASAbs.py              (tkinter GUI, bilingual)│
├─────────────────────────────────────────────────┤
│  saxsabs.cli            (headless CLI)          │
├─────────────────────────────────────────────────┤
│  saxsabs.core.normalization  (monitor norms)    │
│  saxsabs.core.calibration    (K-factor est.)    │
│  saxsabs.io.parsers          (header + 1D I/O)  │
│  saxsabs.constants           (NIST SRM 3600)    │
└─────────────────────────────────────────────────┘
```

- **`saxsabs_workbench.py`**: application launcher with CLI flags (`--lang`, `--session`, `--version`), structured logging, and graceful error handling. Dynamically loads `SASAbs.py`.
- **`SASAbs.py`**: production GUI (~5 500 lines, tkinter) with full bilingual (中文 / English) internationalisation, multi-background capillary subtraction, and integrated calibration workflows.
- **`src/saxsabs/core`**: pure computation logic (normalization, robust K-factor estimation). No GUI or I/O side-effects — deterministic and testable.
- **`src/saxsabs/io`**: robust input parsing for heterogeneous instrument metadata and format-agnostic external 1-D profiles.
- **`src/saxsabs/cli.py`**: four headless sub-commands (`norm-factor`, `parse-header`, `parse-external1d`, `estimate-k`) for batch and CI usage.
- **`src/saxsabs/constants.py`**: NIST SRM 3600 glassy carbon reference data.

## Design goals

1. Preserve scientific behaviour from the production workflow.
2. Make core math independent from GUI toolkits.
3. Enable CI validation and reviewer reproducibility.
4. Support bilingual operation for international beamline user communities.

## Migration status

- **Done**: normalization, header parsing, external 1-D parsing, robust K estimation, bilingual GUI, CLI, CI, JOSS paper.
- **Next**: extraction of full calibration/batch orchestration from GUI callbacks into `saxsabs.core`.
