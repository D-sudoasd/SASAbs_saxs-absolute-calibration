# saxsabs: Reproducible absolute intensity calibration software for small-angle X-ray scattering

## Authors

Delun Gong
Institute of Metal Research, Chinese Academy of Sciences, Shenyang 110016, China
ORCID: 0000-0001-7877-7707
Email: dlgong@imr.ac.cn

## Abstract

Absolute intensity calibration in small-angle X-ray scattering (SAXS) is often implemented as local, beamline-specific scripts that are difficult to validate, reproduce, and maintain. We present `saxsabs`, an open-source Python software package that provides a reproducible calibration workflow from detector-reduced 1D profiles to absolute-scale intensity outputs, with optional end-to-end support for 2D-derived pipelines in graphical workflows. The software integrates robust normalization, multi-standard calibration (NIST SRM 3600, water, and user-defined references), robust K-factor estimation using MAD-based outlier rejection, composition-based attenuation coefficient calculation via XCOM (`xraydb`), and buffer/solvent subtraction with uncertainty propagation. It also provides standardized outputs in TSV, CSV, canSAS 1D XML, and NXcanSAS HDF5 formats for interoperability. The project includes a command-line interface, a bilingual GUI workbench, continuous integration across Linux/Windows/macOS, and automated tests. A deterministic minimal anonymized dataset is included to demonstrate reviewer-friendly reproducibility without proprietary beamline files. The software is deployed in routine SAXS operations and is designed to reduce manual bookkeeping and improve traceability in absolute intensity workflows.

Keywords: SAXS; absolute intensity calibration; synchrotron; canSAS; NXcanSAS; Python

## Code metadata

| Item | Description |
|---|---|
| Current code version | v1.0.0 |
| Permanent link to code/repository used for this version | https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/releases/tag/v1.0.0 |
| Legal Code License | BSD-3-Clause |
| Code versioning system used | Git |
| Software code languages, tools, and services used | Python; NumPy; pandas; pyFAI; fabio; xraydb; h5py |
| Compilation requirements, operating environments and dependencies | Python >=3.10; core: numpy>=1.24, pandas>=2.0, xraydb>=4.5; optional GUI: pyFAI, fabio, matplotlib, sv-ttk; optional NXcanSAS: h5py |
| Link to developer documentation/manual | https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/blob/main/README.md |
| Support email for questions | dlgong@imr.ac.cn |

## 1. Motivation and significance

Absolute intensity calibration is required for quantitative SAXS interpretation, model comparison, and cross-instrument reproducibility. In practice, calibration involves multiple coupled operations: normalization, transmission handling, subtraction strategy, robust scaling to standards, and export into interoperable downstream formats. While established tools provide strong support for integration and analysis, many laboratories still rely on ad hoc scripts for calibration-control logic and metadata handling. This creates reproducibility and maintenance risks, especially when instrument headers, file formats, and standards vary between beamlines.

`saxsabs` targets this software gap by packaging calibration-control logic into a tested, reusable, and scriptable workflow. The software emphasizes deterministic behavior, explicit formulas, and robust parsing across heterogeneous inputs.

## 2. Software description

### 2.1 Software architecture

The project is organized into four layers:

1. Core numerical layer (`src/saxsabs/core`): monitor normalization, robust K-factor estimation, attenuation coefficient calculation, and buffer subtraction with uncertainty propagation.
2. I/O layer (`src/saxsabs/io`): robust parsers plus standards-oriented writers (canSAS XML and NXcanSAS HDF5).
3. CLI layer (`src/saxsabs/cli.py`): headless commands for batch or CI pipelines.
4. GUI layer (`SASAbs.py` and launcher modules): bilingual desktop workflow for beamline users.

This separation supports both interactive operation and automated reproducibility checks.

### 2.2 Scientific and technical functionality

Main capabilities include:

- Multi-standard calibration with a pluggable registry (`STANDARD_REGISTRY`) containing NIST SRM 3600, water reference behavior, and user-defined references.
- Robust K-factor estimation via median and MAD filtering to reduce sensitivity to outliers.
- Composition-based attenuation coefficient calculation (XCOM-backed via `xraydb`) for arbitrary compositions and photon energies.
- Buffer/solvent subtraction with configurable scaling factor and propagated uncertainty.
- Interoperable export to TSV/CSV/canSAS XML/NXcanSAS HDF5.
- Robust heterogeneous header parsing and format-agnostic external 1D profile ingestion.

### 2.3 Quality assurance and portability

The software is tested in continuous integration on Linux, Windows, and macOS with Python 3.10-3.13. The current test suite includes 52 automated tests covering normalization, calibration, parsing, I/O interoperability, attenuation calculation, and buffer subtraction.

## 3. Illustrative examples

The repository contains command-line examples for each major operation and a deterministic minimal anonymized 2D reproducibility package at `examples/minimal_2d/`. The script `run_minimal_2d_pipeline.py` generates a synthetic detector image workflow, computes a robust K-factor, applies absolute scaling, and exports XML/HDF5-compatible outputs. This package is intended for reviewer reproducibility in contexts where raw beamline data cannot be publicly released.

Representative CLI examples:

- `saxsabs norm-factor --mode rate --exp 1.0 --mon 100000 --trans 0.8`
- `saxsabs parse-header --header-json examples/header_example.json`
- `saxsabs parse-external1d --input examples/profile_example.csv`
- `saxsabs estimate-k --meas examples/k_measured.csv --ref examples/k_reference.csv --qmin 0.01 --qmax 0.2`

## 4. Impact

`saxsabs` is used in routine SAXS calibration workflows at the Institute of Metal Research (Chinese Academy of Sciences). In this deployment context, the package has reduced manual intervention in metadata extraction and improved traceability by producing structured outputs suitable for audit and version control.

The software contributes practical value through:

- workflow standardization across heterogeneous beamline metadata,
- robust scaling resistant to common experimental outliers,
- open and scriptable reproducibility paths (CLI + tests + deterministic examples),
- standards-compatible output for interoperability with downstream SAXS tools.

## 5. Conclusions

`saxsabs` provides a reproducible and extensible calibration-control software layer for absolute-intensity SAXS workflows. By combining robust numerical routines, interoperable data export, and practical deployment pathways (CLI and GUI), it addresses a common gap between integration engines and routine beamline operations.

## Acknowledgments

The author thanks beamline scientists and users at the Institute of Metal Research for workflow feedback and validation discussions.

## Declaration of competing interest

The author declares that there are no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper.

## Data availability

No proprietary raw beamline data are included in the repository. Reviewer reproducibility is supported through deterministic synthetic examples and a minimal anonymized 2D reproducibility package (`examples/minimal_2d/`).

## CRediT authorship contribution statement

Delun Gong: Conceptualization, Methodology, Software, Validation, Investigation, Writing - Original Draft, Writing - Review & Editing.

## References

[1] G. Ashiotis, A. Deschildre, Z. Nawaz, J.P. Wright, D. Karkoulis, F.E. Picca, J. Kieffer, The fast azimuthal integration Python library: pyFAI, Journal of Applied Crystallography 48 (2015) 510-519. https://doi.org/10.1107/S1600576715004306

[2] M. Doucet, et al., SasView version 4.2, Zenodo (2018). https://doi.org/10.5281/zenodo.1412041

[3] C. Prescher, V.B. Prakapenka, DIOPTAS: a program for reduction of two-dimensional X-ray diffraction data and data exploration, High Pressure Research 35 (2015) 223-230. https://doi.org/10.1080/08957959.2015.1059835

[4] J. Ilavsky, P.R. Jemian, Irena: tool suite for modeling and analysis of small-angle scattering, Journal of Applied Crystallography 42 (2009) 347-353. https://doi.org/10.1107/S0021889809002222

[5] J.B. Hopkins, R.E. Gillilan, S. Skou, BioXTAS RAW: improvements to a free open-source program for small-angle X-ray scattering data reduction and analysis, Journal of Applied Crystallography 50 (2017) 1545-1553. https://doi.org/10.1107/S1600576717011438

[6] National Institute of Standards and Technology, Standard Reference Material 3600: Absolute Intensity Calibration Standard for Small-Angle X-ray Scattering (Certificate of Analysis), 2016. https://doi.org/10.18434/M32059

[7] O. Glatter, O. Kratky, Small Angle X-ray Scattering, Academic Press, 1982.

[8] D. Orthaber, A. Bergmann, O. Glatter, SAXS experiments on absolute scale with Kratky systems using water as a secondary standard, Journal of Applied Crystallography 33 (2000) 218-225. https://doi.org/10.1107/S0021889899015216

[9] M. Newville, xraydb: X-ray Reference Data in SQLite, 2023. https://doi.org/10.5281/zenodo.7847236
