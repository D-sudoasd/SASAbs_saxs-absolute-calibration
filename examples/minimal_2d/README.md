# Minimal anonymized 2D reproducibility package

This folder provides a reviewer-friendly deterministic dataset and script for an
end-to-end SAXS absolute-calibration demo without proprietary beamline files.

## Files

- `synthetic_detector_image.csv`: anonymized synthetic 2D detector image (9x9)
- `synthetic_geometry.json`: minimal geometry metadata
- `run_minimal_2d_pipeline.py`: deterministic 2D→1D→K-factor→absolute export

## Run

```bash
python examples/minimal_2d/run_minimal_2d_pipeline.py
```

Output directory: `examples/minimal_2d/outputs/`

Expected key result:

- `summary.json` with `k_factor` in `[1.99, 2.01]`
- `absolute_profile.csv`, `absolute_profile.tsv`, `absolute_profile.xml`
- `absolute_profile.h5` if `h5py` is installed (`pip install -e .[hdf5]`)
