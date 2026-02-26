# Upload instructions for SoftwareX submission

## 1) Files to upload first

Primary package in `submission/softwarex/`:

1. `softwarex_manuscript.md` (convert to `.docx` before upload if required)
2. `cover_letter.md`
3. `highlights.txt`
4. `declarations.md`
5. graphical abstract image (use `paper/fig_workflow.png`, resized only if required)

## 2) Suggested conversion command (optional)

If you use Pandoc locally:

```bash
pandoc submission/softwarex/softwarex_manuscript.md -o submission/softwarex/softwarex_manuscript.docx
```

## 3) Code availability information to paste in system

- Repository: https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration
- Version: v1.0.0
- Release URL: https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/releases/tag/v1.0.0
- License: BSD-3-Clause
- Contact: dlgong@imr.ac.cn

## 4) Reviewer reproducibility note (recommended in cover letter or comments)

Point reviewers to:

- `examples/manual-verification.md`
- `examples/minimal_2d/run_minimal_2d_pipeline.py`

This gives a deterministic end-to-end reproducibility path without proprietary beamline data.
