"""Export detector-space calibrated 2D SAXS images and provenance packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "saxsabs.calibrated2d.v1"
IMAGE_TYPE = "detector_space_absolute_calibrated_net_image"
MASK_CONVENTION = "pyFAI: 0=valid, 1=masked"


@dataclass(frozen=True)
class Calibrated2DExportConfig:
    """Configuration for writing one calibrated 2D export package."""

    root_dir: str | Path
    sample_id: str
    raw_sample_path: str | Path
    poni_path: str | Path
    image: np.ndarray
    mask: np.ndarray | None = None
    dtype: str = "float32"
    overwrite: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_sample_path_mode: str = "basename_hash"
    min_finite_fraction: float = 0.99


@dataclass(frozen=True)
class Calibrated2DExportResult:
    """Paths and manifest data produced for one calibrated 2D package."""

    sample_id: str
    image_path: Path
    mask_npy_path: Path
    mask_edf_path: Path
    poni_path: Path
    metadata_path: Path
    manifest_row: dict[str, Any]


def make_sample_id(stem: str, source_path: str | Path) -> str:
    """Return a stable, filesystem-safe sample id with a short path hash."""
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(stem).strip()).strip("._-")
    if not safe_stem:
        safe_stem = "sample"
    try:
        source_key = str(Path(source_path).resolve())
    except OSError:
        source_key = str(source_path)
    digest = hashlib.sha1(source_key.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"{safe_stem}_{digest}"


def build_absolute_detector_image(
    img_net: np.ndarray,
    k_factor: float,
    thickness_cm: float,
    flat: np.ndarray | None = None,
    apply_flat: bool = True,
) -> np.ndarray:
    """Scale a detector-space net image to absolute intensity.

    The input ``img_net`` is expected to already contain dark/background and
    monitor/transmission correction:
    ``(sample-dark)/norm_sample - alpha*(background-dark)/norm_background``.
    """
    img = np.asarray(img_net, dtype=np.float64)
    k_val = float(k_factor)
    d_val = float(thickness_cm)
    if not np.isfinite(k_val) or k_val <= 0:
        raise ValueError("k_factor must be finite and > 0")
    if not np.isfinite(d_val) or d_val <= 0:
        raise ValueError("thickness_cm must be finite and > 0")

    out = img * (k_val / d_val)
    if flat is not None and apply_flat:
        flat_arr = np.asarray(flat, dtype=np.float64)
        if flat_arr.shape != img.shape:
            raise ValueError(f"flat shape mismatch: {flat_arr.shape} vs {img.shape}")
        with np.errstate(divide="ignore", invalid="ignore"):
            out = out / flat_arr
        out = np.where(np.isfinite(flat_arr) & (flat_arr > 0), out, np.nan)
    return out


def _coerce_dtype(dtype: str) -> np.dtype:
    dtype_n = str(dtype).strip().lower()
    if dtype_n in ("float32", "edf float32"):
        return np.dtype("float32")
    if dtype_n in ("float64", "edf float64"):
        return np.dtype("float64")
    raise ValueError("dtype must be 'float32' or 'float64'")


def _pyfai_mask(mask: np.ndarray | None, shape: tuple[int, ...]) -> np.ndarray:
    if mask is None:
        return np.zeros(shape, dtype=np.uint8)
    mask_arr = np.asarray(mask)
    if mask_arr.shape != shape:
        raise ValueError(f"mask shape mismatch: {mask_arr.shape} vs {shape}")
    return np.where(mask_arr != 0, 1, 0).astype(np.uint8)


def _validate_calibrated_image(
    image: np.ndarray,
    min_finite_fraction: float = 0.99,
    *,
    mask: np.ndarray | None = None,
    stage: str = "input",
) -> None:
    if image.ndim != 2 or image.size == 0 or any(dim == 0 for dim in image.shape):
        raise ValueError("calibrated image must be a non-empty 2-D array")
    min_fraction = float(min_finite_fraction)
    if not np.isfinite(min_fraction) or min_fraction <= 0 or min_fraction > 1:
        raise ValueError("min_finite_fraction must be finite and satisfy 0 < value <= 1")
    finite_count = int(np.isfinite(image).sum())
    finite_fraction = finite_count / image.size
    if finite_count == 0 or finite_fraction < min_fraction:
        raise ValueError(
            "calibrated image has too many non-finite values; "
            f"finite_fraction={finite_fraction:.6g}, min_finite_fraction={min_fraction:.6g}"
        )
    if mask is not None:
        mask_arr = np.asarray(mask) != 0
        if mask_arr.shape != image.shape:
            raise ValueError(f"mask shape mismatch: {mask_arr.shape} vs {image.shape}")
        invalid_unmasked = (~mask_arr) & (~np.isfinite(image))
        if np.any(invalid_unmasked):
            raise ValueError(
                f"calibrated image has non-finite unmasked pixels after {stage}; "
                f"count={int(np.count_nonzero(invalid_unmasked))}"
            )


def _write_edf(path: Path, data: np.ndarray, header: dict[str, str] | None = None) -> None:
    try:
        from fabio.edfimage import EdfImage
    except ImportError as exc:  # pragma: no cover
        raise ImportError("fabio is required for calibrated 2D EDF export") from exc

    img = EdfImage(data=data, header=header or {})
    img.write(str(path))


def _relpath(path: Path, start: Path) -> str:
    return os.path.relpath(path, start=start).replace(os.sep, "/")


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
    return value


def _stable_path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _raw_sample_reference(path: Path, mode: str) -> str:
    mode_normalized = str(mode).strip().lower().replace("-", "_")
    if mode_normalized in {"basename_hash", "basename_hash_private", "private"}:
        digest = hashlib.sha1(_stable_path_key(path).encode("utf-8", errors="replace")).hexdigest()
        return f"{path.name or 'raw_sample'}#{digest[:8]}"
    if mode_normalized in {"absolute", "absolute_path"}:
        return _stable_path_key(path)
    raise ValueError("raw_sample_path_mode must be 'basename_hash' or 'absolute'")


def _transaction_path(target: Path, *, kind: str, token: str) -> Path:
    return target.with_name(f".saxsabs-{kind}-{token}-{target.name}")


def _unlink_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _publish_calibrated2d_package(
    staged: dict[Path, Path],
    *,
    overwrite: bool,
) -> None:
    """Publish staged package members with no-clobber or rollback semantics."""
    targets = list(staged)
    published: list[Path] = []
    backups: dict[Path, Path] = {}
    rollback_failed = False
    token = uuid.uuid4().hex
    try:
        if not overwrite:
            for target in targets:
                # A same-directory hard link is an atomic, Windows-safe
                # create-if-absent operation; it never replaces a racer.
                os.link(staged[target], target)
            # Do not path-delete earlier members after a later collision:
            # portable filesystems provide no atomic conditional unlink, so a
            # competing writer could be deleted between any identity check and
            # unlink.  The package completeness gate rejects retained fragments.
            return

        for target in targets:
            if not target.exists():
                continue
            if not target.is_file() or target.is_symlink():
                raise FileExistsError(
                    f"calibrated 2D overwrite target is not a regular file: {target}"
                )
            backup = _transaction_path(target, kind="backup", token=token)
            try:
                os.link(target, backup)
            except OSError:
                shutil.copy2(target, backup)
            backups[target] = backup

        try:
            for target in targets:
                os.replace(staged[target], target)
                published.append(target)
        except BaseException as publish_error:
            rollback_errors: list[str] = []
            for target in reversed(published):
                backup = backups.get(target)
                try:
                    if backup is None:
                        _unlink_if_present(target)
                    else:
                        os.replace(backup, target)
                except OSError as rollback_error:
                    rollback_errors.append(f"{target}: {rollback_error}")
            if rollback_errors:
                rollback_failed = True
                raise RuntimeError(
                    "calibrated 2D package publish failed and rollback was incomplete; "
                    "backup files were retained: "
                    + "; ".join(rollback_errors)
                ) from publish_error
            raise
    finally:
        for stage in staged.values():
            _unlink_if_present(stage)
        if not rollback_failed:
            for backup in backups.values():
                _unlink_if_present(backup)


def write_calibrated2d_package(config: Calibrated2DExportConfig) -> Calibrated2DExportResult:
    """Write one calibrated 2D image package for pyFAI/pydidas reintegration."""
    root = Path(config.root_dir)
    raw_sample_id = str(config.sample_id)
    sample_id = make_sample_id(raw_sample_id, config.raw_sample_path)
    # Keep caller-provided hashed ids stable; avoid double-hashing.
    if re.search(r"_[0-9a-f]{8}(?:_rerun[1-9][0-9]*)?$", raw_sample_id):
        if "/" in raw_sample_id or "\\" in raw_sample_id:
            raise ValueError("sample_id must not contain path separators")
        sample_id = raw_sample_id

    image = np.asarray(config.image)
    if image.ndim != 2:
        raise ValueError("calibrated image must be a 2-D array")
    out_dtype = _coerce_dtype(config.dtype)
    mask_out = _pyfai_mask(config.mask, image.shape)
    _validate_calibrated_image(
        image,
        config.min_finite_fraction,
        mask=mask_out,
        stage="input validation",
    )
    with np.errstate(over="ignore", invalid="ignore"):
        image_out = image.astype(out_dtype, copy=False)
    _validate_calibrated_image(
        image_out,
        config.min_finite_fraction,
        mask=mask_out,
        stage="dtype conversion",
    )

    dirs = {
        "images": root / "images",
        "geometry": root / "geometry",
        "masks": root / "masks",
        "metadata": root / "metadata",
    }

    image_path = dirs["images"] / f"{sample_id}_cal2d.edf"
    mask_npy_path = dirs["masks"] / f"{sample_id}_mask.npy"
    mask_edf_path = dirs["masks"] / f"{sample_id}_mask.edf"
    poni_out_path = dirs["geometry"] / f"{sample_id}.poni"
    metadata_path = dirs["metadata"] / f"{sample_id}_cal2d.json"

    targets = [image_path, mask_npy_path, mask_edf_path, poni_out_path, metadata_path]
    if not config.overwrite:
        existing = [p for p in targets if p.exists()]
        if existing:
            raise FileExistsError(f"calibrated 2D export target exists: {existing[0]}")

    raw_sample = Path(config.raw_sample_path)
    raw_sample_ref = _raw_sample_reference(raw_sample, config.raw_sample_path_mode)
    poni_src = Path(config.poni_path)
    if not poni_src.is_file():
        raise FileNotFoundError(f"PONI file not found or not a regular file: {poni_src}")
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    header = {
        "SAXSAbsSchema": SCHEMA_VERSION,
        "ImageType": IMAGE_TYPE,
        "IntensityUnit": "cm^-1",
        "MaskConvention": MASK_CONVENTION,
    }
    metadata_dir = metadata_path.parent
    user_meta = _json_safe(dict(config.metadata or {}))
    integration_policy = dict(user_meta.get("integration_policy", {}))
    flat_applied = bool(integration_policy.get("flat_applied_in_image", False))
    correct_solid = bool(integration_policy.get("correctSolidAngle", False))
    polarization = integration_policy.get("polarization_factor")

    meta = {
        "schema": SCHEMA_VERSION,
        "image_type": IMAGE_TYPE,
        "intensity_unit": "cm^-1",
        "files": {
            "raw_sample": raw_sample_ref,
            "calibrated_image": _relpath(image_path, metadata_dir),
            "poni": _relpath(poni_out_path, metadata_dir),
            "mask_npy": _relpath(mask_npy_path, metadata_dir),
            "mask_edf": _relpath(mask_edf_path, metadata_dir),
        },
        "normalization": user_meta.get("normalization", {}),
        "background": user_meta.get("background", {}),
        "corrections_applied_in_image": {
            "dark": True,
            "background": True,
            "monitor": True,
            "transmission": True,
            "absolute_k": True,
            "thickness": True,
            "flat": flat_applied,
            "solid_angle": False,
            "polarization": False,
        },
        "integration_policy": {
            "correctSolidAngle": correct_solid,
            "polarization_applied": bool(
                integration_policy.get("polarization_applied", False)
            ),
            "polarization_factor": polarization,
            "flat_applied_in_image": flat_applied,
            "mask_convention": MASK_CONVENTION,
        },
        "recommended_pyfai_reintegration": {
            "dark": None,
            "flat": None if flat_applied else user_meta.get("flat_path"),
            "normalization_factor": 1.0,
            "correctSolidAngle": correct_solid,
            "polarization_factor": polarization,
            "mask": _relpath(mask_npy_path, metadata_dir),
        },
        "qc": {
            "image_shape": list(image.shape),
            "mask_shape": list(mask_out.shape),
            "finite_fraction": float(np.isfinite(image_out).sum() / image_out.size),
            "negative_fraction": float(
                np.sum(np.isfinite(image_out) & (image_out < 0)) / image_out.size
            ),
        },
    }
    for key, value in user_meta.items():
        if key not in meta and key not in ("integration_policy",):
            meta[key] = value

    transaction_token = uuid.uuid4().hex
    staged = {
        target: _transaction_path(target, kind="stage", token=transaction_token)
        for target in targets
    }
    try:
        _write_edf(staged[image_path], image_out, header=header)
        np.save(staged[mask_npy_path], mask_out)
        _write_edf(
            staged[mask_edf_path],
            mask_out,
            header={"MaskConvention": MASK_CONVENTION},
        )
        shutil.copy2(poni_src, staged[poni_out_path])
        staged[metadata_path].write_text(
            json.dumps(_json_safe(meta), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except BaseException:
        for stage in staged.values():
            _unlink_if_present(stage)
        raise
    _publish_calibrated2d_package(staged, overwrite=config.overwrite)

    manifest_row = {
        "sample_id": sample_id,
        "raw_sample": raw_sample_ref,
        "calibrated_image": str(image_path),
        "poni": str(poni_out_path),
        "mask_npy": str(mask_npy_path),
        "mask_edf": str(mask_edf_path),
        "metadata": str(metadata_path),
        "dtype": str(out_dtype),
        "image_shape": "x".join(str(v) for v in image.shape),
    }

    return Calibrated2DExportResult(
        sample_id=sample_id,
        image_path=image_path,
        mask_npy_path=mask_npy_path,
        mask_edf_path=mask_edf_path,
        poni_path=poni_out_path,
        metadata_path=metadata_path,
        manifest_row=manifest_row,
    )
