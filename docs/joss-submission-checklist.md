# JOSS submission checklist

## Repository essentials

- [x] OSI-approved license file (`LICENSE`)
- [x] Installation instructions (`README.md`)
- [x] Citation metadata (`CITATION.cff`)
- [x] Public contribution guidance (`CONTRIBUTING.md`)
- [x] Code of Conduct referenced in `CONTRIBUTING.md`
- [x] `codemeta.json` for metadata interoperability
- [x] README badges (CI, license, Python version)

## Software quality

- [x] Installable package (`pyproject.toml`)
- [x] Automated tests (`tests/`)
- [x] Continuous integration (`.github/workflows/ci.yml`)
- [x] Multi-platform CI matrix (Ubuntu / Windows / macOS × Python 3.10–3.13)
- [x] Headless reproducibility path (`saxsabs` CLI)
- [x] `python -m saxsabs` entry point (`__main__.py`)
- [x] `__version__` in package `__init__.py`

## Documentation

- [x] Manual verification procedure (`examples/manual-verification.md`)
- [x] Architecture and design boundary (`docs/architecture.md`)
- [x] Reviewer FAQ (`docs/reviewer-faq.md`)
- [x] Google-style docstrings on all public API functions

## Paper requirements

- [x] `paper/paper.md` exists
- [x] `paper/paper.bib` exists with DOI-bearing references
- [x] State-of-the-field section with concrete tool comparison table and 13+ rows
- [x] Research impact section with real deployment context
- [x] AI usage disclosure with specific tools and scope (JOSS 2025 policy)
- [x] Final author list, affiliations, and repository URL finalized

## Data availability strategy

- [x] Synthetic examples for parser/calibration logic (expanded to 36 points)
- [x] Public anonymized mini-dataset or documented legal/data constraints statement
      (synthetic 36-point examples serve as open test data; no proprietary data required)

## Pre-submission dry run

- [x] `pytest -q`
- [x] `ruff check src tests`
- [x] JOSS paper PDF build via `openjournals/paperdraft` in CI

## Remaining blockers

- [ ] 6 months of public Git history (JOSS requirement for privately-developed projects)
