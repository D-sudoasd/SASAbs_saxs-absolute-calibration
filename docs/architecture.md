# Architecture

## Layers

```
┌─────────────────────────────────────────────────┐
│  saxsabs_workbench.py   (launcher + logging)    │
│  SASAbs.py              (tkinter GUI, bilingual)│
├─────────────────────────────────────────────────┤
│  saxsabs.cli            (headless CLI)          │
│  saxsabs.workbench_launcher (installed launcher)│
├─────────────────────────────────────────────────┤
│  saxsabs.core.normalization  (monitor norms)    │
│  saxsabs.core.calibration    (K-factor est.)    │
│  saxsabs.core.mu_calculator  (XCOM-based μ)     │
│  saxsabs.core.buffer_subtraction (BioSAXS)      │
│  saxsabs.io.parsers          (header + 1D I/O)  │
│  saxsabs.io.writers          (canSAS/NXcanSAS)  │
│  saxsabs.constants           (standards registry)│
└─────────────────────────────────────────────────┘
```

- **`saxsabs_workbench.py`**: application launcher with CLI flags (`--lang`, `--session`, `--version`), structured logging, and graceful error handling. Dynamically loads `SASAbs.py`.
- **`SASAbs.py`**: production GUI (tkinter) with full bilingual (中文 / English)
	internationalisation, multi-background capillary subtraction, and integrated
	calibration workflows.
- **`src/saxsabs/core`**: pure computation logic (normalization, robust
	K-factor estimation, XCOM-based μ calculator, buffer subtraction with error
	propagation). No GUI side-effects — deterministic and testable.
- **`src/saxsabs/io`**: robust input parsing plus standard-format writers
	(canSAS XML and NXcanSAS HDF5).
- **`src/saxsabs/cli.py`**: four headless sub-commands (`norm-factor`, `parse-header`, `parse-external1d`, `estimate-k`) for batch and CI usage.
- **`src/saxsabs/constants.py`**: pluggable reference-standard registry
	(SRM 3600, water, custom curves).
- **`src/saxsabs/workbench_launcher.py`**: packaged launcher used by
	`saxsabs-workbench` entry point.

## Design goals

1. Preserve scientific behaviour from the production workflow.
2. Make core math independent from GUI toolkits.
3. Enable CI validation and reviewer reproducibility.
4. Support bilingual operation for international beamline user communities.

## Migration status

- **Done**: normalization, header parsing, external 1-D parsing, robust K
	estimation, μ calculator, buffer subtraction, canSAS/NXcanSAS writers,
	bilingual GUI, CLI, CI, and JOSS paper assets.
- **Next**: continue incremental extraction of long GUI callbacks into smaller
	testable orchestration units without behavior drift.
