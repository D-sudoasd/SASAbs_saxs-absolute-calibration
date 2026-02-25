# Manual verification checklist

This file defines a reviewer-friendly verification path when raw beamline data cannot be fully public.

## Inputs

- Header metadata example (JSON)
- External 1D sample profile (`.csv`/`.dat`)

## Steps

1. Install package:

   ```bash
   pip install -e .[dev]
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

## Notes

- For publication, replace placeholder sample files with anonymized or synthetic data and pin expected ranges/tolerances.
