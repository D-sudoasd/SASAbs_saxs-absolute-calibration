---
title: 'saxsabs: A robust workflow for SAXS absolute intensity calibration and external 1D conversion'
tags:
  - Python
  - SAXS
  - absolute intensity calibration
  - synchrotron
authors:
  - name: BL19B2 Team
    affiliation: 1
affiliations:
  - name: SSRF BL19B2
    index: 1
date: 25 February 2026
bibliography: paper.bib
---

# Summary

saxsabs is an open-source Python software package for robust small-angle X-ray scattering (SAXS) absolute-intensity calibration workflows and external 1D profile conversion. The project originated from a production beamline application and is now modularized into testable core functions and command-line interfaces. The package targets a practical gap between azimuthal integration engines and reproducible end-to-end absolute-scaling workflows in real beamline environments, where metadata conventions and file formats are often heterogeneous.

# Statement of need

Absolute-intensity conversion in SAXS pipelines commonly depends on local scripts that combine detector integration outputs, beam-monitor normalization, transmission/thickness corrections, and ad hoc parsing of instrument metadata. In practice, this causes at least three recurring reproducibility problems:

1. metadata heterogeneity across instruments or sessions (e.g., inconsistent header keys and units),
2. non-standard external 1D text formats,
3. workflow logic embedded in GUI callbacks, which is difficult to test and re-run headlessly.

saxsabs addresses these issues by providing:

- monitor-mode-aware normalization (`rate` vs. `integrated`),
- robust header parsing with key normalization and unit handling,
- tolerant external 1D parser across CSV/space/semicolon-delimited formats,
- robust K-factor estimation using overlap-constrained interpolation and median-absolute-deviation filtering,
- deterministic output structures suitable for batch reporting and audit trails.

The package is intended for beamline scientists and SAXS users who need reproducible, automatable absolute-scaling operations while preserving compatibility with existing station workflows.

# State of the field

Existing SAXS software ecosystems provide strong components for integration, modeling, and visualization, including pyFAI for azimuthal integration [@pyfai], SasView for analysis/model fitting [@sasview], and Dioptas for interactive diffraction data reduction [@dioptas]. However, many operational SAXS absolute-calibration workflows still require local glue code to connect these components with beamline metadata parsing, monitor semantics, and batch reporting conventions.

saxsabs is designed for this integration gap rather than replacing integration/modeling engines. Its contribution is workflow robustness and reproducibility around absolute scaling:

- standardized normalization semantics (`rate` vs. `integrated`) with explicit formulas,
- defensive metadata parsing for heterogeneous header dictionaries,
- resilient external 1D ingestion and column inference,
- robust K-factor estimation with explicit overlap constraints,
- headless CLI pathways and automated tests for reviewer-visible validation.

In short, the package complements existing SAXS tools by formalizing the data-plumbing and calibration-control layer that is often left as private scripts.

# Software design

The software is organized in layers:

- `saxsabs.core.normalization`: monitor normalization logic.
- `saxsabs.core.calibration`: robust K-factor estimation API.
- `saxsabs.io.parsers`: metadata/header parsing and external 1D parsing.
- `saxsabs.cli`: headless command-line entry points for reproducible execution.
- legacy GUI script retained for operational continuity while core logic is migrated.

This architecture separates pure numerical logic from user-interface events. Core functions are deterministic and testable, while the legacy GUI remains available for operational continuity. The migration strategy avoids abrupt workflow disruption and supports continuous verification that GUI and CLI pathways produce consistent calibration outcomes.

Key design decisions include:

- explicit handling of monitor normalization modes,
- overlap-limited interpolation against reference curves,
- median and MAD-based robust filtering to reduce outlier sensitivity,
- reproducibility-oriented outputs and command-line execution routes.

# Research impact statement

saxsabs captures a production-proven SAXS calibration workflow and turns it into a publication-grade software package. The immediate impact is methodological reproducibility: calibration and parsing behavior are now testable in CI and executable headlessly without GUI dependence.

The project defines impact along three measurable dimensions:

1. **Operational efficiency**: reduction in manual intervention steps for calibration and external-profile conversion.
2. **Reliability**: reduced failure rate due to heterogeneous metadata and irregular text-file formats.
3. **Traceability**: improved auditability of calibration parameters and outputs.

Because some beamline datasets cannot be publicly redistributed, this repository includes synthetic examples and deterministic tests to demonstrate algorithmic reproducibility. A structured impact-evidence template is provided in the repository for maintainers to report deployment statistics (e.g., number of processed runs, runtime savings, and error-rate changes) in future releases.

This balanced strategy supports immediate reviewability while preserving a path to stronger quantitative impact reporting as additional public evidence becomes available.

# AI usage disclosure

Parts of code refactoring, test skeleton generation, and manuscript drafting were assisted by AI-based coding tools and subsequently reviewed by the authors.

# Acknowledgements

We acknowledge beamline users and collaborators who provided practical feedback on data heterogeneity and workflow failure modes.

# References
