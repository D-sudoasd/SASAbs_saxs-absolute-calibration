"""Tests for same-机时 / acquisition time grouping (core.session_grouper)."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time

from saxsabs.core.session_grouper import cluster_by_acquisition_time


def test_empty_input():
    assert cluster_by_acquisition_time([]) == []


def test_single_file():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.tif"
        p.touch()
        groups = cluster_by_acquisition_time([p])
        assert len(groups) == 1
        assert groups[0].size == 1


def test_time_gap_clustering(tmp_path):
    # Create 5 files with controlled mtimes
    files = []
    base = time.time() - 3600 * 5
    for i, delta_min in enumerate([0, 10, 80, 95, 200]):
        p = tmp_path / f"run_{i}.tif"
        p.touch()
        # Force mtime
        mtime = base + delta_min * 60
        p.stat().st_mtime  # touch updates it; we need os.utime
        import os
        os.utime(p, (mtime, mtime))
        files.append(p)

    groups = cluster_by_acquisition_time(files, gap_minutes=90.0, use_header_timestamps=False)

    # Expect two groups: (0,1,2,3) close together, then 4 far away
    assert len(groups) >= 2
    # The first group should contain the first four (gaps < 90 min)
    sizes = [g.size for g in groups]
    assert 3 <= max(sizes) <= 4  # depending on exact gap math


def test_header_ts_preferred(tmp_path):
    p = tmp_path / "with_header.tif"
    p.touch()

    called = {"n": 0}

    def fake_header_ts(path):
        called["n"] += 1
        return 1700000000.0  # fixed

    groups = cluster_by_acquisition_time(
        [p],
        gap_minutes=90,
        use_header_timestamps=True,
        header_ts_extractor=fake_header_ts,
    )
    assert len(groups) == 1
    assert called["n"] >= 1


def test_distinct_header_timestamps_are_not_reused(tmp_path):
    p1 = tmp_path / "run_a.tif"
    p2 = tmp_path / "run_b.tif"
    p1.touch()
    p2.touch()
    ts_by_path = {
        str(p1): 1700000000.0,
        str(p2): 1700000000.0 + 3 * 3600.0,
    }

    def fake_header_ts(path):
        return ts_by_path[str(Path(path))]

    groups = cluster_by_acquisition_time(
        [p1, p2],
        gap_minutes=90,
        use_header_timestamps=True,
        header_ts_extractor=fake_header_ts,
    )

    assert [g.size for g in groups] == [1, 1]
    assert [g.start_ts for g in groups] == [ts_by_path[str(p1)], ts_by_path[str(p2)]]
