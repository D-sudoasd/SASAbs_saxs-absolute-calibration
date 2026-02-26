"""Robust parsing of SAXS instrument headers and external 1-D profiles.

This module addresses two common reproducibility pain points:

1. **Header heterogeneity** – different instruments store exposure time,
   monitor counts, and transmission under varying key names and units.
   :func:`parse_header_values` normalizes keys and coerces values.

2. **1-D text-format diversity** – external 1-D files come in CSV, space-
   delimited, and semicolon-delimited flavours, sometimes without a header
   row.  :func:`read_external_1d_profile` tries several parsing strategies
   and infers column roles heuristically.

3. **Community standard formats** – canSAS 1D XML (``urn:cansas1d:1.1``)
   and NXcanSAS HDF5 files can be read via :func:`read_cansas1d_xml` and
   :func:`read_nxcansas_h5` respectively.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
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
    p = Path(path)
    ext = p.suffix.lower()

    # Route to specialized readers based on file extension
    if ext == ".xml":
        try:
            return read_cansas1d_xml(p)
        except Exception:
            pass  # fall through to generic text parser
    elif ext in (".h5", ".hdf5", ".hdf", ".nxs"):
        return read_nxcansas_h5(p)

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


# ---------------------------------------------------------------------------
# canSAS 1D XML reader  (urn:cansas1d:1.1)
# ---------------------------------------------------------------------------
_CANSAS_NS = "urn:cansas1d:1.1"


def read_cansas1d_xml(path: str | Path) -> dict[str, Any]:
    """Read a canSAS 1D XML file and return a profile dict.

    Returns the same ``{"x", "i_rel", "err_rel", ...}`` dict as
    :func:`read_external_1d_profile`.
    """
    p = Path(path)
    tree = ET.parse(str(p))
    root = tree.getroot()

    # Handle both namespaced and non-namespaced XML.
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    # Find SASdata → Idata elements
    q_vals: list[float] = []
    i_vals: list[float] = []
    e_vals: list[float] = []

    for idata in root.iter(f"{ns}Idata"):
        q_el = idata.find(f"{ns}Q")
        i_el = idata.find(f"{ns}I")
        if q_el is None or i_el is None:
            continue
        try:
            q_vals.append(float(q_el.text))
            i_vals.append(float(i_el.text))
        except (TypeError, ValueError):
            continue
        e_el = idata.find(f"{ns}Idev")
        if e_el is not None and e_el.text:
            try:
                e_vals.append(float(e_el.text))
            except (TypeError, ValueError):
                e_vals.append(np.nan)
        else:
            e_vals.append(np.nan)

    if len(q_vals) < 2:
        raise ValueError(f"canSAS XML contains too few data points: {p.name}")

    x = np.asarray(q_vals, dtype=np.float64)
    i_rel = np.asarray(i_vals, dtype=np.float64)
    err = np.asarray(e_vals, dtype=np.float64) if e_vals else np.full_like(x, np.nan)

    order = np.argsort(x)
    return {
        "x": x[order],
        "i_rel": i_rel[order],
        "err_rel": err[order],
        "x_col": "Q",
        "i_col": "I",
        "err_col": "Idev",
    }


# ---------------------------------------------------------------------------
# NXcanSAS HDF5 reader
# ---------------------------------------------------------------------------

def read_nxcansas_h5(path: str | Path) -> dict[str, Any]:
    """Read an NXcanSAS HDF5 file and return a profile dict.

    Requires the ``h5py`` package.  Returns the same dict format as
    :func:`read_external_1d_profile`.
    """
    try:
        import h5py
    except ImportError as exc:
        raise ImportError(
            "h5py is required for reading NXcanSAS files. "
            "Install it with:  pip install saxsabs[hdf5]"
        ) from exc

    p = Path(path)
    with h5py.File(str(p), "r") as f:
        # Walk groups to find the first SASdata containing Q and I datasets.
        q_ds = None
        i_ds = None
        e_ds = None

        def _find_sasdata(group: Any) -> bool:
            nonlocal q_ds, i_ds, e_ds
            cls = group.attrs.get("canSAS_class", "")
            if isinstance(cls, bytes):
                cls = cls.decode()
            if cls == "SASdata" or group.name.rsplit("/", 1)[-1].startswith("sasdata"):
                if "Q" in group and "I" in group:
                    q_ds = group["Q"][()]
                    i_ds = group["I"][()]
                    if "Idev" in group:
                        e_ds = group["Idev"][()]
                    return True
            for key in group:
                item = group[key]
                if hasattr(item, "keys"):  # is a group
                    if _find_sasdata(item):
                        return True
            return False

        _find_sasdata(f)

    if q_ds is None or i_ds is None:
        raise ValueError(f"Cannot find SASdata/Q,I datasets in {p.name}")

    x = np.asarray(q_ds, dtype=np.float64).ravel()
    i_rel = np.asarray(i_ds, dtype=np.float64).ravel()
    err = (
        np.asarray(e_ds, dtype=np.float64).ravel()
        if e_ds is not None
        else np.full_like(x, np.nan)
    )

    order = np.argsort(x)
    return {
        "x": x[order],
        "i_rel": i_rel[order],
        "err_rel": err[order],
        "x_col": "Q",
        "i_col": "I",
        "err_col": "Idev" if e_ds is not None else "",
    }
