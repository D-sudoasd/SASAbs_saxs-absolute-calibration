"""BL19B2 detector-space absolute 2D batch correction workflow.

This module is intentionally separate from the GUI.  It implements a
configuration-driven batch path for the Spring-8 BL19B2 TIFF layout used in
``dat001`` while preserving the original data tree as read-only input.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import importlib.metadata as importlib_metadata
import json
import math
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saxsabs.core.calibration import estimate_k_factor_robust
from saxsabs.constants import get_reference_data


SCHEMA_VERSION = "saxsabs.bl19b2_abs2d.v2"
FORMULA_VERSION = "v2_dark_exposure_matched"
INTENSITY_UNIT = "cm^-1"
EXCLUDED_SAMPLE_PARTS = {"reference_saxs", "csv_output", "sum", "test"}
EXCLUDED_PREFIXES = ("processed_",)


@dataclass(frozen=True)
class BL19B2Header:
    exposure_s: float | None = None
    monitor: float | None = None
    transmission: float | None = None
    energy_kev: float | None = None
    distance_mm: float | None = None
    beam_x_px: float | None = None
    beam_y_px: float | None = None
    pixel_size_m: float | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FrameClassification:
    status: str
    reason: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputPaths:
    h5: Path
    edf: Path
    metadata: Path
    preview: Path


@dataclass(frozen=True)
class ReferencePaths:
    dark: Path
    background: Path
    standard: Path
    direct: Path | None = None
    mask: Path | None = None


@dataclass(frozen=True)
class PydidasCalibration:
    source_path: Path
    detector_name: str
    distance_m: float
    poni1_m: float
    poni2_m: float
    pixel1_m: float
    pixel2_m: float
    rot1: float
    rot2: float
    rot3: float
    wavelength_m: float
    mask_path: Path | None = None


@dataclass(frozen=True)
class BL19B2Abs2DConfig:
    input_root: Path
    poni_path: Path | None = None
    pydidas_cali_yaml: Path | None = None
    mask_path: Path | None = None
    output_root: Path | None = None
    mu_cm_inv: float = 20.2
    alpha: float = 1.0
    q_window: tuple[float, float] = (0.01, 0.2)
    npt: int = 1000
    dtype: str = "float32"
    dry_run: bool = False
    max_frames: int | None = None
    overwrite: bool = False
    write_preview: bool = True
    standard_thickness_cm: float | None = None
    standard_key: str = "SRM3600"
    correct_solid_angle_for_k: bool = True
    polarization_factor: float | None = None
    dark_hot_pixel_threshold: float = 10.0

    def resolved_output_root(self) -> Path:
        if self.output_root is not None:
            return Path(self.output_root)
        return Path(self.input_root).parent / f"{Path(self.input_root).name}_absolute_corrected_2D"


@dataclass(frozen=True)
class StandardCalibration:
    k_factor: float
    k_std: float
    q_min_overlap: float
    q_max_overlap: float
    points_used: int
    points_total: int
    standard_thickness_cm: float
    norm_standard: float
    norm_background: float
    bg_transmission_used: float
    standard_thickness_source: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MaskInfo:
    mask: np.ndarray
    npy_path: Path
    edf_path: Path
    checksum_sha256: str
    user_mask_path: Path | None
    user_mask_pixels: int
    detector_mask_pixels: int
    dark_hot_pixels: int
    combined_mask_pixels: int
    dark_hot_pixel_threshold: float


@dataclass(frozen=True)
class ProvenancePaths:
    run_command: Path
    processing_environment: Path
    code_state: Path
    provenance_summary: Path


_FIELD_RE = re.compile(
    r"#\s*([^=#:\r\n]+?)\s*(?:=|:)\s*([^#\r\n]+)"
    r"|#\s*(Exposure_time|Exposure_period|Pixel_size)\s+([^#\r\n]+)",
    re.IGNORECASE,
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _parse_float(raw: Any) -> float | None:
    if raw is None:
        return None
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(raw))
    if match is None:
        return None
    try:
        value = float(match.group(0))
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _parse_required_float(fields: dict[str, str], key: str, path: Path) -> float:
    value = _parse_float(fields.get(key))
    if value is None:
        raise ValueError(f"{path} missing numeric {key}")
    return value


def _parse_required_positive_float(fields: dict[str, str], key: str, path: Path) -> float:
    value = _parse_required_float(fields, key, path)
    if value <= 0:
        raise ValueError(f"{path} {key} must be finite and > 0")
    return value


def _norm_key(key: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(key).upper())


def _read_flat_yaml(path: str | Path) -> dict[str, str]:
    yaml_path = Path(path)
    fields: dict[str, str] = {}
    for raw_line in yaml_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("'\"")
    return fields


def _resolve_yaml_path(raw: str | None, yaml_path: Path) -> Path | None:
    if raw is None:
        return None
    raw_text = str(raw).strip().strip("'\"")
    if not raw_text or raw_text == "." or raw_text.lower() in {"none", "null"}:
        return None
    path = Path(raw_text)
    if path.is_absolute():
        return path
    return yaml_path.parent / path


def parse_pydidas_cali_yaml(path: str | Path) -> PydidasCalibration:
    """Parse a flat pydidas calibration YAML file and convert units for pyFAI PONI."""
    yaml_path = Path(path)
    fields = _read_flat_yaml(yaml_path)
    distance_m = _parse_required_positive_float(fields, "detector_dist", yaml_path)
    pixel_x_um = _parse_required_positive_float(fields, "detector_pxsizex", yaml_path)
    pixel_y_um = _parse_required_positive_float(fields, "detector_pxsizey", yaml_path)
    wavelength_angstrom = _parse_required_positive_float(fields, "xray_wavelength", yaml_path)
    return PydidasCalibration(
        source_path=yaml_path,
        detector_name=fields.get("detector_name", "Pilatus 2M"),
        distance_m=distance_m,
        poni1_m=_parse_required_float(fields, "detector_poni1", yaml_path),
        poni2_m=_parse_required_float(fields, "detector_poni2", yaml_path),
        pixel1_m=round(pixel_y_um * 1e-6, 12),
        pixel2_m=round(pixel_x_um * 1e-6, 12),
        rot1=_parse_float(fields.get("detector_rot1")) or 0.0,
        rot2=_parse_float(fields.get("detector_rot2")) or 0.0,
        rot3=_parse_float(fields.get("detector_rot3")) or 0.0,
        wavelength_m=round(wavelength_angstrom * 1e-10, 23),
        mask_path=_resolve_yaml_path(fields.get("detector_mask_file"), yaml_path),
    )


def _poni_detector_name(detector_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "", detector_name)
    if normalized.lower() == "pilatus2m":
        return "Pilatus2M"
    return normalized or "Pilatus2M"


def write_pydidas_poni(cali_yaml: str | Path, poni_path: str | Path) -> Path:
    """Write a pyFAI PONI file from pydidas calibration YAML."""
    geometry = parse_pydidas_cali_yaml(cali_yaml)
    detector_config = {"pixel1": geometry.pixel1_m, "pixel2": geometry.pixel2_m}
    target = Path(poni_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "# Nota: C-Order, 1 refers to the Y axis, 2 to the X axis",
            f"# Calibration imported from {geometry.source_path}",
            "poni_version: 2",
            f"Detector: {_poni_detector_name(geometry.detector_name)}",
            f"Detector_config: {json.dumps(detector_config)}",
            f"Distance: {geometry.distance_m:.17g}",
            f"Poni1: {geometry.poni1_m:.17g}",
            f"Poni2: {geometry.poni2_m:.17g}",
            f"Rot1: {geometry.rot1:.17g}",
            f"Rot2: {geometry.rot2:.17g}",
            f"Rot3: {geometry.rot3:.17g}",
            f"Wavelength: {geometry.wavelength_m:.12g}",
            "",
            "# This file was generated by SAXSAbs from pydidas Cali.yaml.",
            "",
        ]
    )
    target.write_text(text, encoding="utf-8")
    return target


def parse_bl19b2_description(description: str) -> BL19B2Header:
    """Parse BL19B2 Pilatus TIFF ImageDescription text."""
    text = str(description or "").replace("\x00", "\n").replace("\r", "\n")
    fields: dict[str, str] = {}
    for match in _FIELD_RE.finditer(text):
        if match.group(1):
            key = match.group(1).strip()
            value = match.group(2).strip()
        else:
            key = match.group(3).strip()
            value = match.group(4).strip()
        fields[_norm_key(key)] = value

    return BL19B2Header(
        exposure_s=_parse_float(fields.get("EXPOSURETIME")),
        monitor=_parse_float(fields.get("MON")),
        transmission=_parse_float(fields.get("ABS")),
        energy_kev=_parse_float(fields.get("E0")),
        distance_mm=_parse_float(fields.get("CAML")),
        beam_x_px=_parse_float(fields.get("DRTX")),
        beam_y_px=_parse_float(fields.get("DRTY")),
        pixel_size_m=_parse_float(fields.get("PIXELSIZE")),
        raw_fields=fields,
    )


def read_tiff_header(path: str | Path) -> BL19B2Header:
    """Read BL19B2 header fields from a TIFF file without loading all pixels."""
    try:
        import tifffile
    except ImportError as exc:  # pragma: no cover
        raise ImportError("tifffile is required for BL19B2 TIFF header scanning") from exc

    with tifffile.TiffFile(str(path)) as tif:
        page = tif.pages[0]
        tag = page.tags.get("ImageDescription")
        description = "" if tag is None else str(tag.value)
    return parse_bl19b2_description(description)


def _is_finite_positive(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value)) and float(value) > 0


def classify_sample_frame(header: BL19B2Header) -> FrameClassification:
    """Return whether a sample frame has enough metadata for cm^-1 output."""
    missing: list[str] = []
    if not _is_finite_positive(header.exposure_s):
        missing.append("Exposure_time")
    if not _is_finite_positive(header.monitor):
        missing.append("MON")
    if not _is_finite_positive(header.transmission):
        missing.append("ABS/transmission")
    if missing:
        return FrameClassification("rejected", "missing or invalid " + ", ".join(missing))

    assert header.transmission is not None
    if header.transmission > 1.0:
        return FrameClassification(
            "rejected",
            f"transmission ABS must be <= 1 for sample frames, got {header.transmission:.6g}",
        )
    if header.transmission >= 1.0:
        return FrameClassification(
            "rejected",
            "transmission ABS must be < 1 for Beer-Lambert thickness estimation",
        )
    return FrameClassification("ok")


def estimate_thickness_cm(transmission: float, mu_cm_inv: float = 20.2) -> np.float64:
    """Estimate thickness from Beer-Lambert law: d = -ln(T) / mu."""
    t = float(transmission)
    mu = float(mu_cm_inv)
    if not math.isfinite(t) or t <= 0 or t >= 1:
        raise ValueError(f"transmission must satisfy 0 < T < 1, got {transmission!r}")
    if not math.isfinite(mu) or mu <= 0:
        raise ValueError(f"mu_cm_inv must be finite and > 0, got {mu_cm_inv!r}")
    return np.float64(-math.log(t) / mu)


def compute_norm_factor(exposure_s: float, monitor: float, transmission: float) -> float:
    """Compute BL19B2 rate-mode normalization exp * MON * T."""
    exp_v = float(exposure_s)
    mon_v = float(monitor)
    trans_v = float(transmission)
    if not all(math.isfinite(v) and v > 0 for v in (exp_v, mon_v, trans_v)):
        raise ValueError("exposure_s, monitor, and transmission must be finite and > 0")
    return exp_v * mon_v * trans_v


def validate_config(config: BL19B2Abs2DConfig) -> None:
    if (config.poni_path is None) == (config.pydidas_cali_yaml is None):
        raise ValueError("provide exactly one of poni_path or pydidas_cali_yaml")
    if not math.isfinite(float(config.mu_cm_inv)) or float(config.mu_cm_inv) <= 0:
        raise ValueError("mu_cm_inv must be finite and > 0")
    if not math.isfinite(float(config.alpha)):
        raise ValueError("alpha must be finite")
    if config.standard_thickness_cm is not None:
        thickness = float(config.standard_thickness_cm)
        if not math.isfinite(thickness) or thickness <= 0:
            raise ValueError("standard_thickness_cm must be finite and > 0")
    q_lo, q_hi = config.q_window
    if not (math.isfinite(float(q_lo)) and math.isfinite(float(q_hi)) and q_lo < q_hi):
        raise ValueError("q_window must contain finite increasing values")
    if int(config.npt) <= 0:
        raise ValueError("npt must be > 0")
    if not math.isfinite(float(config.dark_hot_pixel_threshold)) or config.dark_hot_pixel_threshold < 0:
        raise ValueError("dark_hot_pixel_threshold must be finite and >= 0")


def subtract_dark_for_exposure(
    image: np.ndarray,
    dark: np.ndarray,
    *,
    image_exposure_s: float,
    dark_exposure_s: float,
) -> np.ndarray:
    """Subtract a dark image after scaling it to the image exposure time."""
    img = np.asarray(image, dtype=np.float64)
    dark_arr = np.asarray(dark, dtype=np.float64)
    if img.shape != dark_arr.shape:
        raise ValueError(f"dark shape mismatch: {dark_arr.shape} vs {img.shape}")
    exp_v = float(image_exposure_s)
    dark_exp_v = float(dark_exposure_s)
    if not (math.isfinite(exp_v) and exp_v > 0):
        raise ValueError("image_exposure_s must be finite and > 0")
    if not (math.isfinite(dark_exp_v) and dark_exp_v > 0):
        raise ValueError("dark_exposure_s must be finite and > 0")
    return img - dark_arr * (exp_v / dark_exp_v)


def normalize_dark_corrected_image(
    image: np.ndarray,
    dark: np.ndarray,
    *,
    image_exposure_s: float,
    dark_exposure_s: float,
    monitor: float,
    transmission: float,
) -> tuple[np.ndarray, float]:
    corrected = subtract_dark_for_exposure(
        image,
        dark,
        image_exposure_s=image_exposure_s,
        dark_exposure_s=dark_exposure_s,
    )
    norm = compute_norm_factor(image_exposure_s, monitor, transmission)
    return corrected / norm, norm


def natural_key(path: str | Path) -> list[Any]:
    text = str(path)
    parts = re.split(r"(\d+)", text)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def is_sample_tiff(path: str | Path, input_root: str | Path) -> bool:
    p = Path(path)
    if p.suffix.lower() not in (".tif", ".tiff"):
        return False
    try:
        rel = p.relative_to(Path(input_root))
    except ValueError:
        rel = p
    parts = [part.lower() for part in rel.parts[:-1]]
    if any(part in EXCLUDED_SAMPLE_PARTS for part in parts):
        return False
    return not any(part.startswith(EXCLUDED_PREFIXES) for part in parts)


def build_output_paths(source: str | Path, *, input_root: str | Path, output_root: str | Path) -> OutputPaths:
    source_path = Path(source)
    root = Path(input_root)
    out = Path(output_root)
    rel_parent = source_path.parent.relative_to(root)
    stem = source_path.stem
    return OutputPaths(
        h5=out / "images_h5" / rel_parent / f"{stem}_abs2d_cm-1.h5",
        edf=out / "images_edf" / rel_parent / f"{stem}_abs2d_cm-1.edf",
        metadata=out / "metadata" / rel_parent / f"{stem}_abs2d.json",
        preview=out / "previews" / rel_parent / f"{stem}_preview.png",
    )


def _resolve_mask_path(
    ref: Path,
    *,
    mask_path: str | Path | None = None,
    pydidas_cali_yaml: str | Path | None = None,
) -> Path | None:
    if mask_path is not None:
        explicit = Path(mask_path)
        if not explicit.is_file():
            raise FileNotFoundError(f"explicit BL19B2 mask must be a file: {explicit}")
        return explicit
    if pydidas_cali_yaml is not None:
        yaml_path = Path(pydidas_cali_yaml)
        fields = _read_flat_yaml(yaml_path)
        yaml_mask = _resolve_yaml_path(fields.get("detector_mask_file"), yaml_path)
        if yaml_mask is not None and yaml_mask.is_file():
            return yaml_mask
    for name in ("MASK_file.edf", "Mask.edf", "mask.edf"):
        candidate = ref / name
        if candidate.is_file():
            return candidate
    return None


def find_reference_paths(
    input_root: str | Path,
    *,
    mask_path: str | Path | None = None,
    pydidas_cali_yaml: str | Path | None = None,
) -> ReferencePaths:
    ref = Path(input_root) / "reference_saxs"
    paths = ReferencePaths(
        dark=ref / "dark001.tif",
        background=ref / "BG001.tif",
        standard=ref / "GC001.tif",
        direct=ref / "drt001.tif",
        mask=_resolve_mask_path(ref, mask_path=mask_path, pydidas_cali_yaml=pydidas_cali_yaml),
    )
    missing = [
        str(path)
        for path in (paths.dark, paths.background, paths.standard)
        if not Path(path).exists()
    ]
    if missing:
        raise FileNotFoundError("Missing required BL19B2 reference file(s): " + "; ".join(missing))
    return paths


def read_detector_image(path: str | Path) -> np.ndarray:
    """Read a detector image using fabio and return float64 pixels."""
    try:
        import fabio
    except ImportError as exc:  # pragma: no cover
        raise ImportError("fabio is required for BL19B2 detector image reading") from exc
    return np.asarray(fabio.open(str(path)).data, dtype=np.float64)


def build_combined_mask(
    detector_mask: np.ndarray | None,
    user_mask: np.ndarray | None,
    dark: np.ndarray,
    *,
    dark_hot_pixel_threshold: float = 10.0,
) -> tuple[np.ndarray, dict[str, int]]:
    dark_arr = np.asarray(dark, dtype=np.float64)
    if detector_mask is None:
        det_mask = np.zeros(dark_arr.shape, dtype=bool)
    else:
        det_mask = np.asarray(detector_mask) != 0
        if det_mask.shape != dark_arr.shape:
            raise ValueError(f"detector mask shape mismatch: {det_mask.shape} vs {dark_arr.shape}")
    if user_mask is None:
        usr_mask = np.zeros(dark_arr.shape, dtype=bool)
    else:
        usr_mask = np.asarray(user_mask) != 0
        if usr_mask.shape != dark_arr.shape:
            raise ValueError(f"user mask shape mismatch: {usr_mask.shape} vs {dark_arr.shape}")
    hot_threshold = float(dark_hot_pixel_threshold)
    if not math.isfinite(hot_threshold) or hot_threshold < 0:
        raise ValueError("dark_hot_pixel_threshold must be finite and >= 0")
    dark_hot = np.abs(dark_arr) > hot_threshold
    combined = (usr_mask | det_mask | dark_hot).astype(np.uint8)
    return combined, {
        "user_mask_pixels": int(np.count_nonzero(usr_mask)),
        "detector_mask_pixels": int(np.count_nonzero(det_mask)),
        "dark_hot_pixels": int(np.count_nonzero(dark_hot)),
        "combined_mask_pixels": int(np.count_nonzero(combined)),
    }


def _mask_checksum(mask: np.ndarray) -> str:
    arr = np.asarray(mask, dtype=np.uint8)
    h = hashlib.sha256()
    h.update(str(arr.shape).encode("ascii"))
    h.update(arr.tobytes(order="C"))
    return h.hexdigest()


def _file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_edf_array(path: Path, data: np.ndarray, header: dict[str, str] | None = None) -> None:
    try:
        from fabio.edfimage import EdfImage
    except ImportError as exc:  # pragma: no cover
        raise ImportError("fabio is required for BL19B2 EDF output") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    EdfImage(data=data, header=header or {}).write(str(path))


def load_and_write_mask(
    *,
    safe_poni_path: Path,
    dark: np.ndarray,
    reference_paths: ReferencePaths,
    config: BL19B2Abs2DConfig,
) -> MaskInfo:
    try:
        import pyFAI
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pyFAI is required for BL19B2 mask export") from exc

    ai = pyFAI.load(str(safe_poni_path))
    detector_mask = getattr(ai.detector, "mask", None)
    user_mask: np.ndarray | None = None
    user_mask_path: Path | None = None
    if reference_paths.mask is not None and reference_paths.mask.is_file():
        user_mask_path = reference_paths.mask
        user_mask = read_detector_image(user_mask_path)
    mask, counts = build_combined_mask(
        detector_mask,
        user_mask,
        dark,
        dark_hot_pixel_threshold=config.dark_hot_pixel_threshold,
    )
    out_root = config.resolved_output_root()
    npy_path = out_root / "masks" / "bl19b2_mask.npy"
    edf_path = out_root / "masks" / "bl19b2_mask.edf"
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(npy_path, mask)
    _write_edf_array(
        edf_path,
        mask,
        header={
            "SAXSAbsSchema": SCHEMA_VERSION,
            "MaskConvention": "pyFAI: 0=valid, 1=masked",
            "MaskSources": "user mask + pyFAI detector mask + abs(dark) > threshold",
            "DarkHotPixelThreshold": f"{float(config.dark_hot_pixel_threshold):.10g}",
        },
    )
    return MaskInfo(
        mask=mask,
        npy_path=npy_path,
        edf_path=edf_path,
        checksum_sha256=_mask_checksum(mask),
        user_mask_path=user_mask_path,
        user_mask_pixels=counts["user_mask_pixels"],
        detector_mask_pixels=counts["detector_mask_pixels"],
        dark_hot_pixels=counts["dark_hot_pixels"],
        combined_mask_pixels=counts["combined_mask_pixels"],
        dark_hot_pixel_threshold=float(config.dark_hot_pixel_threshold),
    )


def build_processing_signature(
    config: BL19B2Abs2DConfig,
    *,
    mask_info: MaskInfo,
    standard_thickness_source: str,
    safe_poni_path: Path,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "schema": SCHEMA_VERSION,
        "formula_version": FORMULA_VERSION,
        "geometry_source": "pydidas_cali_yaml" if config.pydidas_cali_yaml is not None else "poni",
        "safe_poni_checksum_sha256": _file_sha256(safe_poni_path),
        "normalization_formula": "exposure_s * MON * ABS",
        "dark_scaling": "exposure_matched",
        "mu_cm_inv": float(config.mu_cm_inv),
        "alpha": float(config.alpha),
        "q_window": [float(config.q_window[0]), float(config.q_window[1])],
        "npt": int(config.npt),
        "standard_key": config.standard_key,
        "standard_thickness_source": standard_thickness_source,
        "correct_solid_angle_for_k": bool(config.correct_solid_angle_for_k),
        "polarization_factor": config.polarization_factor,
        "mask_checksum_sha256": mask_info.checksum_sha256,
        "dark_hot_pixel_threshold": float(config.dark_hot_pixel_threshold),
    }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), payload


def _provenance_paths(out_root: Path) -> ProvenancePaths:
    config_dir = out_root / "config"
    return ProvenancePaths(
        run_command=config_dir / "run_command.ps1",
        processing_environment=config_dir / "processing_environment.json",
        code_state=config_dir / "code_state.txt",
        provenance_summary=config_dir / "provenance_summary.json",
    )


def _package_version(distribution_name: str) -> str | None:
    try:
        return importlib_metadata.version(distribution_name)
    except importlib_metadata.PackageNotFoundError:
        return None


def collect_software_versions() -> dict[str, Any]:
    try:
        import saxsabs

        saxsabs_version = getattr(saxsabs, "__version__", None)
    except Exception:
        saxsabs_version = _package_version("saxsabs")
    packages = {
        "saxsabs": saxsabs_version,
        "numpy": np.__version__,
        "pyFAI": _package_version("pyFAI"),
        "fabio": _package_version("fabio"),
        "h5py": _package_version("h5py"),
        "tifffile": _package_version("tifffile"),
        "matplotlib": _package_version("matplotlib"),
    }
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
    }


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git_output(args: list[str], cwd: Path, *, timeout_s: int = 30) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except Exception as exc:
        return f"<git command failed: {exc}>"
    text = (result.stdout or "").strip()
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        return text or f"<git {' '.join(args)} failed: {err}>"
    return text


def collect_code_state(repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _default_repo_root()
    if not (root / ".git").exists():
        return {
            "repo_root": str(root),
            "available": False,
            "status": "unknown",
            "reason": ".git directory not found",
        }
    status_short = _git_output(["status", "--short"], root)
    dirty = bool(status_short.strip())
    untracked_files = _git_output(["ls-files", "--others", "--exclude-standard"], root) if dirty else ""
    untracked_snapshots: list[dict[str, str]] = []
    for rel_path in [line.strip() for line in untracked_files.splitlines() if line.strip()]:
        candidate = root / rel_path
        if candidate.suffix.lower() not in (".py", ".md", ".yml", ".yaml", ".toml", ".txt"):
            continue
        try:
            if candidate.is_file() and candidate.stat().st_size <= 256_000:
                untracked_snapshots.append(
                    {
                        "path": rel_path,
                        "content": candidate.read_text(encoding="utf-8", errors="replace"),
                    }
                )
        except OSError:
            continue
    return {
        "repo_root": str(root),
        "available": True,
        "branch": _git_output(["branch", "--show-current"], root),
        "commit": _git_output(["rev-parse", "HEAD"], root),
        "status": "dirty" if dirty else "clean",
        "status_short": status_short,
        "diff_stat": _git_output(["diff", "--stat"], root) if dirty else "",
        "diff": _git_output(["diff"], root, timeout_s=120) if dirty else "",
        "untracked_files": untracked_files,
        "untracked_file_snapshots": untracked_snapshots,
    }


def format_code_state_text(code_state: dict[str, Any]) -> str:
    lines = [
        "# SAXSAbs code state",
        f"generated_at: {_dt.datetime.now().isoformat(timespec='seconds')}",
        f"repo_root: {code_state.get('repo_root', '')}",
        f"available: {code_state.get('available', '')}",
        f"branch: {code_state.get('branch', '')}",
        f"commit: {code_state.get('commit', '')}",
        f"status: {code_state.get('status', '')}",
        "",
        "## git status --short",
        str(code_state.get("status_short", "")),
        "",
        "## git diff --stat",
        str(code_state.get("diff_stat", "")),
        "",
        "## untracked files",
        str(code_state.get("untracked_files", "")),
        "",
        "## git diff",
        str(code_state.get("diff", "")),
        "",
        "## untracked file snapshots",
    ]
    for item in code_state.get("untracked_file_snapshots", []) or []:
        lines.extend(
            [
                f"### {item.get('path', '')}",
                "```",
                str(item.get("content", "")),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _ps_single_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _optional_path_text(value: str | Path | None) -> str:
    return "" if value is None else str(Path(value))


def build_rerun_command(config: BL19B2Abs2DConfig, *, poni_path: Path | None = None) -> str:
    qmin, qmax = config.q_window
    lines = [
        "$env:PYTHONPATH='src'",
        f"& {_ps_single_quote(sys.executable)} -m saxsabs.cli bl19b2-abs2d `",
        f"  --input-root {_ps_single_quote(Path(config.input_root))} `",
    ]
    if config.pydidas_cali_yaml is not None:
        lines.append(f"  --pydidas-cali-yaml {_ps_single_quote(Path(config.pydidas_cali_yaml))} `")
        if config.mask_path is not None:
            lines.append(f"  --mask {_ps_single_quote(Path(config.mask_path))} `")
    else:
        source_poni = Path(poni_path) if poni_path is not None else Path(config.poni_path)
        lines.append(f"  --poni {_ps_single_quote(source_poni)} `")
    lines.extend(
        [
            f"  --output-root {_ps_single_quote(config.resolved_output_root())} `",
            f"  --mu {float(config.mu_cm_inv):.10g} `",
            f"  --alpha {float(config.alpha):.10g} `",
            f"  --qmin {float(qmin):.10g} `",
            f"  --qmax {float(qmax):.10g} `",
            f"  --npt {int(config.npt)} `",
            f"  --dtype {config.dtype} `",
            f"  --dark-hot-pixel-threshold {float(config.dark_hot_pixel_threshold):.10g}",
        ]
    )
    if config.standard_thickness_cm is not None:
        lines[-1] += " `"
        lines.append(f"  --standard-thickness-cm {float(config.standard_thickness_cm):.10g}")
    return "\n".join(lines) + "\n"


def write_provenance_package(
    *,
    config: BL19B2Abs2DConfig,
    safe_poni_path: Path,
    reference_paths: ReferencePaths,
    mask_info: MaskInfo,
    calibration: StandardCalibration,
    processing_signature: str,
    signature_payload: dict[str, Any],
    counts: dict[str, int],
    software_versions: dict[str, Any],
    code_state: dict[str, Any],
    run_status: str,
) -> ProvenancePaths:
    out_root = config.resolved_output_root()
    paths = _provenance_paths(out_root)
    paths.run_command.parent.mkdir(parents=True, exist_ok=True)
    paths.run_command.write_text(build_rerun_command(config, poni_path=safe_poni_path), encoding="utf-8")
    _write_json(paths.processing_environment, software_versions)
    paths.code_state.write_text(format_code_state_text(code_state), encoding="utf-8")
    summary = {
        "schema": SCHEMA_VERSION,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "run_status": run_status,
        "input_root": str(Path(config.input_root)),
        "output_root": str(out_root),
        "source_poni_path": _optional_path_text(config.poni_path),
        "pydidas_cali_yaml": _optional_path_text(config.pydidas_cali_yaml),
        "safe_poni_path": str(safe_poni_path),
        "references": {
            "dark": str(reference_paths.dark),
            "background": str(reference_paths.background),
            "standard": str(reference_paths.standard),
            "direct": str(reference_paths.direct or ""),
            "user_mask": str(reference_paths.mask or ""),
        },
        "mask": {
            "npy": str(mask_info.npy_path),
            "edf": str(mask_info.edf_path),
            "checksum_sha256": mask_info.checksum_sha256,
            "user_mask_pixels": mask_info.user_mask_pixels,
            "detector_mask_pixels": mask_info.detector_mask_pixels,
            "dark_hot_pixels": mask_info.dark_hot_pixels,
            "combined_mask_pixels": mask_info.combined_mask_pixels,
        },
        "processing_signature": processing_signature,
        "processing_signature_payload": signature_payload,
        "standard_calibration": {
            "k_factor": calibration.k_factor,
            "k_std": calibration.k_std,
            "q_min_overlap": calibration.q_min_overlap,
            "q_max_overlap": calibration.q_max_overlap,
            "points_used": calibration.points_used,
            "points_total": calibration.points_total,
            "standard_thickness_cm": calibration.standard_thickness_cm,
            "standard_thickness_source": calibration.standard_thickness_source,
        },
        "counts": dict(counts),
        "software_versions": software_versions,
        "code_state": {
            "status": code_state.get("status"),
            "branch": code_state.get("branch"),
            "commit": code_state.get("commit"),
            "repo_root": code_state.get("repo_root"),
            "details": str(paths.code_state),
        },
        "files": {
            "run_command": str(paths.run_command),
            "processing_environment": str(paths.processing_environment),
            "code_state": str(paths.code_state),
            "provenance_summary": str(paths.provenance_summary),
        },
    }
    _write_json(paths.provenance_summary, summary)
    return paths


def build_provenance_metadata(
    *,
    provenance_paths: ProvenancePaths,
    software_versions: dict[str, Any],
    code_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "software_versions": software_versions,
        "code_state_ref": str(provenance_paths.code_state),
        "code_state_status": code_state.get("status", "unknown"),
        "provenance": {
            "run_command": str(provenance_paths.run_command),
            "processing_environment": str(provenance_paths.processing_environment),
            "code_state": str(provenance_paths.code_state),
            "provenance_summary": str(provenance_paths.provenance_summary),
        },
    }


def update_metadata_provenance(
    metadata_path: Path,
    *,
    provenance_paths: ProvenancePaths,
    software_versions: dict[str, Any],
    code_state: dict[str, Any],
) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        build_provenance_metadata(
            provenance_paths=provenance_paths,
            software_versions=software_versions,
            code_state=code_state,
        )
    )
    _write_json(metadata_path, metadata)


def _copy_poni_to_safe_path(config: BL19B2Abs2DConfig) -> Path:
    out_root = config.resolved_output_root()
    target_dir = out_root / "config" / "geometry"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "BL19B2_SAXS_Califile.poni"
    if config.pydidas_cali_yaml is not None:
        return write_pydidas_poni(config.pydidas_cali_yaml, target)
    if not target.exists() or config.overwrite:
        assert config.poni_path is not None
        shutil.copy2(config.poni_path, target)
    return target


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        ordered: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in ordered:
                    ordered.append(key)
        fieldnames = ordered
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_processing_config(
    config: BL19B2Abs2DConfig,
    safe_poni: Path,
    *,
    mask_info: MaskInfo | None = None,
    processing_signature: str = "",
    signature_payload: dict[str, Any] | None = None,
) -> None:
    out_root = config.resolved_output_root()
    lines = [
        f"schema: {SCHEMA_VERSION}",
        f"input_root: {Path(config.input_root)}",
        f"output_root: {out_root}",
        f"source_poni_path: {_optional_path_text(config.poni_path)}",
        f"pydidas_cali_yaml: {_optional_path_text(config.pydidas_cali_yaml)}",
        f"configured_mask_path: {_optional_path_text(config.mask_path)}",
        f"safe_poni_path: {safe_poni}",
        f"mu_cm_inv: {config.mu_cm_inv}",
        f"alpha: {config.alpha}",
        f"standard_key: {config.standard_key}",
        f"q_window: [{config.q_window[0]}, {config.q_window[1]}]",
        f"npt: {config.npt}",
        f"dtype: {config.dtype}",
        f"dry_run: {str(config.dry_run).lower()}",
        f"max_frames: {config.max_frames if config.max_frames is not None else ''}",
        f"overwrite: {str(config.overwrite).lower()}",
        f"dark_hot_pixel_threshold: {config.dark_hot_pixel_threshold}",
        "normalization_formula: exposure_s * MON * ABS",
        "thickness_formula: -ln(ABS) / mu_cm_inv",
        "dark_scaling: exposure_matched",
        "corrected_2d_formula: ((S-dark*exp_s/exp_dark)/N_s - alpha*(BG-dark*exp_bg/exp_dark)/N_bg) * K / d_cm",
        "solid_angle_applied_in_image: false",
        "polarization_applied_in_image: false",
    ]
    if mask_info is not None:
        lines.extend(
            [
                f"mask_npy: {mask_info.npy_path}",
                f"mask_edf: {mask_info.edf_path}",
                f"mask_checksum_sha256: {mask_info.checksum_sha256}",
                f"user_mask_path: {mask_info.user_mask_path or ''}",
                f"user_mask_pixels: {mask_info.user_mask_pixels}",
                f"detector_mask_pixels: {mask_info.detector_mask_pixels}",
                f"dark_hot_pixels: {mask_info.dark_hot_pixels}",
                f"combined_mask_pixels: {mask_info.combined_mask_pixels}",
            ]
        )
    if processing_signature:
        lines.append(f"processing_signature: {processing_signature}")
    if signature_payload:
        lines.append("processing_signature_payload_json: " + json.dumps(signature_payload, sort_keys=True))
    path = out_root / "config" / "processing_config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def scan_inputs(config: BL19B2Abs2DConfig) -> tuple[list[dict[str, Any]], list[Path]]:
    """Scan TIFF inputs and return inventory rows plus candidate sample paths."""
    root = Path(config.input_root)
    if not root.exists():
        raise FileNotFoundError(f"input_root does not exist: {root}")
    rows: list[dict[str, Any]] = []
    sample_paths: list[Path] = []
    refs = find_reference_paths(
        root,
        mask_path=config.mask_path,
        pydidas_cali_yaml=config.pydidas_cali_yaml,
    )
    reference_set = {refs.dark.resolve(), refs.background.resolve(), refs.standard.resolve()}
    if refs.direct is not None and refs.direct.exists():
        reference_set.add(refs.direct.resolve())
    if refs.mask is not None and refs.mask.exists():
        reference_set.add(refs.mask.resolve())

    for path in sorted(root.rglob("*"), key=natural_key):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        ext = path.suffix.lower()
        if ext not in (".tif", ".tiff"):
            if ext in (".csv", ".dat", ".py", ".bat", ".7z", ".asc", ".json"):
                rows.append(
                    {
                        "relative_path": str(rel),
                        "kind": "ignored_non_tiff",
                        "status": "ignored",
                        "reason": f"extension {ext} is not raw detector TIFF input",
                    }
                )
            continue

        kind = "sample" if is_sample_tiff(path, root) else "ignored_tiff"
        if path.resolve() in reference_set:
            kind = "reference"
        header = read_tiff_header(path)
        classification = classify_sample_frame(header) if kind == "sample" else FrameClassification("ok")
        if kind == "sample":
            sample_paths.append(path)
        rows.append(
            {
                "relative_path": str(rel),
                "kind": kind,
                "status": classification.status,
                "reason": classification.reason,
                "exposure_s": header.exposure_s,
                "monitor": header.monitor,
                "transmission_abs": header.transmission,
                "energy_kev": header.energy_kev,
                "distance_mm": header.distance_mm,
                "beam_x_px": header.beam_x_px,
                "beam_y_px": header.beam_y_px,
                "pixel_size_m": header.pixel_size_m,
                "size_bytes": path.stat().st_size,
                "mtime": _dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    return rows, sample_paths


def _background_transmission(header: BL19B2Header) -> tuple[float, list[str]]:
    warnings: list[str] = []
    trans = header.transmission
    if trans is None or not math.isfinite(float(trans)) or float(trans) <= 0:
        warnings.append("BG ABS missing or invalid; using T_bg=1.0")
        return 1.0, warnings
    if float(trans) > 1.0:
        warnings.append(f"BG ABS={float(trans):.6g} > 1; clamped to T_bg=1.0")
        return 1.0, warnings
    return float(trans), warnings


def calibrate_standard(
    config: BL19B2Abs2DConfig,
    *,
    reference_paths: ReferencePaths,
    safe_poni_path: Path,
    dark: np.ndarray,
    background: np.ndarray,
    dark_header: BL19B2Header,
    mask: np.ndarray,
) -> tuple[StandardCalibration, np.ndarray]:
    """Estimate K from GC001 and return calibration plus normalized BG image."""
    try:
        import pyFAI
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pyFAI is required for BL19B2 K calibration") from exc

    bg_header = read_tiff_header(reference_paths.background)
    std_header = read_tiff_header(reference_paths.standard)
    std_class = classify_sample_frame(std_header)
    if std_class.status != "ok":
        raise ValueError(f"standard frame is not usable: {std_class.reason}")
    if not _is_finite_positive(dark_header.exposure_s):
        raise ValueError("dark frame requires Exposure_time for exposure-matched subtraction")
    assert dark_header.exposure_s is not None

    bg_t, warnings = _background_transmission(bg_header)
    if not _is_finite_positive(bg_header.exposure_s) or not _is_finite_positive(bg_header.monitor):
        raise ValueError("background frame requires Exposure_time and MON")
    assert bg_header.exposure_s is not None and bg_header.monitor is not None
    norm_bg = compute_norm_factor(bg_header.exposure_s, bg_header.monitor, bg_t)

    assert std_header.exposure_s is not None
    assert std_header.monitor is not None
    assert std_header.transmission is not None
    norm_std = compute_norm_factor(
        std_header.exposure_s,
        std_header.monitor,
        std_header.transmission,
    )
    if config.standard_thickness_cm is not None:
        std_thickness = float(config.standard_thickness_cm)
        std_thickness_source = "user_config"
    else:
        std_thickness = float(estimate_thickness_cm(std_header.transmission, config.mu_cm_inv))
        std_thickness_source = "beer_lambert_from_abs_mu"

    standard = read_detector_image(reference_paths.standard)
    if standard.shape != dark.shape or background.shape != dark.shape:
        raise ValueError(
            "reference image shape mismatch: "
            f"standard{standard.shape}, background{background.shape}, dark{dark.shape}"
        )
    mask_arr = np.asarray(mask, dtype=np.uint8)
    if mask_arr.shape != dark.shape:
        raise ValueError(f"mask shape mismatch: {mask_arr.shape} vs {dark.shape}")

    bg_net, _ = normalize_dark_corrected_image(
        background,
        dark,
        image_exposure_s=bg_header.exposure_s,
        dark_exposure_s=dark_header.exposure_s,
        monitor=bg_header.monitor,
        transmission=bg_t,
    )
    std_normed, _ = normalize_dark_corrected_image(
        standard,
        dark,
        image_exposure_s=std_header.exposure_s,
        dark_exposure_s=dark_header.exposure_s,
        monitor=std_header.monitor,
        transmission=std_header.transmission,
    )
    std_net = std_normed - config.alpha * bg_net
    ai = pyFAI.load(str(safe_poni_path))
    kwargs: dict[str, Any] = {
        "unit": "q_A^-1",
        "correctSolidAngle": bool(config.correct_solid_angle_for_k),
        "mask": mask_arr,
    }
    if config.polarization_factor is not None:
        kwargs["polarization_factor"] = float(config.polarization_factor)
    res = ai.integrate1d(std_net, int(config.npt), **kwargs)
    q = np.asarray(res.radial, dtype=np.float64)
    i_net_vol = np.asarray(res.intensity, dtype=np.float64) / std_thickness
    q_ref, i_ref = get_reference_data(config.standard_key)
    k_result = estimate_k_factor_robust(
        q_meas=q,
        i_meas_per_cm=i_net_vol,
        q_ref=q_ref,
        i_ref=i_ref,
        q_window=config.q_window,
    )
    calibration = StandardCalibration(
        k_factor=float(k_result.k_factor),
        k_std=float(k_result.k_std),
        q_min_overlap=float(k_result.q_min_overlap),
        q_max_overlap=float(k_result.q_max_overlap),
        points_used=int(k_result.points_used),
        points_total=int(k_result.points_total),
        standard_thickness_cm=float(std_thickness),
        norm_standard=float(norm_std),
        norm_background=float(norm_bg),
        bg_transmission_used=float(bg_t),
        standard_thickness_source=std_thickness_source,
        warnings=tuple(warnings),
    )
    return calibration, bg_net


def _coerce_output_dtype(image: np.ndarray, dtype: str) -> np.ndarray:
    dtype_n = str(dtype).strip().lower()
    if dtype_n == "float32":
        return image.astype(np.float32, copy=False)
    if dtype_n == "float64":
        return image.astype(np.float64, copy=False)
    raise ValueError("dtype must be float32 or float64")


def write_hdf5_image(path: Path, image: np.ndarray, metadata: dict[str, Any]) -> None:
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover
        raise ImportError("h5py is required for BL19B2 HDF5 output") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(str(path), "w") as f:
        entry = f.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        entry.attrs["schema"] = SCHEMA_VERSION
        entry.attrs["processing_signature"] = str(metadata.get("processing_signature", ""))
        data = entry.create_group("data")
        data.attrs["NX_class"] = "NXdata"
        data.attrs["signal"] = "I_abs_2d"
        ds = data.create_dataset(
            "I_abs_2d",
            data=image,
            compression="gzip",
            compression_opts=4,
            shuffle=True,
        )
        ds.attrs["units"] = INTENSITY_UNIT
        ds.attrs["long_name"] = "detector-space absolute corrected SAXS image"
        entry.create_dataset("metadata_json", data=json.dumps(_json_safe(metadata), ensure_ascii=False))


def write_edf_image(path: Path, image: np.ndarray, metadata: dict[str, Any]) -> None:
    calibration = metadata.get("absolute_calibration", {})
    mask = metadata.get("mask", {})
    thickness = metadata.get("thickness", {})
    normalization = metadata.get("normalization", {})
    dark = metadata.get("dark", {})
    mask = metadata.get("mask", {})
    corrections = metadata.get("corrections_applied_in_image", {})
    header = {
        "SAXSAbsSchema": SCHEMA_VERSION,
        "ImageType": "detector_space_absolute_corrected_2d",
        "IntensityUnit": INTENSITY_UNIT,
        "RawSample": str(metadata.get("raw_sample", "")),
        "ProcessingSignature": str(metadata.get("processing_signature", "")),
        "KFactor": f"{float(calibration.get('k_factor', math.nan)):.10g}",
        "ThicknessCm": f"{float(thickness.get('thickness_cm', math.nan)):.10g}",
        "NormSample": f"{float(normalization.get('norm_sample', math.nan)):.10g}",
        "TransmissionAbs": f"{float(normalization.get('transmission_abs', math.nan)):.10g}",
        "ExposureSample": f"{float(normalization.get('exposure_s', math.nan)):.10g}",
        "DarkExposure": f"{float(dark.get('exposure_s', math.nan)):.10g}",
        "MaskPath": str(mask.get("edf", "")),
        "SolidAngleAppliedInImage": str(bool(corrections.get("solid_angle", False))).lower(),
        "PolarizationAppliedInImage": str(bool(corrections.get("polarization", False))).lower(),
        "Normalization": "exposure_s * MON * ABS",
    }
    _write_edf_array(path, image, header=header)


def write_preview_png(path: Path, image: np.ndarray) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False

    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return False
    lo, hi = np.nanpercentile(finite, [1.0, 99.5])
    if not np.isfinite(lo) or not np.isfinite(hi) or lo >= hi:
        lo = float(np.nanmin(finite))
        hi = float(np.nanmax(finite))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6.0, 6.8), dpi=120)
    im = ax.imshow(image, origin="upper", cmap="viridis", vmin=lo, vmax=hi)
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label=INTENSITY_UNIT)
    fig.tight_layout(pad=0.05)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def _qc_stats(image: np.ndarray) -> dict[str, Any]:
    finite_mask = np.isfinite(image)
    finite = image[finite_mask]
    if finite.size == 0:
        return {
            "finite_fraction": 0.0,
            "negative_fraction": 0.0,
            "min": None,
            "max": None,
            "mean": None,
            "p01": None,
            "p50": None,
            "p995": None,
        }
    return {
        "finite_fraction": float(finite.size / image.size),
        "negative_fraction": float(np.sum(finite < 0) / finite.size),
        "min": float(np.nanmin(finite)),
        "max": float(np.nanmax(finite)),
        "mean": float(np.nanmean(finite)),
        "p01": float(np.nanpercentile(finite, 1.0)),
        "p50": float(np.nanpercentile(finite, 50.0)),
        "p995": float(np.nanpercentile(finite, 99.5)),
    }


def _pydidas_index_row(
    *,
    source: Path,
    paths: OutputPaths,
    safe_poni_path: Path,
    mask_info: MaskInfo,
) -> dict[str, Any]:
    return {
        "raw_sample": str(source),
        "edf": str(paths.edf),
        "hdf5": str(paths.h5),
        "poni": str(safe_poni_path),
        "mask": str(mask_info.npy_path),
        "mask_edf": str(mask_info.edf_path),
        "metadata": str(paths.metadata),
        "normalization_factor": 1.0,
        "dark": "",
        "flat": "",
    }


def _frame_qc_row_from_metadata(
    *,
    source: Path,
    rel: Path,
    paths: OutputPaths,
    expected_signature: str | None = None,
) -> dict[str, Any] | None:
    metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
    if metadata.get("schema") != SCHEMA_VERSION:
        return None
    if expected_signature is not None and metadata.get("processing_signature") != expected_signature:
        return None
    outputs = metadata.get("outputs", {})
    qc = metadata.get("qc", {})
    normalization = metadata.get("normalization", {})
    thickness = metadata.get("thickness", {})
    calibration = metadata.get("absolute_calibration", {})
    mask = metadata.get("mask", {})
    warnings = metadata.get("warnings", [])
    warning_text = " | ".join(str(item) for item in warnings) if isinstance(warnings, list) else str(warnings)
    preview = str(outputs.get("preview") or paths.preview)
    if not Path(preview).exists():
        preview = ""
    return {
        "relative_path": str(rel),
        "status": "success_existing",
        "hdf5": str(outputs.get("hdf5") or paths.h5),
        "edf": str(outputs.get("edf") or paths.edf),
        "metadata": str(outputs.get("metadata") or paths.metadata),
        "preview": preview,
        "processing_signature": metadata.get("processing_signature", ""),
        "mask": str(mask.get("npy", "")),
        "k_factor": calibration.get("k_factor", ""),
        "thickness_cm": thickness.get("thickness_cm", ""),
        "norm_sample": normalization.get("norm_sample", ""),
        "transmission_abs": normalization.get("transmission_abs", ""),
        **qc,
        "warnings": warning_text,
    }


def _frame_metadata(
    *,
    source: Path,
    header: BL19B2Header,
    norm_s: float,
    thickness_cm: float,
    calibration: StandardCalibration,
    paths: OutputPaths,
    qc: dict[str, Any],
    safe_poni_path: Path,
    reference_paths: ReferencePaths,
    config: BL19B2Abs2DConfig,
    dark_header: BL19B2Header,
    mask_info: MaskInfo,
    processing_signature: str,
    signature_payload: dict[str, Any],
    provenance_paths: ProvenancePaths,
    software_versions: dict[str, Any],
    code_state: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    metadata = {
        "schema": SCHEMA_VERSION,
        "formula_version": FORMULA_VERSION,
        "processing_signature": processing_signature,
        "processing_signature_payload": signature_payload,
        "raw_sample": str(source),
        "outputs": {
            "hdf5": str(paths.h5),
            "edf": str(paths.edf),
            "metadata": str(paths.metadata),
            "preview": str(paths.preview),
        },
        "intensity_unit": INTENSITY_UNIT,
        "normalization": {
            "formula": "exposure_s * MON * ABS",
            "exposure_s": header.exposure_s,
            "monitor": header.monitor,
            "transmission_abs": header.transmission,
            "norm_sample": norm_s,
        },
        "dark": {
            "file": str(reference_paths.dark),
            "exposure_s": dark_header.exposure_s,
            "scaling": "exposure_matched",
            "formula": "dark_scaled = dark * exposure_s / dark_exposure_s",
        },
        "thickness": {
            "method": "Beer-Lambert from ABS and mu",
            "mu_cm_inv": config.mu_cm_inv,
            "thickness_cm": thickness_cm,
        },
        "absolute_calibration": {
            "standard_file": str(reference_paths.standard),
            "standard_key": config.standard_key,
            "k_factor": calibration.k_factor,
            "k_std": calibration.k_std,
            "q_min_overlap": calibration.q_min_overlap,
            "q_max_overlap": calibration.q_max_overlap,
            "points_used": calibration.points_used,
            "points_total": calibration.points_total,
            "standard_thickness_cm": calibration.standard_thickness_cm,
            "standard_thickness_source": calibration.standard_thickness_source,
        },
        "background": {
            "background_file": str(reference_paths.background),
            "alpha": config.alpha,
            "norm_background": calibration.norm_background,
            "transmission_used": calibration.bg_transmission_used,
        },
        "mask": {
            "npy": str(mask_info.npy_path),
            "edf": str(mask_info.edf_path),
            "checksum_sha256": mask_info.checksum_sha256,
            "convention": "pyFAI: 0=valid, 1=masked",
            "sources": {
                "user_mask": str(mask_info.user_mask_path or ""),
                "pyfai_detector_mask": True,
                "dark_hot_pixel_threshold": mask_info.dark_hot_pixel_threshold,
            },
            "counts": {
                "user_mask_pixels": mask_info.user_mask_pixels,
                "detector_mask_pixels": mask_info.detector_mask_pixels,
                "dark_hot_pixels": mask_info.dark_hot_pixels,
                "combined_mask_pixels": mask_info.combined_mask_pixels,
            },
        },
        "geometry": {
            "poni": str(safe_poni_path),
            "source_poni_path": _optional_path_text(config.poni_path),
            "pydidas_cali_yaml": _optional_path_text(config.pydidas_cali_yaml),
            "energy_kev": header.energy_kev,
            "distance_mm_header": header.distance_mm,
            "beam_x_px_header": header.beam_x_px,
            "beam_y_px_header": header.beam_y_px,
            "pixel_size_m_header": header.pixel_size_m,
        },
        "corrections_applied_in_image": {
            "dark": True,
            "dark_scaling": "exposure_matched",
            "background": True,
            "monitor": True,
            "transmission": True,
            "absolute_k": True,
            "thickness": True,
            "flat": False,
            "mask": False,
            "solid_angle": False,
            "polarization": False,
        },
        "corrections_deferred_to_integration": {
            "mask": str(mask_info.npy_path),
            "solid_angle": bool(config.correct_solid_angle_for_k),
            "polarization_factor": config.polarization_factor,
        },
        "recommended_reintegration": {
            "dark": None,
            "flat": None,
            "mask": str(mask_info.npy_path),
            "normalization_factor": 1.0,
            "do_not_repeat": ["dark", "background", "transmission", "monitor", "thickness", "K"],
            "correctSolidAngle": bool(config.correct_solid_angle_for_k),
            "polarization_factor": config.polarization_factor,
            "solid_angle_and_polarization": "apply once during integration, not in the 2D image",
        },
        "qc": qc,
        "warnings": warnings,
    }
    metadata.update(
        build_provenance_metadata(
            provenance_paths=provenance_paths,
            software_versions=software_versions,
            code_state=code_state,
        )
    )
    return metadata


def _ensure_output_dirs(out_root: Path) -> None:
    for rel in [
        "config",
        "config/geometry",
        "images_h5",
        "images_edf",
        "metadata",
        "previews",
        "qc",
        "logs",
        "manifests",
        "masks",
    ]:
        (out_root / rel).mkdir(parents=True, exist_ok=True)


def _write_readme(out_root: Path) -> None:
    text = """# BL19B2 dat001 absolute corrected 2D outputs

These detector-space images have already had exposure-matched dark subtraction,
background subtraction, exposure/MON/transmission normalization, Beer-Lambert
thickness scaling, and GC-derived K-factor scaling applied.

The 2D matrix does not have mask, solid-angle, or polarization corrections
burned into pixel values.

For pyFAI/pydidas reintegration use the copied PONI file and set:

- dark = None
- flat = None
- mask = masks/bl19b2_mask.npy
- normalization_factor = 1.0
- correctSolidAngle = True
- do not reapply transmission, monitor, thickness, or K scaling

PNG previews are for inspection only and are not scientific data.
"""
    (out_root / "README.md").write_text(text, encoding="utf-8")


def run_bl19b2_abs2d(config: BL19B2Abs2DConfig) -> dict[str, Any]:
    """Run BL19B2 scan and optional absolute corrected 2D export."""
    validate_config(config)
    input_root = Path(config.input_root)
    out_root = config.resolved_output_root()
    _ensure_output_dirs(out_root)
    safe_poni = _copy_poni_to_safe_path(config)
    _write_readme(out_root)
    software_versions = collect_software_versions()
    code_state = collect_code_state()
    provenance_paths = _provenance_paths(out_root)

    reference_paths = find_reference_paths(
        input_root,
        mask_path=config.mask_path,
        pydidas_cali_yaml=config.pydidas_cali_yaml,
    )
    inventory_rows, sample_paths = scan_inputs(config)
    _write_csv(out_root / "manifests" / "input_inventory.csv", inventory_rows)
    _write_csv(
        out_root / "config" / "reference_selection.csv",
        [
            {"kind": "dark", "path": str(reference_paths.dark)},
            {"kind": "background", "path": str(reference_paths.background)},
            {"kind": "standard", "path": str(reference_paths.standard)},
            {"kind": "direct", "path": str(reference_paths.direct or "")},
            {"kind": "mask", "path": str(reference_paths.mask or "")},
            {"kind": "poni", "path": str(safe_poni)},
        ],
    )

    sample_total = len(sample_paths)
    rejected_scan = [row for row in inventory_rows if row.get("kind") == "sample" and row["status"] != "ok"]
    if config.dry_run:
        _write_processing_config(config, safe_poni)
        provenance_paths.run_command.parent.mkdir(parents=True, exist_ok=True)
        provenance_paths.run_command.write_text(
            build_rerun_command(config, poni_path=safe_poni),
            encoding="utf-8",
        )
        _write_json(provenance_paths.processing_environment, software_versions)
        provenance_paths.code_state.write_text(format_code_state_text(code_state), encoding="utf-8")
        _write_csv(out_root / "qc" / "rejected_frames.csv", rejected_scan)
        return {
            "status": "dry-run",
            "output_root": str(out_root),
            "sample_total": sample_total,
            "rejected": len(rejected_scan),
            "inventory_csv": str(out_root / "manifests" / "input_inventory.csv"),
            "run_command": str(provenance_paths.run_command),
        }

    dark = read_detector_image(reference_paths.dark)
    dark_header = read_tiff_header(reference_paths.dark)
    background = read_detector_image(reference_paths.background)
    mask_info = load_and_write_mask(
        safe_poni_path=safe_poni,
        dark=dark,
        reference_paths=reference_paths,
        config=config,
    )
    calibration, bg_net = calibrate_standard(
        config,
        reference_paths=reference_paths,
        safe_poni_path=safe_poni,
        dark=dark,
        background=background,
        dark_header=dark_header,
        mask=mask_info.mask,
    )
    processing_signature, signature_payload = build_processing_signature(
        config,
        mask_info=mask_info,
        standard_thickness_source=calibration.standard_thickness_source,
        safe_poni_path=safe_poni,
    )
    _write_processing_config(
        config,
        safe_poni,
        mask_info=mask_info,
        processing_signature=processing_signature,
        signature_payload=signature_payload,
    )
    standard_rows = [
        {
            "schema": SCHEMA_VERSION,
            "processing_signature": processing_signature,
            "k_factor": calibration.k_factor,
            "k_std": calibration.k_std,
            "q_min_overlap": calibration.q_min_overlap,
            "q_max_overlap": calibration.q_max_overlap,
            "points_used": calibration.points_used,
            "points_total": calibration.points_total,
            "standard_thickness_cm": calibration.standard_thickness_cm,
            "standard_thickness_source": calibration.standard_thickness_source,
            "norm_standard": calibration.norm_standard,
            "norm_background": calibration.norm_background,
            "bg_transmission_used": calibration.bg_transmission_used,
            "dark_exposure_s": dark_header.exposure_s,
            "mask_checksum_sha256": mask_info.checksum_sha256,
            "warnings": " | ".join(calibration.warnings),
        }
    ]
    _write_csv(out_root / "qc" / "standard_k_report.csv", standard_rows)

    valid_samples = [p for p in sample_paths if classify_sample_frame(read_tiff_header(p)).status == "ok"]
    if config.max_frames is not None:
        valid_samples = valid_samples[: max(0, int(config.max_frames))]

    frame_qc_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    pydidas_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = list(rejected_scan)
    warning_rows: list[dict[str, Any]] = []
    processed = 0
    skipped = 0
    failed = 0

    for source in valid_samples:
        rel = source.relative_to(input_root)
        paths = build_output_paths(source, input_root=input_root, output_root=out_root)
        if (
            paths.h5.exists()
            and paths.edf.exists()
            and paths.metadata.exists()
            and not config.overwrite
        ):
            try:
                row = _frame_qc_row_from_metadata(
                    source=source,
                    rel=rel,
                    paths=paths,
                    expected_signature=processing_signature,
                )
            except Exception:
                row = None
            if row is not None:
                update_metadata_provenance(
                    paths.metadata,
                    provenance_paths=provenance_paths,
                    software_versions=software_versions,
                    code_state=code_state,
                )
                skipped += 1
                frame_qc_rows.append(row)
                manifest_row = {"raw_sample": str(source), **row}
                manifest_row["status"] = "skipped_existing"
                manifest_rows.append(manifest_row)
                pydidas_rows.append(
                    _pydidas_index_row(
                        source=source,
                        paths=paths,
                        safe_poni_path=safe_poni,
                        mask_info=mask_info,
                    )
                )
                if row.get("warnings"):
                    warning_rows.append(row)
                continue

        try:
            header = read_tiff_header(source)
            frame_class = classify_sample_frame(header)
            if frame_class.status != "ok":
                rejected_rows.append(
                    {
                        "relative_path": str(rel),
                        "kind": "sample",
                        "status": frame_class.status,
                        "reason": frame_class.reason,
                    }
                )
                continue
            assert header.exposure_s is not None
            assert header.monitor is not None
            assert header.transmission is not None
            thickness = float(estimate_thickness_cm(header.transmission, config.mu_cm_inv))
            sample = read_detector_image(source)
            if sample.shape != dark.shape:
                raise ValueError(f"sample shape mismatch: {sample.shape} vs dark{dark.shape}")

            sample_normed, norm_s = normalize_dark_corrected_image(
                sample,
                dark,
                image_exposure_s=header.exposure_s,
                dark_exposure_s=dark_header.exposure_s,
                monitor=header.monitor,
                transmission=header.transmission,
            )
            image_abs = (sample_normed - config.alpha * bg_net) * (calibration.k_factor / thickness)
            image_out = _coerce_output_dtype(image_abs, config.dtype)
            qc = _qc_stats(image_out)
            warnings = list(calibration.warnings)
            if qc["finite_fraction"] < 0.99:
                warnings.append(f"finite_fraction below 0.99: {qc['finite_fraction']:.6g}")
            if qc["negative_fraction"] > 0.2:
                warnings.append(f"negative_fraction above 0.2: {qc['negative_fraction']:.6g}")

            metadata = _frame_metadata(
                source=source,
                header=header,
                norm_s=norm_s,
                thickness_cm=thickness,
                calibration=calibration,
                paths=paths,
                qc=qc,
                safe_poni_path=safe_poni,
                reference_paths=reference_paths,
                config=config,
                dark_header=dark_header,
                mask_info=mask_info,
                processing_signature=processing_signature,
                signature_payload=signature_payload,
                provenance_paths=provenance_paths,
                software_versions=software_versions,
                code_state=code_state,
                warnings=warnings,
            )
            write_hdf5_image(paths.h5, image_out, metadata)
            write_edf_image(paths.edf, image_out, metadata)
            _write_json(paths.metadata, metadata)
            preview_written = False
            if config.write_preview:
                preview_written = write_preview_png(paths.preview, image_out)

            row = {
                "relative_path": str(rel),
                "status": "success",
                "hdf5": str(paths.h5),
                "edf": str(paths.edf),
                "metadata": str(paths.metadata),
                "preview": str(paths.preview) if preview_written else "",
                "processing_signature": processing_signature,
                "mask": str(mask_info.npy_path),
                "k_factor": calibration.k_factor,
                "thickness_cm": thickness,
                "norm_sample": norm_s,
                "transmission_abs": header.transmission,
                **qc,
                "warnings": " | ".join(warnings),
            }
            frame_qc_rows.append(row)
            manifest_rows.append({"raw_sample": str(source), **row})
            pydidas_rows.append(
                _pydidas_index_row(
                    source=source,
                    paths=paths,
                    safe_poni_path=safe_poni,
                    mask_info=mask_info,
                )
            )
            if warnings:
                warning_rows.append(row)
            processed += 1
        except Exception as exc:
            failed += 1
            row = {
                "relative_path": str(rel),
                "kind": "sample",
                "status": "failed",
                "reason": str(exc),
            }
            rejected_rows.append(row)
            manifest_rows.append({"raw_sample": str(source), **row})

    _write_csv(out_root / "qc" / "frame_qc.csv", frame_qc_rows)
    _write_csv(out_root / "qc" / "warning_frames.csv", warning_rows)
    _write_csv(out_root / "qc" / "rejected_frames.csv", rejected_rows)
    _write_csv(out_root / "manifests" / "processing_manifest.csv", manifest_rows)
    _write_csv(out_root / "manifests" / "pydidas_pyfai_index.csv", pydidas_rows)
    log_path = out_root / "logs" / "processing.log"
    log_path.write_text(
        "\n".join(
            [
                f"timestamp={_dt.datetime.now().isoformat(timespec='seconds')}",
                f"input_root={input_root}",
                f"output_root={out_root}",
                f"processed={processed}",
                f"skipped={skipped}",
                f"failed={failed}",
                f"rejected={len(rejected_rows)}",
                f"k_factor={calibration.k_factor:.10g}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    counts = {
        "sample_total": sample_total,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "rejected": len(rejected_rows),
        "successful_outputs": len(frame_qc_rows),
    }
    write_provenance_package(
        config=config,
        safe_poni_path=safe_poni,
        reference_paths=reference_paths,
        mask_info=mask_info,
        calibration=calibration,
        processing_signature=processing_signature,
        signature_payload=signature_payload,
        counts=counts,
        software_versions=software_versions,
        code_state=code_state,
        run_status="complete",
    )
    return {
        "status": "complete",
        "output_root": str(out_root),
        "sample_total": sample_total,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "rejected": len(rejected_rows),
        "k_factor": calibration.k_factor,
        "standard_k_report": str(out_root / "qc" / "standard_k_report.csv"),
        "processing_manifest": str(out_root / "manifests" / "processing_manifest.csv"),
        "provenance_summary": str(provenance_paths.provenance_summary),
    }
