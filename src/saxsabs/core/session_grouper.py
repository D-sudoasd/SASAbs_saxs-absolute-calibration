"""Automatic grouping of SAXS files by acquisition "机时" (beamtime / experimental run).

The goal is to detect clusters of files that were collected close together in time
(typically within the same user beamtime slot) so that:
- Output can be organized into per-session subdirectories
- Auto BG/Dark matching can prefer references from the same group
- Batch reports become more interpretable for users

Implementation uses a simple, robust time-gap clustering algorithm (no heavy deps).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np


@dataclass(frozen=True)
class AcquisitionGroup:
    """A cluster of files presumed to belong to the same experimental run / 机时."""

    group_id: str
    files: list[Path]
    start_ts: float | None = None
    end_ts: float | None = None

    @property
    def size(self) -> int:
        return len(self.files)

    @property
    def duration_minutes(self) -> float | None:
        if self.start_ts is None or self.end_ts is None:
            return None
        return (self.end_ts - self.start_ts) / 60.0


def _get_best_timestamp(
    path: str | Path,
    *,
    header_ts_extractor: Callable[[str | Path], float | None] | None = None,
) -> float | None:
    """Return the best available timestamp for a file (header first, then mtime)."""
    p = Path(path)
    if header_ts_extractor is not None:
        try:
            ts = header_ts_extractor(str(p))
            if ts is not None and np.isfinite(ts) and ts > 0:
                return float(ts)
        except Exception:
            pass

    # Fallback to filesystem mtime (best effort; note that copying files changes it)
    try:
        return p.stat().st_mtime
    except Exception:
        return None


def cluster_by_acquisition_time(
    paths: Sequence[str | Path],
    *,
    gap_minutes: float = 90.0,
    use_header_timestamps: bool = True,
    header_ts_extractor: Callable[[str | Path], float | None] | None = None,
    min_group_size: int = 1,
) -> list[AcquisitionGroup]:
    """Cluster files into groups using a maximum gap between consecutive timestamps.

    Algorithm (deterministic, stable):
    1. For every file obtain the best timestamp (header if available & enabled,
       otherwise os.stat().st_mtime).
    2. Sort files by timestamp (files without timestamp go to the end, in original order).
    3. Walk the sorted list and start a new group whenever the gap to the previous
       file exceeds `gap_minutes`.

    This is intentionally simple and interpretable for beamline users.

    Parameters
    ----------
    paths
        Input file paths (order does not matter).
    gap_minutes
        Maximum allowed gap between two consecutive files in the same group.
        Typical values for synchrotron beamlines: 45–120 minutes.
    use_header_timestamps
        If True and a header_ts_extractor is supplied, prefer header acquisition
        time over filesystem mtime.
    header_ts_extractor
        Optional callable(path) -> unix_timestamp_seconds or None.
        The GUI can pass a wrapper around its header parser.
    min_group_size
        Minimum files required to emit a group (usually 1).

    Returns
    -------
    List of AcquisitionGroup objects, sorted by start time (groups without time last).
    """
    if not paths:
        return []

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_paths: list[Path] = []
    for p in paths:
        sp = str(Path(p).resolve())
        if sp not in seen:
            seen.add(sp)
            unique_paths.append(Path(p))

    # Collect (path, timestamp) pairs
    items: list[tuple[Path, float | None]] = []
    for p in unique_paths:
        ts = None
        if use_header_timestamps:
            ts = _get_best_timestamp(p, header_ts_extractor=header_ts_extractor)
        if ts is None:
            ts = _get_best_timestamp(p, header_ts_extractor=None)
        items.append((p, ts))

    # Stable sort: by timestamp (None last), then by original path for determinism
    items.sort(key=lambda x: (x[1] is None, x[1] or 0.0, str(x[0])))

    if not items:
        return []

    groups: list[AcquisitionGroup] = []
    current_files: list[Path] = [items[0][0]]
    current_start = items[0][1]
    current_end = items[0][1]
    prev_ts = items[0][1]

    gap_seconds = gap_minutes * 60.0

    for p, ts in items[1:]:
        if prev_ts is not None and ts is not None and (ts - prev_ts) <= gap_seconds:
            # continue current group
            current_files.append(p)
            if current_start is None or (ts is not None and ts < current_start):
                current_start = ts
            if current_end is None or (ts is not None and ts > current_end):
                current_end = ts
        else:
            # close previous group
            if len(current_files) >= min_group_size:
                gid = _make_group_id(current_start, current_files[0])
                groups.append(
                    AcquisitionGroup(
                        group_id=gid,
                        files=current_files,
                        start_ts=current_start,
                        end_ts=current_end,
                    )
                )
            # start new
            current_files = [p]
            current_start = ts
            current_end = ts
        prev_ts = ts if ts is not None else prev_ts

    # don't forget the last group
    if len(current_files) >= min_group_size:
        gid = _make_group_id(current_start, current_files[0])
        groups.append(
            AcquisitionGroup(
                group_id=gid,
                files=current_files,
                start_ts=current_start,
                end_ts=current_end,
            )
        )

    # Sort groups by start time (None groups at the end)
    groups.sort(key=lambda g: (g.start_ts is None, g.start_ts or 0.0))
    return groups


def _make_group_id(ts: float | None, first_file: Path) -> str:
    """Generate a human-friendly group identifier."""
    if ts is not None:
        try:
            import datetime

            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.strftime("%Y%m%d_%H%M")
        except Exception:
            pass
    # Fallback using stem of first file
    stem = first_file.stem[:12].replace(" ", "_")
    return f"run_{stem}" if stem else "run_unknown"


def add_group_to_meta(
    meta: dict[str, Any], group: AcquisitionGroup | None
) -> dict[str, Any]:
    """Helper to enrich a sample metadata dict with group information (for reports)."""
    if group is None:
        meta = dict(meta)
        meta["group_id"] = None
        meta["group_size"] = None
        return meta
    meta = dict(meta)
    meta["group_id"] = group.group_id
    meta["group_size"] = group.size
    meta["group_start_ts"] = group.start_ts
    return meta
