# JOSS submission checklist

## Repository essentials

- [x] OSI-approved license file (`LICENSE`)
- [x] Installation instructions (`README.md`)
- [x] Citation metadata (`CITATION.cff`)
- [x] Public contribution guidance (`CONTRIBUTING.md`)

## Software quality

- [x] Installable package (`pyproject.toml`)
- [x] Automated tests (`tests/`)
- [x] Continuous integration (`.github/workflows/ci.yml`)
- [x] Headless reproducibility path (`saxsabs` CLI)

## Documentation

- [x] Manual verification procedure (`examples/manual-verification.md`)
- [x] Architecture and design boundary (`docs/architecture.md`)
- [x] Reviewer FAQ (`docs/reviewer-faq.md`)

## Paper requirements

- [x] `paper/paper.md` exists
- [x] `paper/paper.bib` exists
- [ ] State-of-the-field section with concrete tool comparison and citations
- [ ] Research impact section with quantitative evidence from real usage
- [ ] Final author list, affiliations, and repository URL finalized

## Data availability strategy

- [x] Synthetic examples for parser/calibration logic
- [ ] Public anonymized mini-dataset or documented legal/data constraints statement

## Pre-submission dry run

- [x] `pytest -q`
- [x] `ruff check src tests`
- [ ] Build/pandoc validation of JOSS paper in CI or local container
