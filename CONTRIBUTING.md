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
