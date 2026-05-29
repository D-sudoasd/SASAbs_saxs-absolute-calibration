"""Basic tests for the extracted reference_matching module."""

import pytest

from saxsabs.core.reference_matching import (
    reference_score,
    select_best_reference,
    build_reference_library,
)


def test_reference_score_basic():
    sample = {"exp": 1.0, "mon": 1000, "trans": 0.8, "mtime": 100000}
    ref = {"exp": 1.0, "mon": 1000, "trans": 0.8, "mtime": 100000}
    s = reference_score(sample, ref, kind="bg")
    assert 0 <= s < 0.01  # almost perfect match


def test_select_best_reference_prefers_close():
    sample = {"exp": 2.0, "mon": 5000, "trans": 0.9, "shape": (1024, 1024)}
    refs = [
        {"path": "far", "exp": 10.0, "mon": 100, "trans": 0.1, "shape": (1024, 1024)},
        {"path": "close", "exp": 2.1, "mon": 5100, "trans": 0.88, "shape": (1024, 1024)},
    ]
    best, score = select_best_reference(sample, refs, kind="bg")
    assert best is not None
    assert best["path"] == "close"
    assert score < 1.0


def test_build_reference_library_skips_bad_paths():
    # Non-existent paths should be skipped gracefully
    refs = build_reference_library(["/this/file/does/not/exist_12345.tif"])
    assert refs == []
