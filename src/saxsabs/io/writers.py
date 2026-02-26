"""Export SAXS profiles in standard community formats.

Supported output formats:

* **canSAS 1D XML** — ``urn:cansas1d:1.1`` (no external dependencies)
* **NXcanSAS HDF5** — NeXus ``NXcanSAS`` application definition (requires h5py)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# canSAS 1D XML  (cansas1d:1.1)
# ---------------------------------------------------------------------------
_CANSAS_NS = "urn:cansas1d:1.1"
_CANSAS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_CANSAS_SCHEMA = (
    "urn:cansas1d:1.1 "
    "http://www.cansas.org/formats/canSAS1d/1.1/doc/cansas1d.xsd"
)


def write_cansas1d_xml(
    path: str | Path,
    q: np.ndarray,
    i_abs: np.ndarray,
    err: np.ndarray | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write a 1-D SAXS profile in canSAS 1D XML format.

    Parameters
    ----------
    path : str or Path
        Output file path (should end in ``.xml``).
    q : ndarray
        Momentum-transfer values (Å⁻¹).
    i_abs : ndarray
        Absolute intensity (cm⁻¹).
    err : ndarray or None
        Uncertainty (cm⁻¹).
    metadata : dict or None
        Optional keys: ``title``, ``run``, ``wavelength_A``, ``sdd_m``,
        ``sample_name``, ``instrument_name``, ``detector_name``,
        ``process_name``.

    Returns
    -------
    Path
        The written file path.
    """
    meta = metadata or {}
    out = Path(path)

    root = ET.Element("SASroot")
    root.set("version", "1.1")
    root.set("xmlns", _CANSAS_NS)
    root.set("xmlns:xsi", _CANSAS_XSI)
    root.set("xsi:schemaLocation", _CANSAS_SCHEMA)

    entry = ET.SubElement(root, "SASentry", name="entry01")
    ET.SubElement(entry, "Title").text = meta.get("title", "SAXS profile")
    ET.SubElement(entry, "Run").text = meta.get("run", "001")

    # --- SASdata ---
    sasdata = ET.SubElement(entry, "SASdata")
    q_arr = np.asarray(q, dtype=np.float64)
    i_arr = np.asarray(i_abs, dtype=np.float64)
    e_arr = np.asarray(err, dtype=np.float64) if err is not None else None

    for idx in range(q_arr.size):
        idata = ET.SubElement(sasdata, "Idata")
        qel = ET.SubElement(idata, "Q", unit="1/A")
        qel.text = f"{q_arr[idx]:.8g}"
        iel = ET.SubElement(idata, "I", unit="1/cm")
        iel.text = f"{i_arr[idx]:.8g}"
        if e_arr is not None and np.isfinite(e_arr[idx]):
            eel = ET.SubElement(idata, "Idev", unit="1/cm")
            eel.text = f"{e_arr[idx]:.8g}"

    # --- SASsample ---
    sassample = ET.SubElement(entry, "SASsample")
    ET.SubElement(sassample, "ID").text = meta.get("sample_name", "unknown")

    # --- SASinstrument ---
    sasinst = ET.SubElement(entry, "SASinstrument")
    ET.SubElement(sasinst, "name").text = meta.get("instrument_name", "")
    source = ET.SubElement(sasinst, "SASsource")
    ET.SubElement(source, "radiation").text = "x-ray"
    if "wavelength_A" in meta:
        wl = ET.SubElement(source, "wavelength", unit="A")
        wl.text = f"{meta['wavelength_A']:.6g}"
    ET.SubElement(sasinst, "SAScollimation")
    det = ET.SubElement(sasinst, "SASdetector")
    ET.SubElement(det, "name").text = meta.get("detector_name", "")
    if "sdd_m" in meta:
        sdd = ET.SubElement(det, "SDD", unit="m")
        sdd.text = f"{meta['sdd_m']:.4g}"

    # --- SASprocess ---
    sasproc = ET.SubElement(entry, "SASprocess")
    ET.SubElement(sasproc, "name").text = meta.get(
        "process_name", "SAXSAbs absolute calibration"
    )

    # Write
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out), xml_declaration=True, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# NXcanSAS HDF5
# ---------------------------------------------------------------------------
def write_nxcansas_h5(
    path: str | Path,
    q: np.ndarray,
    i_abs: np.ndarray,
    err: np.ndarray | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write a 1-D SAXS profile in NXcanSAS (NeXus HDF5) format.

    Requires the ``h5py`` package (``pip install saxsabs[hdf5]``).

    Parameters
    ----------
    path, q, i_abs, err, metadata
        Same as :func:`write_cansas1d_xml`.

    Returns
    -------
    Path
        The written file path.
    """
    try:
        import h5py
    except ImportError as exc:
        raise ImportError(
            "h5py is required for NXcanSAS output. "
            "Install it with:  pip install saxsabs[hdf5]"
        ) from exc

    meta = metadata or {}
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    q_arr = np.asarray(q, dtype=np.float64)
    i_arr = np.asarray(i_abs, dtype=np.float64)

    with h5py.File(str(out), "w") as f:
        entry = f.create_group("sasentry01")
        entry.attrs["NX_class"] = "NXentry"
        entry.attrs["canSAS_class"] = "SASentry"
        entry.attrs["version"] = "1.1"
        entry["definition"] = "NXcanSAS"
        entry["title"] = meta.get("title", "SAXS profile")
        entry["run"] = meta.get("run", "001")

        # SASdata
        data = entry.create_group("sasdata01")
        data.attrs["NX_class"] = "NXdata"
        data.attrs["canSAS_class"] = "SASdata"
        data.attrs["signal"] = "I"
        data.attrs["I_axes"] = "Q"
        data.attrs["Q_indices"] = 0

        ds_q = data.create_dataset("Q", data=q_arr)
        ds_q.attrs["units"] = "1/angstrom"

        ds_i = data.create_dataset("I", data=i_arr)
        ds_i.attrs["units"] = "1/cm"

        if err is not None:
            e_arr = np.asarray(err, dtype=np.float64)
            ds_e = data.create_dataset("Idev", data=e_arr)
            ds_e.attrs["units"] = "1/cm"

        # SASinstrument (minimal)
        inst = entry.create_group("sasinstrument01")
        inst.attrs["NX_class"] = "NXinstrument"
        inst.attrs["canSAS_class"] = "SASinstrument"
        if meta.get("instrument_name"):
            inst["name"] = meta["instrument_name"]

        src = inst.create_group("source01")
        src.attrs["NX_class"] = "NXsource"
        src["radiation"] = "x-ray"
        if "wavelength_A" in meta:
            ds_wl = src.create_dataset(
                "incident_wavelength", data=meta["wavelength_A"]
            )
            ds_wl.attrs["units"] = "angstrom"

        # SASsample
        sample = entry.create_group("sassample01")
        sample.attrs["NX_class"] = "NXsample"
        sample.attrs["canSAS_class"] = "SASsample"
        sample["name"] = meta.get("sample_name", "unknown")

    return out
