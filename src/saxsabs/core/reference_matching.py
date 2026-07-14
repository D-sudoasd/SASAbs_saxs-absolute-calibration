"""Reference (BG / Dark) library building and best-match selection for batch workflows.

Extracted from the legacy GUI to provide a pure, testable implementation
that can be used by both the Workbench and future CLI batch tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np


NO_USABLE_REFERENCE_SCORE = 1e9
DEFAULT_MAX_SCORE_THRESHOLD = 0.5
DEFAULT_MIN_MATCHED_FIELDS = 2


@dataclass(frozen=True)
class ReferenceEntry:
    """Normalized entry in a BG or Dark reference library."""

    path: str
    shape: tuple[int, int] | tuple[int, int, int] | None
    exp: float | None
    mon: float | None
    trans: float | None
    mtime: float | None  # unix timestamp seconds


def _relative_diff(a: Any, b: Any) -> float | None:
    """Relative absolute difference, safe for None / non-finite values."""
    if a is None or b is None:
        return None
    try:
        fa = float(a)
        fb = float(b)
    except Exception:
        return None
    if not (np.isfinite(fa) and np.isfinite(fb)):
        return None
    den = max(abs(fa), 1e-12)
    return abs(fa - fb) / den


def _positive_finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not np.isfinite(out) or out <= 0:
        return None
    return out


def _matched_scientific_fields(
    sample_meta: dict[str, Any], ref_meta: dict[str, Any], kind: str = "bg"
) -> list[str]:
    """Return sample/ref header fields that are positive finite in both records.

    File modification time is intentionally excluded here. It is useful as a
    tie-breaker in the score, but it is not enough scientific evidence to
    auto-select a BG/Dark reference when headers are missing.
    """
    fields = ["exp", "mon"]
    if kind == "bg":
        fields.append("trans")

    matched = []
    for field in fields:
        if (
            _positive_finite_float(sample_meta.get(field)) is not None
            and _positive_finite_float(ref_meta.get(field)) is not None
        ):
            matched.append(field)
    return matched


def build_reference_library(
    paths: list[str | Path] | None,
    *,
    parse_header_fn: Callable[[str | Path, dict | None], tuple[float | None, float | None, float | None]] | None = None,
    open_image_fn: Callable[[str | Path], Any] | None = None,
    return_rejections: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a list of reference metadata dicts from candidate BG/Dark files.

    This function performs I/O (fabio open + header parsing). It is intentionally
    kept here (rather than pure) because the GUI already depends on fabio for the
    whole batch path. The scoring functions below are pure.

    Parameters
    ----------
    paths
        List of file paths to consider as references.
    parse_header_fn
        Callable(path, header_dict) -> (exp, mon, trans). If None, a no-op that
        returns (None, None, None) is used (caller can enrich later).
    open_image_fn
        Callable(path) -> object with .data and optional .header. Defaults to
        a lazy import of fabio.

    Returns
    -------
    List of dicts with keys: path, shape, exp, mon, trans, mtime (suitable for
    reference_score / select_best_reference).
    """
    if not paths:
        return ([], []) if return_rejections else []

    unique_paths = list(dict.fromkeys(str(p) for p in paths if p))

    if parse_header_fn is None:
        def parse_header_fn(p, header_dict=None):  # type: ignore
            return None, None, None

    if open_image_fn is None:
        def _lazy_fabio_open(p):
            import fabio

            return fabio.open(p)

        open_image_fn = _lazy_fabio_open

    refs: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for p in unique_paths:
        img = None
        try:
            img = open_image_fn(p)
            raw_data = getattr(img, "data", None)
            shape = tuple(np.asarray(raw_data).shape) if raw_data is not None else None
            hdr = getattr(img, "header", {}) or {}
            exp, mon, trans = parse_header_fn(p, header_dict=hdr)
            mtime = Path(p).stat().st_mtime if Path(p).exists() else None
            refs.append(
                {
                    "path": str(p),
                    "shape": shape,
                    "exp": exp,
                    "mon": mon,
                    "trans": trans,
                    "mtime": mtime,
                }
            )
        except Exception:
            rejected.append(
                {
                    "path": str(p),
                    "reason": "unreadable_reference",
                }
            )
            continue
        finally:
            close = getattr(img, "close", None) if img is not None else None
            if callable(close):
                close()
    return (refs, rejected) if return_rejections else refs


def reference_score(
    sample_meta: dict[str, Any], ref_meta: dict[str, Any], kind: str = "bg"
) -> float:
    """Compute a scalar similarity score (lower = better match).

    The scoring logic is identical to the original GUI implementation:
    - exposure time (weight 1.0)
    - monitor counts (weight 0.8)
    - transmission (only for kind=="bg", weight 1.5)
    - file mtime proximity (decaying, max penalty 1.5)

    Returns 1e9 when no usable fields are present (worst possible score).
    """
    score = 0.0
    used = 0.0

    se, re = sample_meta.get("exp"), ref_meta.get("exp")
    sm, rm = sample_meta.get("mon"), ref_meta.get("mon")
    st, rt = sample_meta.get("trans"), ref_meta.get("trans")
    stime, rtime = sample_meta.get("mtime"), ref_meta.get("mtime")

    se_v, re_v = _positive_finite_float(se), _positive_finite_float(re)
    if se_v is not None and re_v is not None:
        d = _relative_diff(se_v, re_v)
        if d is not None:
            score += d * 1.0
            used += 1.0

    sm_v, rm_v = _positive_finite_float(sm), _positive_finite_float(rm)
    if sm_v is not None and rm_v is not None:
        d = _relative_diff(sm_v, rm_v)
        if d is not None:
            score += d * 0.8
            used += 0.8

    st_v, rt_v = _positive_finite_float(st), _positive_finite_float(rt)
    if kind == "bg" and st_v is not None and rt_v is not None:
        score += abs(st_v - rt_v) * 1.5
        used += 1.5

    if stime is not None and rtime is not None:
        try:
            dt_h = abs(float(stime) - float(rtime)) / 3600.0
            score += min(dt_h / 24.0, 3.0) * 0.5
            used += 0.5
        except Exception:
            pass

    if used == 0:
        return NO_USABLE_REFERENCE_SCORE
    return score / used


def score_reference_candidate(
    sample_meta: dict[str, Any],
    ref_meta: dict[str, Any],
    kind: str = "bg",
    *,
    max_score_threshold: float | None = DEFAULT_MAX_SCORE_THRESHOLD,
    require_same_shape: bool = True,
    min_matched_fields: int = DEFAULT_MIN_MATCHED_FIELDS,
) -> dict[str, Any]:
    """Score and validate one reference candidate.

    The returned dictionary is deliberately plain so GUI dry-check/report code
    can preserve rejection reasons without depending on implementation classes.
    """
    score = reference_score(sample_meta, ref_meta, kind=kind)
    matched_fields = _matched_scientific_fields(sample_meta, ref_meta, kind=kind)
    reasons: list[str] = []

    sample_shape = sample_meta.get("shape")
    ref_shape = ref_meta.get("shape")
    if require_same_shape and sample_shape is not None and ref_shape != sample_shape:
        reasons.append("shape_mismatch")

    if len(matched_fields) < int(min_matched_fields):
        reasons.append("insufficient_matched_fields")

    if not np.isfinite(score) or score >= NO_USABLE_REFERENCE_SCORE:
        reasons.append("no_usable_score")
    elif max_score_threshold is not None and score > float(max_score_threshold):
        reasons.append("score_above_threshold")

    return {
        "path": str(ref_meta.get("path", "")),
        "score": score,
        "matched_fields": matched_fields,
        "matched_field_count": len(matched_fields),
        "required_matched_fields": int(min_matched_fields),
        "sample_shape": sample_shape,
        "ref_shape": ref_shape,
        "reasons": reasons,
        "accepted": not reasons,
        "reference": ref_meta,
    }


def select_best_reference(
    sample_meta: dict[str, Any],
    refs: list[dict[str, Any]],
    kind: str = "bg",
    *,
    max_score_threshold: float | None = DEFAULT_MAX_SCORE_THRESHOLD,
    require_same_shape: bool = True,
    min_matched_fields: int = DEFAULT_MIN_MATCHED_FIELDS,
    return_rejections: bool = False,
) -> tuple[dict[str, Any] | None, float | None] | tuple[
    dict[str, Any] | None,
    float | None,
    list[dict[str, Any]],
]:
    """Return (best_ref_dict, best_score) or (None, None) if no candidates."""
    if not refs:
        return (None, None, []) if return_rejections else (None, None)

    scored: list[tuple[float, dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    for ref_meta in refs:
        candidate = score_reference_candidate(
            sample_meta,
            ref_meta,
            kind=kind,
            max_score_threshold=max_score_threshold,
            require_same_shape=require_same_shape,
            min_matched_fields=min_matched_fields,
        )
        if candidate["accepted"]:
            scored.append((candidate["score"], ref_meta))
        else:
            candidate.pop("reference", None)
            rejected.append(candidate)

    if not scored:
        return (None, None, rejected) if return_rejections else (None, None)

    scored.sort(key=lambda x: x[0])
    best_score, best_ref = scored[0]
    return (best_ref, best_score, rejected) if return_rejections else (best_ref, best_score)
