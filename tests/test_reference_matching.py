"""Basic tests for the extracted reference_matching module."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from saxsabs.core.reference_matching import (
    build_reference_library,
    reference_score,
    select_best_reference,
)


def test_reference_score_basic():
    sample = {"exp": 1.0, "mon": 1000, "trans": 0.8, "mtime": 100000}
    ref = {"exp": 1.0, "mon": 1000, "trans": 0.8, "mtime": 100000}
    s = reference_score(sample, ref, kind="bg")
    assert 0 <= s < 0.01  # almost perfect match


def test_reference_score_coerces_numeric_string_metadata():
    sample = {"exp": "1.0", "mon": "1000", "trans": "0.8", "mtime": "100000"}
    ref = {"exp": "1.1", "mon": "1100", "trans": "0.75", "mtime": "100600"}
    score = reference_score(sample, ref, kind="bg")

    assert np.isfinite(score)
    assert score < 1e9


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


def test_build_reference_library_default_parser_accepts_header_keyword():
    def fake_open_image(path):
        return SimpleNamespace(data=[[1, 2], [3, 4]], header={"ExposureTime": "1.0"})

    refs = build_reference_library(["synthetic_ref.tif"], open_image_fn=fake_open_image)

    assert len(refs) == 1
    assert refs[0]["path"] == "synthetic_ref.tif"
    assert refs[0]["shape"] == (2, 2)
    assert refs[0]["exp"] is None

def test_build_reference_library_closes_open_image_after_success():
    opened = SimpleNamespace(data=[[1, 2]], header={}, close=Mock())

    refs = build_reference_library(
        ["synthetic_ref.tif"], open_image_fn=lambda path: opened
    )

    assert len(refs) == 1
    opened.close.assert_called_once_with()


def test_build_reference_library_closes_open_image_after_parse_failure():
    opened = SimpleNamespace(data=[[1, 2]], header={}, close=Mock())

    def fail_parse(path, header_dict=None):
        raise ValueError("invalid header")

    refs, rejected = build_reference_library(
        ["synthetic_ref.tif"],
        parse_header_fn=fail_parse,
        open_image_fn=lambda path: opened,
        return_rejections=True,
    )

    assert refs == []
    assert rejected[0]["reason"] == "unreadable_reference"
    opened.close.assert_called_once_with()


def test_select_best_reference_rejects_candidate_without_matched_header_fields():
    sample = {"exp": 1.0, "mon": 1000, "trans": 0.8, "shape": (2, 2)}
    refs = [
        {
            "path": "no_header.tif",
            "shape": (2, 2),
            "exp": None,
            "mon": None,
            "trans": None,
            "mtime": None,
        }
    ]

    best, score, rejected = select_best_reference(
        sample,
        refs,
        kind="bg",
        return_rejections=True,
    )

    assert best is None
    assert score is None
    assert rejected[0]["path"] == "no_header.tif"
    assert "insufficient_matched_fields" in rejected[0]["reasons"]
    assert "no_usable_score" in rejected[0]["reasons"]


def test_select_best_reference_requires_same_shape_by_default():
    sample = {"exp": 1.0, "mon": 1000, "trans": 0.8, "shape": (2, 2)}
    refs = [
        {"path": "wrong_shape.tif", "shape": (4, 4), "exp": 1.0, "mon": 1000, "trans": 0.8}
    ]

    best, score, rejected = select_best_reference(
        sample,
        refs,
        kind="bg",
        return_rejections=True,
    )

    assert best is None
    assert score is None
    assert rejected[0]["path"] == "wrong_shape.tif"
    assert "shape_mismatch" in rejected[0]["reasons"]


def test_build_reference_library_reports_unreadable_candidates_when_requested():
    def fake_open_image(path):
        raise OSError(f"damaged image: {path}")

    refs, rejected = build_reference_library(
        ["damaged_ref.tif"],
        open_image_fn=fake_open_image,
        return_rejections=True,
    )

    assert refs == []
    assert rejected[0]["path"] == "damaged_ref.tif"
    assert rejected[0]["reason"] == "unreadable_reference"


def test_select_best_reference_rejects_candidates_above_score_threshold():
    sample = {"exp": 1.0, "mon": 1000, "trans": 0.9, "shape": (2, 2)}
    refs = [
        {"path": "too_far.tif", "shape": (2, 2), "exp": 100.0, "mon": 1, "trans": 0.1}
    ]

    best, score, rejected = select_best_reference(
        sample,
        refs,
        kind="bg",
        max_score_threshold=0.2,
        return_rejections=True,
    )

    assert best is None
    assert score is None
    assert rejected[0]["path"] == "too_far.tif"
    assert rejected[0]["score"] > 0.2
    assert "score_above_threshold" in rejected[0]["reasons"]
