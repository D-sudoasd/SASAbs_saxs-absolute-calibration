---
title: "A reproducible calibrated-detector-image package for synchrotron SAXS absolute-intensity workflows"
authors:
  - name: Delun Gong
    orcid: 0000-0001-7877-7707
    affiliation: 1
affiliations:
  - name: Institute of Metal Research, Chinese Academy of Sciences, Shenyang 110016, China
    index: 1
bibliography: jac_calibrated2d_refs.bib
---

<!--
Draft scope note:
This manuscript is written as a target JAC-style software paper for the stronger
innovation route discussed in the project assessment. It assumes that the
calibrated 2D package exporter, schema validation, checksum manifest,
reintegration recipe, and benchmark examples will be completed before submission.
Replace every TODO with measured values, file names, screenshots, or repository
links before sending to a journal.
-->

# Synopsis

SAXSAbs defines a reproducible calibrated-detector-image package for synchrotron
small-angle X-ray scattering absolute-intensity workflows. The package preserves
an absolute-scale detector image together with the mask, pyFAI geometry, correction
policy, provenance records and a reintegration recipe, allowing third parties to
recalculate calibrated one-dimensional profiles without access to beamline-private
bookkeeping.

# Abstract

Absolute-intensity calibration is essential when small-angle X-ray scattering
(SAXS) profiles are compared between instruments, experiments or quantitative
models, yet the intermediate data required to audit this calibration are often
lost after detector images have been reduced to one-dimensional curves. We present
SAXSAbs, an open-source Python package that defines and implements a reproducible
calibrated-detector-image package for synchrotron SAXS workflows. The package
contains a detector-space net image on an absolute intensity scale, the mask and
pyFAI PONI geometry used for integration, a machine-readable correction policy,
processing provenance, checksums and an executable reintegration recipe. SAXSAbs
builds on pyFAI for azimuthal integration and focuses on the calibration-control
layer: robust K-factor estimation against standard references, monitor-mode-aware
normalization, transmission and thickness handling, optional flat-field correction,
buffer subtraction and standards-oriented export. The workflow is designed to
complement existing diffraction and scattering platforms by making the calibrated
intermediate state portable and independently verifiable. In deterministic
examples and synchrotron beamline tests, the exported package can be reintegrated
with pyFAI to reproduce the reported absolute one-dimensional profile within
TODO tolerance, while retaining enough metadata to diagnose common failure modes
such as geometry mismatch, invalid transmission, inconsistent masks and unstable
K-factor estimates. This approach turns a beamline-specific calibration procedure
into an auditable data object that can be shared with collaborators, reviewers
and downstream analysis tools.

Keywords: SAXS; absolute intensity calibration; synchrotron data reduction;
pyFAI; reproducibility; metadata provenance; calibrated detector image.

# 1. Introduction

Two-dimensional area detectors have made synchrotron SAXS and combined
SAXS/WAXS experiments efficient enough that data reduction is now frequently a
high-throughput workflow rather than a single-image operation. Modern beamlines
therefore rely on software that can read detector images, apply geometric
calibration, handle masks and detector corrections, integrate images and process
large image series. Mature tools already exist for many of these tasks. pyFAI
provides a fast and widely used azimuthal-integration library with explicit
geometry handling through PONI files [@pyfai]. pydidas provides an accessible
graphical and scriptable workflow environment for X-ray diffraction data
processing [@pydidas]. StreamSAXS targets both offline and streaming SAXS/WAXS
workflows at synchrotron facilities [@streamsaxs]. Earlier and established tools
such as FIT2D [@fit2d], Nika [@nika], DPDAK [@dpdak], Dioptas [@dioptas],
BioXTAS RAW [@bioxtasraw], Irena [@irena] and GSAS-II [@gsasii] further
demonstrate that image reduction, integration, exploration and downstream
analysis are already well represented in the scattering and diffraction software
ecosystem.

The remaining reproducibility problem addressed here is narrower but common in
practice. Once a SAXS detector image has been corrected, normalized, background
subtracted, calibrated against a standard and integrated to a one-dimensional
profile, the calibrated intermediate image and the precise correction policy are
often not preserved in a form that another researcher can reuse. Collaborators
may receive only a final text file containing \(q\), \(I(q)\) and an uncertainty
column. Reviewers may be unable to determine whether the reported intensity scale
depends on the chosen transmission, thickness, monitor semantics, mask
convention, flat-field correction or PONI geometry. Beamline staff may retain the
knowledge required to regenerate the profile, but that knowledge is frequently
encoded in local scripts, graphical-session state or manual spreadsheets rather
than in a portable data product.

This gap is especially important for absolute-intensity SAXS. Quantitative SAXS
interpretation depends on bringing measured scattering intensities onto an
absolute differential cross-section scale. Calibration against reference
standards such as NIST SRM 3600 glassy carbon [@srm3600] or liquid water
[@orthaber2000] requires normalization by beam-monitor quantities, transmission
and sample thickness, followed by estimation of a scale factor that can be
sensitive to parasitic scattering, beamstop shadows and detector artefacts. A
final one-dimensional profile is therefore not a complete record of the
calibration decision. To make absolute-intensity data reproducible, the
detector-space state after correction and calibration should be shareable
together with the geometry, mask, standards, formulas and software versions used
to create it.

SAXSAbs was developed to formalize this calibration-control layer. The software
does not attempt to replace pyFAI, pydidas or general-purpose SAXS/WAXS workflow
platforms. Instead, it defines a calibrated-detector-image package that can be
produced by a SAXS absolute-calibration workflow and reintegrated by standard
tools. The package contains the absolute-scale detector image, the mask, the
PONI geometry, a correction-policy record, provenance metadata, checksums and a
reintegration recipe. The design goal is that a third party can inspect the
package, verify file integrity, rerun azimuthal integration and recover the
reported absolute one-dimensional curve without reconstructing private beamline
bookkeeping.

# 2. Software overview

SAXSAbs is an open-source Python package with a modular numerical core, a command
line interface and a bilingual graphical workbench. The existing core implements
monitor normalization, robust K-factor estimation, a standard-reference registry,
a composition-based attenuation coefficient calculator using xraydb [@xraydb],
buffer subtraction with uncertainty propagation, heterogeneous header parsing and
canSAS/NXcanSAS one-dimensional export. The graphical workflow uses pyFAI and
FabIO-compatible detector I/O for practical two-dimensional image processing,
while the installable package exposes the calibration logic for headless testing
and scripted operation.

The calibrated-detector-image package extends this software boundary from final
curve export to reproducible intermediate export. The central object is an image
array in detector coordinates after dark-current subtraction, monitor
normalization, background subtraction, optional flat-field correction and
absolute K-factor scaling have been applied according to a recorded policy. The
image is kept in detector space rather than transformed into reciprocal-space
coordinates because detector space preserves the exact pixel mask and pyFAI
geometry relation needed for independent reintegration. The package therefore
acts as a bridge between raw beamline images that may be too large or private to
share and final one-dimensional curves that are too reduced to audit.

# 3. Package definition

The package is organized as a small directory tree with stable file roles. A
typical package contains an image file, a mask file, a PONI geometry file, a
metadata file, a manifest and a reintegration script or recipe. The image stores
the calibrated detector-space intensity. The mask records invalid pixels using a
declared convention compatible with pyFAI. The PONI file preserves detector
distance, beam centre, rotations, pixel sizes and wavelength. The metadata file
records sample identifiers, raw source paths or anonymized source names,
correction settings, absolute-calibration parameters, software versions and
recommended reintegration arguments. The manifest records all files in the
package and their checksums so that corruption or accidental replacement can be
detected.

The correction policy is deliberately explicit. It records whether dark-current
subtraction, background subtraction, flat-field correction, polarization
correction, solid-angle correction, transmission correction, thickness
normalization and K-factor scaling were applied in the image or should be applied
during reintegration. This distinction is essential because a calibrated image
can otherwise be double-corrected or under-corrected when it is passed to another
program. For example, if the detector-space image has already been scaled to
absolute units and divided by thickness, the reintegration recipe sets the
normalization factor to unity and instructs pyFAI not to reapply the same
normalization. Conversely, corrections that remain integration dependent, such
as solid-angle correction, are recorded in the reintegration recipe rather than
silently embedded in undocumented state.

The metadata schema is versioned. Versioning allows the package to evolve while
remaining machine-readable, and it allows old packages to be validated against
the schema that created them. The initial schema records the package identifier,
sample identifier, image type, intensity unit, mask convention, geometry file,
correction policy, reference standard, K-factor estimate, K-factor uncertainty,
normalization mode, monitor values, transmission, thickness, q range, azimuthal
range, software versions and checksum manifest. The schema is intentionally
small enough to be reviewed in a text editor but explicit enough for automated
validation and reintegration.

# 4. Calibration and reintegration workflow

The workflow starts from a standard sample, one or more background images, a dark
image, a pyFAI PONI geometry file and optional mask and flat-field images. The
standard and background images are normalized by the selected monitor convention.
In rate mode the normalization factor is
\[
N = t_{\mathrm{exp}} I_0 T,
\]
where \(t_{\mathrm{exp}}\) is the exposure time, \(I_0\) is the beam-monitor
quantity and \(T\) is the transmission. In integrated mode the exposure-time
factor is omitted because the monitor value already represents integrated counts.
The detector-space net image is calculated by subtracting the normalized dark
and background contributions from the normalized sample signal.

The net standard image is integrated with pyFAI to obtain an observed profile.
SAXSAbs estimates the absolute K factor by comparing this profile with a
registered reference standard. For NIST SRM 3600 glassy carbon, the reference
profile is interpolated over a specified q range and point-wise ratios between
reference and measured intensities are calculated. The final K factor is the
median of the accepted ratios after median absolute deviation filtering. This
robust estimator reduces sensitivity to isolated detector artefacts or q points
affected by parasitic scattering. For liquid water, the software uses a
temperature-dependent flat reference value and applies the same robust dispersion
logic to the selected q window.

After the K factor has been determined, the detector-space image for each sample
is scaled to absolute intensity according to the recorded thickness and
normalization policy. The calibrated image, mask, PONI file and metadata are
written into the package. The reintegration recipe then calls pyFAI with the
stored PONI file and mask and with normalization choices that reflect the
correction policy. The expected output is a one-dimensional profile on the same
absolute scale as the original SAXSAbs batch result. This reintegration step is
the central reproducibility test: a package is considered valid only if the
reported profile can be regenerated from the exported intermediate state within
a declared numerical tolerance.

# 5. Implementation

The package implementation is designed around pure functions where possible.
Image scaling, sample identifier generation, metadata construction, manifest
creation and checksum calculation are separated from graphical user-interface
state. This separation allows deterministic tests to verify individual
behaviours, such as flat-field application, mask conversion, PONI copying and
metadata generation. The intended public API consists of a configuration object
describing the calibrated image export and a writer function that creates the
package directory and returns the paths and manifest row for downstream logging.

The graphical workbench uses this API after two-dimensional background
subtraction and absolute scaling have been completed. The same API can also be
called from command-line workflows, which is important for beamline automation
and continuous-integration tests. The package writer does not require raw
beamline files to be published; it records source-file identities and provenance
while allowing users to anonymize paths or provide relative identifiers when
sharing data externally. This design balances reproducibility with the practical
constraints of facility data policies and proprietary measurements.

SAXSAbs writes standard one-dimensional outputs in CSV, TSV, canSAS XML and
NXcanSAS HDF5, but the calibrated-detector-image package is distinct from these
final products. The one-dimensional formats are suitable for modelling and
downstream analysis, whereas the package is intended for audit, reintegration
and method review. In a typical publication workflow, authors can deposit the
small package for representative samples alongside final profiles, allowing
reviewers to confirm that the reported absolute scale can be reconstructed.

# 6. Demonstration and validation plan

The first validation example is a deterministic synthetic detector dataset
included in the repository. The example contains a small detector image, a
minimal geometry description and a scripted workflow that produces an absolute
profile and standard-format outputs. In the calibrated-package validation, this
example will be extended so that the package writer exports the detector-space
absolute image, mask, PONI file, metadata and manifest. The reintegration recipe
will then regenerate the one-dimensional profile and compare it with the profile
produced during the original workflow. The expected acceptance criterion is a
relative intensity difference below TODO value across the valid q range and a
K-factor within TODO range.

The second validation example should use an anonymized synchrotron beamline
dataset measured with a standard sample and a representative unknown sample.
This dataset should demonstrate the practical value of the package under
realistic conditions, including non-trivial masks, beamstop shadows, background
subtraction and real metadata heterogeneity. The manuscript should report the
number of images, detector format, q range, beam energy, standard type, exposure
conditions, K-factor dispersion, number of rejected q points, package size and
reintegration agreement. If the raw data cannot be released, the calibrated
package and a reduced anonymized subset should still be deposited so that the
central reproducibility claim can be checked.

The third validation example should evaluate failure detection. Deliberate
perturbations of the package can be used to test whether schema validation and
quality-control checks detect an incompatible mask shape, a missing PONI file, a
changed checksum, invalid transmission, inconsistent wavelength or a correction
policy that would double-apply normalization. These tests convert common
beamline workflow mistakes into documented software behaviours rather than
unobserved failure modes.

# 7. Results to report before submission

The final manuscript should report quantitative results rather than only
software capabilities. The most important result is reintegration agreement:
the one-dimensional absolute profile regenerated from the calibrated package
should match the original SAXSAbs output within a clearly stated tolerance.
Agreement should be shown for the synthetic example and at least one real
beamline example. The second result is audit completeness: every reported curve
should be traceable to a package identifier, checksum manifest, PONI file, mask,
correction policy, standard reference and K-factor estimate. The third result is
quality-control behaviour: invalid or inconsistent packages should fail with
specific diagnostics instead of producing silent numerical output.

For a JAC submission, the figures should carry most of the evidence. Figure 1
should present the conceptual workflow from raw detector images to the
calibrated package and then to independently regenerated one-dimensional
profiles. Figure 2 should show the package structure and metadata schema,
including the correction-policy fields. Figure 3 should compare the original
and reintegrated absolute profiles for the synthetic and beamline examples.
Figure 4 should summarize quality-control diagnostics and failure cases. A table
should compare SAXSAbs with pyFAI, pydidas, StreamSAXS, Nika, DPDAK, Dioptas and
BioXTAS RAW, but it should avoid framing those tools as inadequate. The correct
message is that those tools solve integration, workflow and analysis problems,
whereas SAXSAbs contributes a portable absolute-calibration audit package.

# 8. Discussion

The main contribution of SAXSAbs is not a new azimuthal-integration algorithm
and not a general-purpose graphical workflow platform. Those areas are already
well served by established software. The contribution is the definition and
implementation of a shareable calibrated intermediate state for absolute SAXS
workflows. This distinction is important for novelty because it positions the
software as a complement to the existing ecosystem. pyFAI remains the integration
engine, pydidas and StreamSAXS remain broader workflow platforms, and SAXSAbs
provides a calibrated data object that makes the absolute-intensity step
auditable.

The calibrated-detector-image package also changes how SAXS data can be reviewed
and reused. A final one-dimensional profile is compact and convenient, but it is
not sufficient to diagnose many reduction choices. Raw detector images are
complete, but they may be large, facility-specific or restricted by data policy.
The proposed package occupies an intermediate position. It is smaller and easier
to share than a complete raw experiment, but it retains the detector-space
information, geometry and correction policy needed to regenerate the reported
absolute profile. This is particularly useful when a paper reports quantitative
intensities, compares measurements across beamlines or uses absolute scale as an
input to modelling.

There are limitations. The package does not remove the need for correct
experimental calibration, and it cannot rescue measurements with poor standards,
incorrect transmissions or unsuitable backgrounds. Its reproducibility claim is
bounded by the recorded correction policy and by the behaviour of the integration
engine used for reintegration. Different versions of pyFAI may differ at small
numerical levels, especially when integration methods, error models or
correction flags change. For this reason, the package records software versions
and recommended integration parameters, and the validation should specify
acceptable tolerances rather than requiring bitwise identity.

Future development will focus on strengthening interoperability with downstream
workflow tools and on extending the validation set. A pydidas-compatible import
example would allow users to treat the calibrated image package as an upstream
data product. Additional real-time or time-resolved examples would test whether
the same package concept scales to in situ SAXS/WAXS series. A community schema,
if adopted beyond this project, could provide a lightweight convention for
publishing auditable SAXS absolute-calibration intermediates alongside final
profiles.

# 9. Conclusions

SAXSAbs provides a reproducible calibrated-detector-image package for
synchrotron SAXS absolute-intensity workflows. By preserving the absolute-scale
detector image together with mask, PONI geometry, correction policy, provenance,
checksums and reintegration instructions, the package makes the calibrated
intermediate state independently verifiable. The software is designed to
complement established integration and workflow tools rather than replace them.
After completion of the package exporter, schema validation and beamline
benchmark, this positioning should provide a stronger and more defensible basis
for a Journal of Applied Crystallography software submission than a conventional
GUI or batch-processing claim.

# Figure and table plan

**Figure 1. Workflow overview.** Raw standard, sample, background and dark images
enter the SAXSAbs calibration-control workflow. The output is both a final
absolute one-dimensional profile and a calibrated-detector-image package that
can be reintegrated independently.

**Figure 2. Package anatomy.** Directory tree and schema fields for the image,
mask, PONI geometry, metadata, correction policy, checksum manifest and
reintegration recipe.

**Figure 3. Reproducibility test.** Overlay of original SAXSAbs output and
profile regenerated from the calibrated package for synthetic and beamline
examples, with residuals shown below.

**Figure 4. Quality-control behaviour.** Examples of validation failures caused
by changed checksums, incompatible mask shape, missing PONI file, invalid
transmission and inconsistent correction policy.

**Table 1. Ecosystem comparison.** Comparison of pyFAI, pydidas, StreamSAXS,
Nika, DPDAK, Dioptas, BioXTAS RAW and SAXSAbs across integration, workflow,
absolute calibration, calibrated package export, provenance and reintegration
verification.

# Data availability

The source repository includes a deterministic synthetic example for reviewer
reproducibility. Before submission, the calibrated-detector-image package
generated from this example and at least one anonymized synchrotron beamline
example should be deposited in a public archive. TODO: add archive DOI, package
checksums and exact command lines.

# Code availability

SAXSAbs is available from GitHub at
https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration and archived at
Zenodo with DOI https://doi.org/10.5281/zenodo.19687104. TODO: update this
statement to the exact release DOI used for the JAC submission.

# Conflict of interest

The author declares no competing interests.

# Acknowledgements

The author thanks beamline users and scientists at the Institute of Metal
Research, Chinese Academy of Sciences, for practical feedback on SAXS
absolute-intensity calibration workflows and metadata heterogeneity. TODO: add
beamline/facility acknowledgements required by the real validation dataset.

