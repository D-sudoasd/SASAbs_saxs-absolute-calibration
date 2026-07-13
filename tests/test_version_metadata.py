from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib

from saxsabs import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_metadata_is_consistent():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    codemeta = json.loads((ROOT / "codemeta.json").read_text(encoding="utf-8"))
    zenodo = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    workbench = (ROOT / "SASAbs.py").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == __version__
    assert re.search(rf'^version: "{re.escape(__version__)}"$', citation, re.MULTILINE)
    assert codemeta["version"] == __version__
    assert zenodo["version"] == __version__
    assert workbench.count(f'"{__version__}"') >= 2
    assert f"## [{__version__}] - 2026-07-13" in changelog

def test_source_distribution_manifest_includes_release_metadata():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    included = {
        line.removeprefix("include ").strip()
        for line in manifest
        if line.startswith("include ")
    }
    assert {
        "CHANGELOG.md",
        "CITATION.cff",
        "codemeta.json",
        ".zenodo.json",
        "tests/conftest.py",
    } <= included
