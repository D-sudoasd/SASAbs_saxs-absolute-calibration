from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FLOAT_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def norm_key(key: Any) -> str:
    if key is None:
        return ""
    s = str(key).strip().lower().replace(" ", "")
    s = s.replace("-", "").replace("_", "")
    return s


def extract_float(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")

    m = FLOAT_PATTERN.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def normalize_transmission(trans: float | None, raw: Any = None, key: Any = None) -> float | None:
    if trans is None:
        return None
    t = float(trans)
    raw_s = str(raw).strip().lower() if raw is not None else ""
    key_s = norm_key(key) if key is not None else ""

    has_pct_hint = (
        "%" in raw_s
        or "percent" in raw_s
        or "pct" in raw_s
        or "percent" in key_s
        or "pct" in key_s
    )

    if has_pct_hint:
        t /= 100.0
    elif 2.0 < t <= 100.0:
        t /= 100.0
    return t


def parse_header_values(header_mapping: dict[str, Any] | None) -> tuple[float | None, float | None, float | None]:
    meta: dict[str, str] = {}

    def add_meta(k: Any, v: Any) -> None:
        if k is None or v is None:
            return
        nk = norm_key(k)
        if nk:
            meta[nk] = str(v).strip()

    for k, v in (header_mapping or {}).items():
        add_meta(k, v)

    exp_keys = ["exposuretime", "counttime", "acqtime", "exposure", "time"]
    mon_keys = ["monitor", "beammonitor", "ionchamber", "mon", "i0", "flux"]
    trans_keys = ["sampletransmission", "transmission", "trans", "abs"]
    exp_exact_only = {"time"}
    mon_exact_only = {"mon", "i0"}
    trans_exact_only = {"abs"}

    def get_val(keys: list[str], exact_only: set[str] | None = None) -> tuple[str | None, str | None]:
        exact_only = set(exact_only or set())

        for k in keys:
            if k in meta:
                return meta[k], k

        for mk, mv in meta.items():
            for k in keys:
                if k in exact_only:
                    continue
                if mk.startswith(k) or mk.endswith(k):
                    return mv, mk

        for mk, mv in meta.items():
            for k in keys:
                if k in exact_only or len(k) < 6:
                    continue
                if k in mk:
                    return mv, mk

        return None, None

    exp_raw, exp_key = get_val(exp_keys, exp_exact_only)
    mon_raw, _ = get_val(mon_keys, mon_exact_only)
    trans_raw, trans_key = get_val(trans_keys, trans_exact_only)

    exp = extract_float(exp_raw)
    mon = extract_float(mon_raw)
    trans = extract_float(trans_raw)

    if exp is not None:
        exp_tag = f"{exp_key or ''} {exp_raw or ''}".lower()
        if "ms" in exp_tag:
            exp /= 1000.0
        elif "us" in exp_tag:
            exp /= 1_000_000.0

    trans = normalize_transmission(trans, raw=trans_raw, key=trans_key)
    return exp, mon, trans


def read_external_1d_profile(path: str | Path) -> dict[str, Any]:
    dfs: list[pd.DataFrame] = []
    errs: list[str] = []

    read_trials: list[dict[str, Any]] = [
        {"sep": None, "engine": "python", "comment": "#"},
        {"sep": r"[,\s;]+", "engine": "python", "comment": "#"},
        {"sep": r"[,\s;]+", "engine": "python", "comment": "#", "header": None},
    ]

    for kw in read_trials:
        try:
            df = pd.read_csv(path, **kw)
            if df is not None and not df.empty and df.shape[1] >= 2:
                dfs.append(df)
        except Exception as exc:
            errs.append(str(exc))

    if not dfs:
        raise ValueError(f"Cannot parse file: {Path(path).name} ({'; '.join(errs[:2])})")

    best: dict[str, Any] | None = None
    best_pts = -1

    for df in dfs:
        numeric_cols: dict[Any, pd.Series] = {}
        for col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce")
            arr = s.to_numpy(dtype=np.float64, na_value=np.nan)
            cnt = int(np.isfinite(arr).sum())
            if cnt >= 3:
                numeric_cols[col] = s

        if len(numeric_cols) < 2:
            continue

        cols = list(numeric_cols.keys())

        def pick(tokens: list[str], used: set[Any]) -> Any:
            for c in cols:
                if c in used:
                    continue
                name = str(c).strip().lower().replace("_", "").replace(" ", "")
                if any(t in name for t in tokens):
                    return c
            return None

        x_col = pick(["q", "chi", "radial", "2theta", "x"], set()) or cols[0]
        i_col = pick(["intensity", "irel", "iabs", "signal", "count", "i"], {x_col})
        if i_col is None:
            i_col = next((c for c in cols if c != x_col), None)
        if i_col is None:
            continue

        err_col = pick(["error", "sigma", "std", "unc"], {x_col, i_col})
        if err_col is None and len(cols) >= 3:
            err_col = next((c for c in cols if c not in {x_col, i_col}), None)

        x = pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
        i_rel = pd.to_numeric(df[i_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
        mask = np.isfinite(x) & np.isfinite(i_rel)
        if int(mask.sum()) < 3:
            continue

        x = x[mask]
        i_rel = i_rel[mask]

        if err_col is not None:
            err = pd.to_numeric(df[err_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)[mask]
            err = np.where(np.isfinite(err), err, np.nan)
        else:
            err = np.full_like(i_rel, np.nan, dtype=np.float64)

        order = np.argsort(x)
        x = x[order]
        i_rel = i_rel[order]
        err = err[order]

        pts = int(x.size)
        if pts > best_pts:
            best_pts = pts
            best = {
                "x": x,
                "i_rel": i_rel,
                "err_rel": err,
                "x_col": str(x_col),
                "i_col": str(i_col),
                "err_col": str(err_col) if err_col is not None else "",
            }

    if best is None:
        raise ValueError(f"Cannot identify valid numeric columns in {Path(path).name}")
    return best
