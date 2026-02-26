# Contributing

Thanks for contributing to `saxsabs`.

## Development setup

```bash
pip install -e .[dev]
pytest -q
ruff check src tests
```

## Pull request checklist

- Add or update tests for behavior changes.
- Keep GUI and core logic separated when possible.
- Update docs for new CLI/API behavior.
- Ensure CI is green.

## Scope policy

This project prioritizes robust SAXS absolute-calibration workflows and reproducible data-processing paths. PRs that improve reliability, reproducibility, and traceability are preferred.

## Reporting bugs

Please open an issue at <https://github.com/D-sudoasd/SASAbs_saxs-absolute-calibration/issues> with:

- A clear title and description of the problem.
- Steps to reproduce the issue.
- Expected vs. actual behaviour.
- Python version, OS, and relevant package versions (`pip list`).

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you are expected to uphold this code. Please report unacceptable behaviour to the repository maintainer.
