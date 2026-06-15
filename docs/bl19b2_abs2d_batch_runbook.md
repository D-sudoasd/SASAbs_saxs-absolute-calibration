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
      MASK_file.edf
    <sample folders>/*.tif
```

Defaults:

- `ABS` in the TIFF header is treated as sample transmission.
- `MON` is treated as a monitor-rate-like factor, so normalization uses
  `Exposure_time * MON * ABS`.
- `mu_cm_inv = 20.2` is used for Beer-Lambert thickness estimation.
- `GC001.tif` is the formal glassy carbon standard.
- `BG001.tif` is the empty/background frame. If `ABS > 1`, background
  transmission is clamped to `T_bg = 1.0` and a warning is recorded.
- `MASK_file.edf` follows the silx/pyFAI convention: nonzero pixels are masked.

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

BG_norm = BG_corr / (exposure_bg * MON_bg * T_bg)
GC_norm = GC_corr / (exposure_gc * MON_gc * T_gc)

I_net_2D = S_corr / (exposure_s * MON_s * T_s) - alpha * BG_norm
I_abs_2D = I_net_2D * K / thickness_cm
```

Thickness:

```text
thickness_cm = -ln(ABS) / mu_cm_inv
```

The 2D output does not burn in mask, solid-angle, or polarization correction.
Those corrections are deferred to pyFAI/pydidas reintegration.

## Mask Policy

The final mask is the union of:

- user/beamline mask: `reference_saxs/MASK_file.edf`
- pyFAI detector mask from the copied PONI detector model
- dark hot pixels where `abs(dark001) > dark_hot_pixel_threshold`

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

## Reuse Command

For a new beamtime, copy `examples/bl19b2_abs2d_template/processing_config.example.yml`,
edit the paths, run a dry scan first, then run the full export.

Template command:

```powershell
$env:PYTHONPATH='src'
py -3.11 -m saxsabs.cli bl19b2-abs2d `
  --input-root '<BL19B2 DATA>\datXXX' `
  --poni '<path>\BL19B2_SAXS_Califile.poni' `
  --output-root '<BL19B2 DATA>\datXXX_absolute_corrected_2D'
```

The actual command used for a run is stored in `config/run_command.ps1`.

## Downstream pyFAI / pydidas Settings

Use the copied PONI and exported mask. Do not repeat corrections already burned
into the 2D matrix.

Set:

- `dark = None`
- `flat = None`
- `mask = masks/bl19b2_mask.npy`
- `normalization_factor = 1.0`
- `correctSolidAngle = True`
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
