# BL19B2 Absolute-Corrected 2D SAXS Batch Runbook

This runbook describes the BL19B2 TIFF-to-absolute-2D workflow implemented by
`saxsabs bl19b2-abs2d`. It is intended for future beamtime reuse and for AI or
human operators who need to repeat the same processing on a new BL19B2 dataset.

## Inputs

Expected raw data layout:

```text
BL19B2 DATA/
  datXXX/
    reference_saxs/
      dark001.tif
      BG001.tif
      GC001.tif
      MASK_file.edf or Mask.edf
      Cali.yaml
    <sample folders>/*.tif
```

Defaults:

- `ABS` in the TIFF header is treated as sample transmission.
- `--monitor-mode rate` uses `Exposure_time * MON * ABS`; `integrated` uses
  `MON * ABS`. The mode must be selected explicitly.
- Choose exactly one sample-thickness strategy: an explicit material- and
  energy-specific `--mu`, or `--sample-thickness-cm`.
- SRM 3600 uses the NIST certified coupon thickness `0.1055 cm` unless an
  explicit standard thickness is recorded.
- `GC001.tif` is the formal glassy carbon standard.
- `BG001.tif` is the no-sample NIST blank. Its recorded transmission must be
  close to one and is used only as a definition check, not as a divisor.
- `dark001.tif`, `BG001.tif`, `GC001.tif`, and `drt001.tif` are defaults only.
  Use `--dark`, `--background`, `--standard`, and `--direct-beam` when a
  beamtime uses different reference file names.
- `MASK_file.edf`, `Mask.edf`, or an explicit `--mask` path follows the silx/pyFAI convention:
  nonzero pixels are masked. Mask paths must be files, not directories.
- `Cali.yaml` from pydidas can be used as the geometry source; SAXSAbs converts it to a
  run-local PONI file under `config/geometry/`.
- Use exactly one geometry source: `--pydidas-cali-yaml` or `--poni`.

Ignored inputs:

- Old CSV/DAT exports are not used as raw detector data.
- `csv_output`, `processed_*`, `sum`, and `test` folders are excluded from
  sample-frame discovery.

## Correction Formula

Dark is exposure-matched before subtraction:

```text
dark_rate = dark / exposure_dark

S_corr  = S  - dark_rate * exposure_s
BG_corr = BG - dark_rate * exposure_bg
GC_corr = GC - dark_rate * exposure_gc

rate mode:
  BG_norm = BG_corr / (exposure_bg * MON_bg)
  GC_norm = GC_corr / (exposure_gc * MON_gc * T_gc)
  I_net_2D = S_corr / (exposure_s * MON_s * T_s) - alpha * BG_norm

integrated mode:
  BG_norm = BG_corr / MON_bg
  GC_norm = GC_corr / (MON_gc * T_gc)
  I_net_2D = S_corr / (MON_s * T_s) - alpha * BG_norm

I_abs_2D = I_net_2D * K / thickness_cm
```

In both modes the detector dark remains exposure-matched as shown above. The
blank is never divided by a separate `T_bg`.

Thickness:

```text
thickness_cm = -ln(ABS) / mu_cm_inv
```

Beer--Lambert inversion is rejected for transmissions close to zero or one.
Without a reported transmission uncertainty the accepted interval is
`0.001 < T < 0.999`; with `--transmission-abs-uncertainty u_T`, both `T` and
`1-T` must exceed `3*u_T`. Use `--sample-thickness-cm` when transmission is not
sufficiently precise.

Optional uncertainty inputs are
`--monitor-relative-standard-uncertainty`,
`--sample-thickness-relative-standard-uncertainty` (fixed-thickness mode),
`--standard-thickness-relative-standard-uncertainty` (calibration coupon),
`--mu-relative-standard-uncertainty` (Beer--Lambert mode), and
`--alpha-standard-uncertainty`. Unknown values must be omitted and remain
`null`; they are never treated as zero. BL19B2 output records these components
and the K standard/expanded uncertainty, but leaves the combined per-pixel
uncertainty `null` until all statistical and systematic inputs are available.
The monitor value is interpreted as the same relative standard uncertainty on
two independent per-frame readings (sample and blank), so their absolute
contributions are combined in quadrature rather than treated as a common-mode
scale error.

The 2D output does not burn in mask, solid-angle, or polarization correction.
Those corrections are deferred to pyFAI/pydidas reintegration.

## Mask Policy

The final mask is the union of:

- user/beamline mask: `reference_saxs/MASK_file.edf`
- pyFAI detector mask from the copied PONI detector model
- dark hot pixels where `abs(dark001) > dark_hot_pixel_threshold`

For pydidas calibration YAML, `detector_mask_file: .`, blank, `none`, or `null`
means no YAML mask. If the YAML mask is absent, missing, or points to a
directory, the workflow falls back to a real file named `MASK_file.edf`,
`Mask.edf`, or `mask.edf` in `reference_saxs/` when present. An explicit
`--mask` path must point to a file.

The exported mask files are:

```text
masks/bl19b2_mask.npy
masks/bl19b2_mask.edf
```

Mask convention is `pyFAI: 0=valid, 1=masked`.

## Output Contract

Default output is written beside the raw directory, not inside it:

```text
datXXX_absolute_corrected_2D/
  config/
    processing_config.yml
    reference_selection.csv
    run_command.ps1
    processing_environment.json
    code_state.txt
    provenance_summary.json
    geometry/BL19B2_SAXS_Califile.poni
  images_h5/
  images_edf/
  metadata/
  previews/
  masks/
  qc/
  manifests/
  logs/
```

Primary outputs per accepted sample:

- HDF5: `images_h5/<sample_folder>/<stem>_abs2d_cm-1.h5`
- EDF: `images_edf/<sample_folder>/<stem>_abs2d_cm-1.edf`
- JSON sidecar: `metadata/<sample_folder>/<stem>_abs2d.json`
- PNG preview: `previews/<sample_folder>/<stem>_preview.png`

Use `manifests/pydidas_pyfai_index.csv` for downstream batch integration.

When rerunning with the default `overwrite = false`, an existing HDF5/EDF/JSON
sidecar set is skipped only if the JSON sidecar is readable and its
`processing_signature` matches the current run. Resume also verifies source
TIFF identity, HDF5/EDF checksums, internal schema/formula/unit/shape/dtype,
finite unmasked values, and the embedded K uncertainty contract. A mismatch,
unreadable file, or incomplete output set blocks the run instead of overwriting
scientific outputs silently.

## Reuse Command

For a new beamtime, copy `examples/bl19b2_abs2d_template/processing_config.example.yml`,
edit the paths, run a dry scan first, then run the full export.

Template command:

```powershell
$env:PYTHONPATH='src'
python -m saxsabs.cli bl19b2-abs2d `
  --input-root '<BL19B2 DATA>\datXXX' `
  --pydidas-cali-yaml '<BL19B2 DATA>\datXXX\reference_saxs\Cali.yaml' `
  --output-root '<BL19B2 DATA>\datXXX_absolute_corrected_2D' `
  --monitor-mode rate `
  --mu 20.2
```

The value `20.2` above is an explicit example for one material/energy, not a
software default. The actual command used for a run is stored in
`config/run_command.ps1`.

## Downstream pyFAI / pydidas Settings

Use the copied PONI and exported mask. Do not repeat corrections already burned
into the 2D matrix.

Set:

- `dark = None`
- `flat = None`
- `mask = masks/bl19b2_mask.npy`
- `normalization_factor = 1.0`
- `correctSolidAngle` must equal the run's recorded
  `correct_solid_angle_for_k` value (the default template uses `True`).
- `polarization_factor = None`, unless a beamline-specific value is confirmed

Do not reapply:

- dark subtraction
- background subtraction
- transmission correction
- monitor normalization
- thickness scaling
- K factor scaling

## Reproducibility Files

Each run writes:

- `config/processing_environment.json`: Python and package versions.
- `config/code_state.txt`: git branch, commit, dirty status, diff stat, diff,
  and untracked-file list.
- `config/provenance_summary.json`: processing signature, references, mask
  checksum, K report, counts, software versions, and code-state pointer.
- per-frame JSON metadata with `software_versions`, `code_state_ref`, and
  `provenance` pointers.

If `code_state.txt` says `status: dirty`, commit the code or keep the
provenance files with the dataset before using the output in a publication.
