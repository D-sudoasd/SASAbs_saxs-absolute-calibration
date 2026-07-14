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

8. Run the focused scientific-safety checks:

   ```bash
   pytest -q tests/test_material_attenuation.py tests/test_mu_calculator.py tests/test_intensity_state.py tests/test_workbench_preflight_gate.py tests/test_workbench_scientific.py
   ```

   Expected: the three nominal NIST 30 keV alloy values, edited-composition
   identity, xraydb version provenance, correction-ledger/buffer contracts,
   disabled legacy paths, preflight invalidation, and screen geometry all pass.

## Workbench safety acceptance

Use anonymized or synthetic files for this UI check. It verifies the controls
that are implemented now; it does not certify the Workbench as an equivalent
front end to the strict BL19B2 campaign runner.

1. Launch the Workbench on a compact desktop (1024 x 700 is the minimum test
   viewport). Confirm the initial window fits the usable screen, the minimum is
   `900 x 600`, and Tab 2/Tab 3 remain vertically scrollable.
2. Load a source-verified calibration record. Confirm K is read-only in Tab 2
   and Tab 3, and μ is read-only in Tab 2. K must follow the active record; μ
   must be populated only by a current calculator result.
3. Open Tab 2. Confirm fixed thickness is selected, while per-frame
   Beer-Lambert and Tab 2 existence-only resume are disabled. Confirm Tab 3
   existence-only resume is also disabled. Programmatically forcing any of
   these legacy values must make Dry Check BLOCKED and must be rejected again
   at the Run entry point.
4. Complete Dry Check with a READY fixture. Confirm Run becomes enabled. Change
   one tracked scientific parameter or source path and confirm Run immediately
   disables. Add BG/Dark files, add either library recursively, and clear the
   libraries; every mutation must immediately invalidate Tab 2 approval. Run
   must also reject a stale approval if a file's recorded size or modification
   time changes after Dry Check.
5. Repeat with BLOCKED fixtures and confirm Run remains disabled. Include Tab 3
   K/d with blank, non-finite, zero, and negative thickness. Record that a
   CAUTION result currently permits Run without a separately persisted
   acknowledgement; this remains an open release gate.
6. In the material calculator, select the NIST 30 keV source and verify:

   - Ti-24Nb-4Zr-8Sn: `74.550355 cm^-1`
   - Ti-6Al-4V: `20.989980 cm^-1`
   - Zr-2.5Nb: `162.949617 cm^-1`

   Confirm the dialog is screen-aware and vertically scrollable. Exact nominal
   composition must attach the nominal material identity; editing that
   composition must produce a custom identity instead of retaining the preset
   label. With PONI energy available, its path/hash/energy must enter JSON and a
   non-30 keV PONI must block NIST calculation. If energy is unavailable, JSON
   must state that it is not geometry-bound. Change source, energy, preset,
   composition, density, or porosity after calculation: μ/provenance must clear
   and Export must disable until recalculation. In Elam mode, porosity must be
   disabled and JSON must record `xraydb_version`. Reopen exported JSON and
   verify `provenance_sha256`. It remains material attenuation provenance, not
   a per-folder derivation tied to accepted raw-transmission frames.
   Calculate once, then modify or replace the PONI at the same path: Export must
   re-read path/content/energy, detect the changed hash/identity, and require
   recalculation. For a formal fixed-thickness Tab 2 dry/run, verify
   preflight/metadata contains no diagnostic attenuation payload and records
   `mu_used_in_thickness_model=false`.
7. Open Tab 3. Confirm raw correction is disabled. Feed a project-owned
   `I_abs_cm^-1` profile back into K or K/d scaling and confirm rejection. Verify
   that formal scaling accepts only explicit `intensity_state=relative` and rejects
   `raw_counts`, `absolute_cm^-1`, `ambiguous`, and missing state. K/d must add K
   and thickness; K-only must add K without reapplying thickness and therefore
   requires inherited `thickness` in `corrections_applied`. Confirm
   `do_not_repeat` is unioned for duplicate-operation protection but cannot prove
   that required thickness was physically applied; disagreement with
   `corrections_applied` makes the profile ambiguous. Note the remaining limit:
   K-only does not yet require inherited thickness value/source provenance.
8. Enable buffer subtraction with a compatible fixture. The buffer must be
   explicit `absolute_cm^-1`, unit `1/cm`, carry K+thickness in
   `corrections_applied`, have no existing `buffer` correction, carry an explicit
   complete `CalibrationContext` fingerprint, and provide numeric `k_factor`
   equal to the active K. Confirm `do_not_repeat` and operator-payload fallback
   alone are rejected. Dry Check
   must reject sample q points outside the buffer range. After Run, confirm
   buffer state/unit/ledger/context fingerprint/path/hash/alpha,
   `BufferKFactor`, `BufferAlphaUncertainty`, and the final `CorrectionsApplied`
   appear in frame report and run metadata. Leave optional `u(alpha)` blank and
   verify it maps to `None` and leaves combined uncertainty NaN. Repeat with a
   finite non-negative value and verify it reaches the single core
   `subtract_buffer` kernel and propagates into combined uncertainty. In text
   output, verify `Error_Statistical_cm^-1` excludes the alpha term,
   `Error_CombinedStandard_cm^-1` includes it, and `Error_cm^-1` equals the
   combined result. Move a single buffered spectrum away from its frame report
   and confirm its own header/provenance still contains the buffer's safe filename
   and SHA-256, alpha, `u(alpha)`, propagation model, and uncertainty type.
   Negative, non-finite, or malformed values must fail closed. Temporarily make
   the shared core kernel unavailable and confirm formal subtraction fails closed
   rather than using a weaker fallback.
9. Before packaging the repository, inspect `audit_outputs/` size and scan tests
   for private drive roots such as `H:\...`. The current roughly 79 MiB campaign
   audit tree and batch-specific path coupling are an open P1 boundary, not a
   portable test-fixture design; do not claim release hygiene is complete.

## Screenshot comparison method

The UI comparison images are session-local visualization artifacts outside the
repository, so this checklist deliberately contains no hard link to them. For
each accepted before/after pair:

- capture only the Workbench window with the same language, theme, screen size,
  DPI, and active tab;
- prefer a window-isolated Win32 capture such as `PrintWindow` and reject images
  containing remote-control overlays, black regions, clipped chrome, or
  unreadable text;
- compare Tab 1, Tab 2, Tab 3, and the μ dialog side by side for reachability,
  scrolling, truncation, read-only/disabled state, warning visibility, and
  status-bar changes;
- retain the session-local artifact inventory with the test log, but do not
  present it as a versioned release artifact or scientific-output provenance.

## Open release gates

The following checks must remain marked incomplete until the corresponding code
exists:

- formal multi-folder/per-sample fixed-thickness campaigns have a Workbench
  owner equivalent to the strict CLI/batch campaign;
- Workbench and strict BL19B2 runner use one shared scientific kernel;
- K-only requires inherited thickness numeric value and source, not just a
  ledger marker;
- Workbench output root has an owner manifest, atomic campaign publication, and
  content-signature resume (existence-only resume must remain disabled);
- Workbench preflight binds critical file content hashes and persists explicit
  CAUTION acceptance;
- all FabIO readers pass normal and exceptional close tests on Windows;
- a cancellable background JobController keeps long jobs off the Tk UI thread.

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
