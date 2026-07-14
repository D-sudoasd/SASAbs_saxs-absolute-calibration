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
│  saxsabs.core.material_attenuation (NIST 30 keV)│
│  saxsabs.core.mu_calculator  (Elam diagnostic μ)│
│  saxsabs.core.intensity_state (1D ledger)       │
│  saxsabs.core.workbench_preflight_gate          │
│  saxsabs.core.buffer_subtraction (BioSAXS)      │
│  saxsabs.workflows.bl19b2_abs2d / integrate1d   │
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
	K-factor estimation, fingerprinted NIST 30 keV material attenuation,
	xraydb/Elam diagnostic attenuation, 1D intensity/correction state, Workbench
	preflight fingerprints, and buffer subtraction). No GUI side-effects —
	deterministic and testable.
- **`src/saxsabs/io`**: robust input parsing plus standard-format writers
	(canSAS XML and NXcanSAS HDF5).
- **`src/saxsabs/cli.py`**: six headless subcommands: four focused utilities
  (`norm-factor`, `parse-header`, `parse-external1d`, `estimate-k`), the
  safety-first `bl19b2-abs2d` workflow, and the explicit
  `bl19b2-abs2d-v1-legacy` migration entry. The legacy entry requires explicit
  monitor and thickness semantics and never silently restores v1 defaults.
- **`src/saxsabs/constants.py`**: pluggable reference-standard registry
	(SRM 3600, water, custom curves).
- **`src/saxsabs/workbench_launcher.py`**: packaged launcher used by
	`saxsabs-workbench` entry point.
- **`src/saxsabs/workflows`**: strict BL19B2 2D absolute-correction and 1D
  integration workflows. These are the campaign-grade provenance baseline;
  the Workbench still contains separate orchestration/scientific callbacks and
  is not yet an equivalent GUI front end to these runners.

## Release-safety contracts

- Calibration-record v2 verifies portable standard/background/dark/reference source paths, ordered SHA-256 identities, built-in reference model versions, integration settings, and robust-estimator parameters. Schema v1 remains readable but cannot authorize formal output.
- Tab 2 and Tab 3 formal outputs require a source-verified calibration record and an operator-compatible `CalibrationContext`. External 1D profiles must also carry matching operator provenance.
- BL19B2 schema v4 validates the complete K/QC contract. Shared background-monitor covariance is propagated jointly; unquantified shared raw-count/dark covariance keeps the combined budget explicitly `partial` and system expanded uncertainty unavailable.
- The reusable `saxsabs.io.calibrated2d` package publishes its multi-file package
  transactionally and resumes only after image, mask, PONI, context, and
  processing-parameter consistency checks. This contract does not make a strict
  BL19B2 whole campaign atomic.
- Detector arrays, headers, and source identities come from one stable snapshot; a source changed during reading is rejected before scientific output publication.
- Workbench formal Tab 2 is fixed-thickness only. The per-frame Beer-Lambert
  control and both Tab 2/Tab 3 existence-only resume controls are UI-disabled;
  forced values make Dry Check BLOCKED and are rejected again at Run. K and μ
  are read-only in Tab 2, and K is read-only in Tab 3.
- Workbench file identities currently bind resolved path, size, and mtime, not a
  content SHA-256 for every selected source. `CAUTION` currently permits Run
  without a separately persisted acknowledgement; these are deliberate open
  boundaries, not properties of the strict runners. BG/Dark reference-library
  mutations explicitly invalidate the in-memory Tab 2 approval.
- Tab 3 raw correction is disabled. Formal K/Kd accepts only an explicitly
  reduced `relative` profile; `raw_counts`, `absolute_cm^-1`, and `ambiguous`
  states fail closed. K/d requires `d > 0`; K-only applies K without repeating
  thickness and requires inherited thickness in `corrections_applied`. Tab 3
  combines inherited corrections with the actual K, optional
  thickness, and optional buffer operations and records that set per frame;
  Tab 2 derives its ledger from the active detector context.
- `corrections_applied` and `do_not_repeat` are parsed separately and unioned for
  duplicate-operation checks. `do_not_repeat` is an execution guard, never proof
  of a required existing correction or absolute physical state; those claims must
  come from `corrections_applied`. If both are present but disagree, intensity
  state becomes ambiguous and formal scaling fails closed.
- Buffer subtraction is absolute-scale only: the buffer must declare
  `absolute_cm^-1`, `1/cm`, K+thickness in `corrections_applied`, no prior buffer
  subtraction, an explicit full active `CalibrationContext` fingerprint, and a
  numeric `k_factor` matching the active K. Operator-payload fallback is not
  sufficient. Dry Check also proves q-range coverage. State, unit, ledger,
  context fingerprint, `BufferKFactor`, `BufferAlphaUncertainty`, alpha, path,
  and hash enter audit output. Optional `u(alpha)` must be finite and non-negative;
  blank maps to `None`, preserving unknown combined uncertainty as NaN.
  The kernel returns the statistical component separately from the combined
  standard uncertainty. Text output writes both columns and uses the combined
  result as the legacy `Error_cm^-1` alias; canSAS/NXcanSAS carry the best
  available combined uncertainty and record the buffer's safe filename/SHA-256,
  alpha, `u(alpha)`, propagation model, and uncertainty type as operator
  provenance.
  The Workbench calls the shared core `subtract_buffer`; if it is unavailable,
  formal subtraction fails closed with no weaker local fallback.
- The NIST 30 keV GUI export is a material-attenuation provenance JSON. It is
  invalidated whenever source/energy/preset/composition/density/porosity input
  changes. Nominal identity is inferred from the edited composition, not copied
  from the selected preset. PONI path/hash/energy are recorded; an available
  non-30 keV PONI is rejected. Missing PONI energy remains explicitly
  `not geometry-bound`. Elam output records xraydb version and cannot select the
  NIST-only porosity flag. This payload is still not a full per-folder thickness
  derivation anchored to accepted raw transmission frames.
  Export re-resolves and re-hashes PONI path, content, and energy, so changes
  after calculation require recalculation. Formal fixed Tab 2 metadata/preflight
  excludes diagnostic attenuation and records `mu_used_in_thickness_model=false`.

## Resource and publication boundaries

- FabIO handles are closed in the strict 1D readers and the strict 2D resume
  verification reader. The shared reference loader, the strict 2D main image
  loader, and multiple Workbench paths still require one common copy-and-close
  loader.
- The reusable calibrated-2D package has transactional multi-file publication
  and signature-aware resume. Workbench existence-only resume is now disabled
  and hard-blocked, but no equivalent content-signature resume exists. The strict
  BL19B2 runner and Workbench both still lack atomic whole-campaign publication.
- The desktop UI has screen-aware initial geometry and a `900 x 600` minimum,
  but it still has no cancellable background `JobController`; high-volume work
  can therefore occupy the Tk event thread.
- Repository hygiene remains open at P1: about 79 MiB of `audit_outputs/` plus
  campaign-specific acceptance tests retain private `H:\...` path coupling.
  They are not portable package fixtures and must be separated, reduced and
  anonymized, or explicitly gated as local-only acceptance assets before release.

## Design goals

1. Preserve scientific behaviour from the production workflow.
2. Make core math independent from GUI toolkits.
3. Enable CI validation and reviewer reproducibility.
4. Support bilingual operation for international beamline user communities.

## Migration status

- **Implemented**: normalization, header parsing, external 1D parsing, robust K
  estimation, NIST 30 keV material core, Elam diagnostic calculator, 1D
  intensity ledger, signed-in-memory Workbench preflight, fixed-thickness
  enforcement, disabled legacy/resume controls, exact K-only/Kd/buffer gates,
  absolute-buffer validation, provenance-aware scrollable μ UI, disabled Tab 3
  raw mode, screen-aware startup, strict BL19B2 workflows, standard writers,
  bilingual GUI, CLI, CI, and paper assets.
- **Still open (P0)**: keep formal multi-folder/per-sample fixed-thickness
  campaigns in the strict CLI/batch owner until Workbench and strict-runner
  kernels are unified; add Workbench campaign ownership, atomic publication,
  and content-signature resume; require numeric inherited thickness and source
  provenance for K-only formal output rather than only a ledger marker.
- **Still open (P1)**: close every FabIO path through a common loader, add a
  cancellable background JobController, persist explicit CAUTION acceptance,
  complete the DPI/theme/language/accessibility matrix, and separate the large
  private-path-coupled campaign audit assets from portable package fixtures.
