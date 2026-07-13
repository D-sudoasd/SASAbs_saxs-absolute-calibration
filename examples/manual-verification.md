# Manual verification checklist

This file defines a reviewer-friendly verification path when raw beamline data
cannot be fully public.

## Inputs

- Header metadata example (JSON)
- External 1D sample profile (`.csv`/`.dat`)
- Minimal anonymized synthetic 2D package (`examples/minimal_2d/`)

## Steps

1. Install package:

   ```bash
   pip install -e .[dev,hdf5]
   ```

2. Run tests:

   ```bash
   pytest -q
   ```

3. Verify normalization:

   ```bash
   saxsabs norm-factor --mode rate --exp 1.0 --mon 100000 --trans 0.8
   ```

   Expected result: `80000.0`

4. Verify header parsing:

   ```bash
   saxsabs parse-header --header-json examples/header_example.json
   ```

   Expected fields: `exp_s`, `i0`, `trans`

5. Verify external profile parsing:

   ```bash
   saxsabs parse-external1d --input examples/profile_example.csv
   ```

   Expected fields: `points`, `x_col`, `i_col`, `err_col`

6. Verify robust K estimation:

   ```bash
   saxsabs estimate-k --meas examples/k_measured.csv --ref examples/k_reference.csv --qmin 0.01 --qmax 0.2
   ```

   Expected: `k_factor` close to `2.0`, with non-zero `points_used`.

7. Verify the independent synthetic raw-frame → absolute intensity workflow:

   ```bash
   python examples/minimal_2d/run_minimal_2d_pipeline.py
   ```

   Expected outputs in `examples/minimal_2d/outputs/`:

   - `summary.json` reports `validation_type=independent_synthetic_raw_frames`
   - `k_relative_error < 0.005`
   - `sample_max_relative_error < 0.01`
   - `absolute_profile.csv`, `absolute_profile.tsv`, `absolute_profile.xml` exist
   - `absolute_profile.h5` exists when `h5py` is available

## Notes

- The minimal package starts from separately constructed dark, NIST blank,
  SRM 3600, and sample frames. It does not use `I_ref = constant * I_meas`.
- Synthetic validation verifies the implementation but is not evidence of a
  completed beamline measurement validation.
- Proprietary beamline data remain excluded for legal and confidentiality reasons.

## Required beamline acceptance before publication

Process one measured SRM 3600 coupon using the certified thickness 1.055 mm,
independently measured sample/standard transmissions, a no-sample blank, and an
exposure-matched electronic dark. Record the K(q) residuals across the certified
q range, repeatability across at least three acquisitions, and agreement with an
independent secondary standard. Do not mark experimental validation complete
until these files and acceptance results are archived with the processing
provenance.
