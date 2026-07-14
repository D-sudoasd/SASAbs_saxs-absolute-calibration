"""Fail-closed 1D integration of BL19B2 absolute-corrected 2D packages.

The input EDF pixels are already in ``cm^-1``.  This workflow applies only the
deferred detector mask and solid-angle correction during azimuthal integration;
it deliberately does not repeat dark, background, monitor, transmission,
thickness, or absolute-scale corrections.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata as importlib_metadata
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np


SCHEMA_VERSION = "saxsabs.bl19b2_integrate1d.v1"
SUCCESS_STATUSES = frozenset({"success", "processed", "skipped_existing", "success_existing"})
NON_SUCCESS_STATUSES = frozenset({"failed"})
DO_NOT_REPEAT = frozenset({"dark", "background", "transmission", "monitor", "thickness", "K"})


@dataclass(frozen=True)
class Integrate1DConfig:
    """Configuration for one independent BL19B2 2D output package."""

    package_root: Path
    processing_manifest: Path | None = None
    poni_path: Path | None = None
    mask_path: Path | None = None
    npt: int = 5500
    unit: str = "q_A^-1"
    method: str = "csr"
    correct_solid_angle: bool = True
    polarization_factor: float | None = None
    resume: bool = True

    def output_root(self) -> Path:
        return Path(self.package_root) / "integration"


@dataclass(frozen=True)
class _InputRow:
    relative_path: Path
    edf: Path
    metadata: Path
    processing_signature: str


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _array_sha256(array: np.ndarray) -> str:
    value = np.asarray(array)
    canonical = np.ascontiguousarray(value.astype(value.dtype.name, copy=False))
    digest = hashlib.sha256()
    digest.update(str(canonical.shape).encode("ascii"))
    digest.update(canonical.dtype.name.encode("ascii"))
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()


def _mask_checksum(mask: np.ndarray) -> str:
    value = np.asarray(mask, dtype=np.uint8)
    digest = hashlib.sha256()
    digest.update(str(value.shape).encode("ascii"))
    digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _metadata_scientific_sha256(metadata: dict[str, Any]) -> str:
    scientific = dict(metadata)
    scientific.pop("last_resume_validation", None)
    return _canonical_hash(scientific)


def _package_file(path: Path, root: Path, label: str) -> Path:
    root_resolved = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside package_root: {path}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} is not a regular file: {path}")
    return resolved


def _relative_input_path(value: str) -> Path:
    text = value.strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or re.match(r"^[A-Za-z]:", text)
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"unsafe relative_path in 2D manifest: {value!r}")
    return Path(*pure.parts)


def _resolve_manifest_output(row: dict[str, str], names: tuple[str, ...], label: str) -> Path:
    values = [row.get(name, "").strip() for name in names if row.get(name, "").strip()]
    if not values:
        raise ValueError(f"successful 2D manifest row is missing {label}")
    resolved = [Path(value).resolve(strict=True) for value in values]
    if any(path != resolved[0] for path in resolved[1:]):
        raise ValueError(f"conflicting {label} columns in 2D manifest")
    return resolved[0]


def _find_single(root: Path, pattern: str, label: str) -> Path:
    matches = sorted(path for path in root.glob(pattern) if path.is_file())
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {label}, found {len(matches)} under {root}")
    return matches[0]


def _read_manifest(config: Integrate1DConfig) -> tuple[Path, bytes, list[_InputRow]]:
    package = Path(config.package_root).resolve(strict=True)
    manifest = _package_file(
        Path(config.processing_manifest or package / "manifests" / "processing_manifest.csv"),
        package,
        "processing_manifest",
    )
    raw = manifest.read_bytes()
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows:
        raise ValueError("2D processing manifest is empty")
    required = {"relative_path", "status", "processing_signature"}
    if not required.issubset(rows[0]):
        raise ValueError(f"2D processing manifest is missing columns: {sorted(required - rows[0].keys())}")

    selected: list[_InputRow] = []
    seen_rel: set[str] = set()
    seen_edf: set[Path] = set()
    image_root = (package / "images_edf").resolve(strict=True)
    metadata_root = (package / "metadata").resolve(strict=True)
    for row in rows:
        status = row.get("status", "").strip().lower()
        if status in NON_SUCCESS_STATUSES:
            continue
        if status not in SUCCESS_STATUSES:
            raise ValueError(f"unknown 2D manifest status {status!r}; refusing to omit it")
        rel = _relative_input_path(row.get("relative_path", ""))
        rel_key = rel.as_posix().casefold()
        if rel_key in seen_rel:
            raise ValueError(f"duplicate relative_path in 2D manifest: {rel}")
        seen_rel.add(rel_key)
        edf = _resolve_manifest_output(row, ("edf", "output_edf"), "EDF path")
        metadata = _resolve_manifest_output(row, ("metadata", "output_metadata"), "metadata path")
        expected_edf = (image_root / rel.parent / f"{rel.stem}_abs2d_cm-1.edf").resolve()
        expected_meta = (metadata_root / rel.parent / f"{rel.stem}_abs2d.json").resolve()
        if edf != expected_edf or metadata != expected_meta:
            raise ValueError(f"2D outputs do not match relative_path mapping for {rel}")
        _package_file(edf, image_root, "EDF")
        _package_file(metadata, metadata_root, "metadata")
        if edf in seen_edf:
            raise ValueError(f"duplicate EDF in 2D manifest: {edf}")
        seen_edf.add(edf)
        signature = row.get("processing_signature", "").strip()
        if not signature:
            raise ValueError(f"missing 2D processing_signature for {rel}")
        selected.append(_InputRow(rel, edf, metadata, signature))

    if not selected:
        raise ValueError("2D manifest contains no successful EDF rows")
    discovered = {path.resolve() for path in image_root.rglob("*.edf") if path.is_file()}
    if discovered != seen_edf:
        missing = sorted(str(path) for path in discovered - seen_edf)
        extra = sorted(str(path) for path in seen_edf - discovered)
        raise ValueError(f"2D manifest/EDF tree mismatch; unlisted={missing}, missing={extra}")
    selected.sort(key=lambda item: _natural_key(item.relative_path.as_posix()))
    return manifest, raw, selected


def _natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def _load_mask(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        value = np.load(path, allow_pickle=False)
    else:
        try:
            import fabio
        except ImportError as exc:  # pragma: no cover
            raise ImportError("fabio is required to read the BL19B2 EDF mask") from exc
        image = fabio.open(str(path))
        try:
            value = np.asarray(image.data)
        finally:
            close = getattr(image, "close", None)
            if callable(close):
                close()
    if value.ndim != 2 or not np.all(np.isfinite(value)):
        raise ValueError("integration mask must be a finite 2D array")
    return (np.asarray(value) != 0).astype(np.uint8)


def _load_integrator(path: Path) -> Any:
    try:
        import pyFAI
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pyFAI is required for BL19B2 1D integration") from exc
    return pyFAI.load(str(path))


def _version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _write_new_or_verify(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError(f"existing integration artifact differs; refusing overwrite: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        raise FileExistsError(f"stale temporary integration artifact: {temporary}")
    temporary.write_bytes(data)
    temporary.replace(path)


def _profile_bytes(q: np.ndarray, intensity: np.ndarray) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(["q_A^-1", "I_abs_cm^-1"])
    writer.writerows((f"{x:.17g}", f"{y:.17g}") for x, y in zip(q, intensity, strict=True))
    return text.getvalue().encode("utf-8")


def _read_profile(path: Path, npt: int) -> tuple[np.ndarray, np.ndarray]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        if next(reader, None) != ["q_A^-1", "I_abs_cm^-1"]:
            raise ValueError(f"invalid 1D profile header: {path}")
        data = np.asarray([[float(x), float(y)] for x, y in reader], dtype=np.float64)
    if data.shape != (npt, 2) or not np.all(np.isfinite(data)) or np.any(np.diff(data[:, 0]) <= 0):
        raise ValueError(f"invalid 1D profile values: {path}")
    return data[:, 0], data[:, 1]


def _validate_metadata(
    item: _InputRow,
    mask_path: Path,
    *,
    mask_checksum_sha256: str,
    poni_path: Path,
    poni_sha256: str,
) -> tuple[dict[str, Any], str]:
    raw = item.metadata.read_bytes()
    try:
        metadata = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable 2D metadata: {item.metadata}") from exc
    if metadata.get("processing_signature") != item.processing_signature:
        raise ValueError(f"2D processing signature mismatch for {item.relative_path}")
    if metadata.get("intensity_unit") != "cm^-1" or not metadata.get("frame_signature"):
        raise ValueError(f"2D metadata lacks absolute-intensity/frame provenance for {item.relative_path}")
    recorded_edf = Path(str(metadata.get("outputs", {}).get("edf", ""))).resolve()
    if recorded_edf != item.edf:
        raise ValueError(f"2D metadata EDF pointer mismatch for {item.relative_path}")
    recorded_mask = Path(str(metadata.get("mask", {}).get("npy", ""))).resolve()
    if recorded_mask != mask_path:
        raise ValueError(f"2D metadata mask pointer mismatch for {item.relative_path}")
    recorded_mask_checksum = str(metadata.get("mask", {}).get("checksum_sha256", ""))
    if not recorded_mask_checksum or recorded_mask_checksum != mask_checksum_sha256:
        raise ValueError(f"2D metadata mask array checksum mismatch for {item.relative_path}")
    recorded_poni = Path(str(metadata.get("geometry", {}).get("poni", ""))).resolve()
    if recorded_poni != poni_path:
        raise ValueError(f"2D metadata PONI pointer mismatch for {item.relative_path}")
    recorded_poni_sha = str(
        metadata.get("processing_signature_payload", {}).get(
            "safe_poni_checksum_sha256", ""
        )
    )
    if not recorded_poni_sha or recorded_poni_sha != poni_sha256:
        raise ValueError(f"2D metadata PONI checksum mismatch for {item.relative_path}")
    corrections = metadata.get("corrections_applied_in_image", {})
    for name in ("dark", "background", "monitor", "transmission", "absolute_k", "thickness"):
        if corrections.get(name) is not True:
            raise ValueError(f"2D metadata does not confirm {name} correction for {item.relative_path}")
    for name in ("mask", "solid_angle", "polarization"):
        if corrections.get(name) is not False:
            raise ValueError(f"2D image already applies {name}; refusing double correction")
    recommended = metadata.get("recommended_reintegration", {})
    do_not_repeat = recommended.get("do_not_repeat")
    if (
        not isinstance(do_not_repeat, list)
        or len(do_not_repeat) != len(DO_NOT_REPEAT)
        or set(do_not_repeat) != DO_NOT_REPEAT
    ):
        raise ValueError(f"2D reintegration contract mismatch for {item.relative_path}")
    if "dark" not in recommended or recommended["dark"] is not None:
        raise ValueError(f"2D reintegration dark must be null for {item.relative_path}")
    if "flat" not in recommended or recommended["flat"] is not None:
        raise ValueError(f"2D reintegration flat must be null for {item.relative_path}")
    normalization = recommended.get("normalization_factor")
    if isinstance(normalization, bool) or normalization != 1.0:
        raise ValueError(f"2D reintegration normalization must be 1 for {item.relative_path}")
    if recommended.get("correctSolidAngle") is not True:
        raise ValueError(
            f"2D reintegration correctSolidAngle must be true for {item.relative_path}"
        )
    if (
        "polarization_factor" not in recommended
        or recommended["polarization_factor"] is not None
    ):
        raise ValueError(
            f"2D reintegration polarization_factor must be null for {item.relative_path}"
        )
    return metadata, _metadata_scientific_sha256(metadata)


def _load_validate_edf(item: _InputRow, metadata: dict[str, Any], mask: np.ndarray) -> np.ndarray:
    try:
        import fabio
    except ImportError as exc:  # pragma: no cover
        raise ImportError("fabio is required for BL19B2 EDF integration") from exc
    image_file = fabio.open(str(item.edf))
    try:
        image = np.asarray(image_file.data)
        header = image_file.header
    finally:
        close = getattr(image_file, "close", None)
        if callable(close):
            close()
    if image.shape != mask.shape:
        raise ValueError(f"EDF/mask shape mismatch for {item.relative_path}: {image.shape} vs {mask.shape}")
    if header.get("ProcessingSignature") != item.processing_signature:
        raise ValueError(f"EDF processing signature mismatch for {item.relative_path}")
    if header.get("FrameSignature") != metadata.get("frame_signature"):
        raise ValueError(f"EDF frame signature mismatch for {item.relative_path}")
    if header.get("IntensityUnit") != "cm^-1":
        raise ValueError(f"EDF intensity unit mismatch for {item.relative_path}")
    expected_array_sha = str(metadata.get("output_image", {}).get("sha256", ""))
    if not expected_array_sha or _array_sha256(image) != expected_array_sha:
        raise ValueError(f"EDF detector array checksum mismatch for {item.relative_path}")
    if np.any(~np.isfinite(image)[mask == 0]):
        raise ValueError(f"EDF contains non-finite unmasked pixels for {item.relative_path}")
    return image


def _integrate(ai: Any, image: np.ndarray, mask: np.ndarray, config: Integrate1DConfig) -> tuple[np.ndarray, np.ndarray]:
    result = ai.integrate1d(
        image,
        config.npt,
        unit=config.unit,
        method=config.method,
        mask=mask,
        correctSolidAngle=True,
        polarization_factor=None,
        dark=None,
        flat=None,
        normalization_factor=1.0,
    )
    q_values = result.radial if hasattr(result, "radial") else result[0]
    intensity_values = result.intensity if hasattr(result, "intensity") else result[1]
    q = np.asarray(q_values, dtype=np.float64)
    intensity = np.asarray(intensity_values, dtype=np.float64)
    if q.shape != (config.npt,) or intensity.shape != (config.npt,):
        raise ValueError("pyFAI returned an unexpected 1D shape")
    if not np.all(np.isfinite(q)) or not np.all(np.isfinite(intensity)) or np.any(np.diff(q) <= 0):
        raise ValueError("pyFAI returned non-finite or non-monotonic 1D data")
    return q, intensity


def _table_bytes(header: list[str], columns: list[np.ndarray]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(tuple(f"{value:.17g}" for value in row) for row in zip(*columns, strict=True))
    return text.getvalue().encode("utf-8")


def run_bl19b2_integrate1d(config: Integrate1DConfig) -> dict[str, Any]:
    """Integrate every successful EDF named by one package's 2D manifest."""
    package = Path(config.package_root).resolve(strict=True)
    if config.npt != 5500 or config.unit != "q_A^-1" or config.method.casefold() != "csr":
        raise ValueError("BL19B2 production integration requires 5500 q_A^-1 points with CSR")
    if config.correct_solid_angle is not True or config.polarization_factor is not None:
        raise ValueError("BL19B2 production integration requires solid-angle=True and no polarization")
    manifest, manifest_bytes, items = _read_manifest(config)
    poni = _package_file(
        Path(config.poni_path or _find_single(package / "config" / "geometry", "*.poni", "PONI")),
        package,
        "PONI",
    )
    default_mask = package / "masks" / "bl19b2_mask.npy"
    if not default_mask.is_file():
        default_mask = _find_single(package / "masks", "*.edf", "mask")
    mask_path = _package_file(Path(config.mask_path or default_mask), package, "mask")
    mask = _load_mask(mask_path)
    poni_sha256 = _file_sha256(poni)
    mask_array_sha256 = _mask_checksum(mask)
    validated_inputs: dict[Path, tuple[dict[str, Any], str, str]] = {}
    selection_rows: list[dict[str, str]] = []
    for item in items:
        metadata, metadata_scientific_sha = _validate_metadata(
            item,
            mask_path,
            mask_checksum_sha256=mask_array_sha256,
            poni_path=poni,
            poni_sha256=poni_sha256,
        )
        edf_sha = _file_sha256(item.edf)
        recorded_edf_sha = str(metadata.get("outputs", {}).get("edf_sha256", ""))
        if not recorded_edf_sha or edf_sha != recorded_edf_sha:
            raise ValueError(f"EDF file checksum mismatch for {item.relative_path}")
        validated_inputs[item.relative_path] = (
            metadata,
            metadata_scientific_sha,
            edf_sha,
        )
        selection_rows.append(
            {
                "relative_path": item.relative_path.as_posix(),
                "edf": item.edf.relative_to(package).as_posix(),
                "metadata": item.metadata.relative_to(package).as_posix(),
                "processing_signature": item.processing_signature,
                "edf_sha256": edf_sha,
                "metadata_scientific_sha256": metadata_scientific_sha,
            }
        )
    selection_doc = {
        "schema": "saxsabs.bl19b2_integrate1d.input_selection.v1",
        "frames": selection_rows,
    }
    selection_bytes = _json_bytes(selection_doc)
    signature_payload = {
        "schema": SCHEMA_VERSION,
        "input_selection_sha256": _sha256_bytes(selection_bytes),
        "poni_sha256": poni_sha256,
        "mask_file_sha256": _file_sha256(mask_path),
        "mask_array_sha256": mask_array_sha256,
        "npt": config.npt,
        "unit": config.unit,
        "method": "csr",
        "correctSolidAngle": True,
        "polarization_factor": None,
        "dark": None,
        "flat": None,
        "normalization_factor": 1.0,
        "do_not_repeat": sorted(DO_NOT_REPEAT),
        "pyFAI_version": _version("pyFAI"),
    }
    run_signature = _canonical_hash(signature_payload)
    out = config.output_root()
    existing_files = list(out.rglob("*")) if out.exists() else []
    existing_files = [path for path in existing_files if path.is_file()]
    signature_file = out / "config" / "run_signature.json"
    manifest_snapshot = out / "manifests" / "input_2d_processing_manifest.csv"
    selection_snapshot = out / "manifests" / "input_2d_selection.json"
    if existing_files and not config.resume:
        raise FileExistsError(f"integration output exists and resume=False: {out}")
    if existing_files and not signature_file.is_file():
        raise ValueError("existing integration output has no run signature; refusing overwrite")
    if existing_files and not manifest_snapshot.is_file():
        raise ValueError("existing integration output has no raw manifest snapshot")
    if existing_files and not selection_snapshot.is_file():
        raise ValueError("existing integration output has no canonical selection snapshot")
    signature_doc = {"schema": SCHEMA_VERSION, "run_signature": run_signature, "payload": signature_payload}
    _write_new_or_verify(signature_file, _json_bytes(signature_doc))
    if manifest_snapshot.exists():
        if not manifest_snapshot.is_file():
            raise ValueError(f"raw manifest snapshot is not a file: {manifest_snapshot}")
        manifest_snapshot_bytes = manifest_snapshot.read_bytes()
    else:
        _write_new_or_verify(manifest_snapshot, manifest_bytes)
        manifest_snapshot_bytes = manifest_bytes
    _write_new_or_verify(selection_snapshot, selection_bytes)
    config_doc = {
        "schema": SCHEMA_VERSION,
        "package_root": str(package),
        "processing_manifest": str(manifest),
        "input_manifest_snapshot_sha256": _sha256_bytes(manifest_snapshot_bytes),
        "poni": str(poni),
        "mask": str(mask_path),
        **signature_payload,
        "run_signature": run_signature,
    }
    _write_new_or_verify(out / "config" / "integration_config.json", _json_bytes(config_doc))

    readme = (
        "# BL19B2 absolute 1D integration\n\n"
        "The EDF inputs were already corrected for dark, background, monitor, transmission, "
        "thickness, and K. This step applies only the package mask and one solid-angle correction "
        "during pyFAI CSR integration. No polarization correction is applied.\n"
    ).encode("utf-8")
    _write_new_or_verify(out / "README.md", readme)

    ai = _load_integrator(poni)
    if _file_sha256(poni) != poni_sha256:
        raise ValueError(f"PONI changed while loading the integrator: {poni}")
    processed = 0
    skipped = 0
    profiles: dict[Path, list[tuple[_InputRow, np.ndarray, np.ndarray, dict[str, Any]]]] = {}
    manifest_rows: list[dict[str, Any]] = []
    for item in items:
        metadata, metadata_scientific_sha, edf_sha = validated_inputs[item.relative_path]
        frame_payload = {
            "run_signature": run_signature,
            "relative_path": item.relative_path.as_posix(),
            "edf_sha256": edf_sha,
            "metadata_scientific_sha256": metadata_scientific_sha,
            "source_processing_signature": item.processing_signature,
            "source_frame_signature": metadata["frame_signature"],
        }
        frame_signature = _canonical_hash(frame_payload)
        profile = out / "profiles" / item.relative_path.parent / f"{item.relative_path.stem}_abs1d_cm-1.csv"
        sidecar = out / "metadata" / item.relative_path.parent / f"{item.relative_path.stem}_abs1d.json"
        if sidecar.exists() and not profile.exists():
            raise ValueError(f"incomplete existing 1D output pair for {item.relative_path}")
        if sidecar.exists():
            side_doc = json.loads(sidecar.read_text(encoding="utf-8"))
            if side_doc.get("frame_signature") != frame_signature:
                raise ValueError(f"1D resume frame signature mismatch for {item.relative_path}")
            if side_doc.get("profile_sha256") != _file_sha256(profile):
                raise ValueError(f"1D resume profile checksum mismatch for {item.relative_path}")
            q, intensity = _read_profile(profile, config.npt)
            skipped += 1
        else:
            image = _load_validate_edf(item, metadata, mask)
            q, intensity = _integrate(ai, image, mask, config)
            profile_data = _profile_bytes(q, intensity)
            _write_new_or_verify(profile, profile_data)
            side_doc = {
                "schema": SCHEMA_VERSION,
                "frame_signature": frame_signature,
                "frame_signature_payload": frame_payload,
                "profile": str(profile),
                "profile_sha256": _sha256_bytes(profile_data),
                "q_points": config.npt,
                "q_min_A^-1": float(q[0]),
                "q_max_A^-1": float(q[-1]),
                "integration_policy": {
                    "unit": "q_A^-1",
                    "method": "csr",
                    "mask": str(mask_path),
                    "correctSolidAngle": True,
                    "polarization_factor": None,
                    "dark": None,
                    "flat": None,
                    "normalization_factor": 1.0,
                    "do_not_repeat": sorted(DO_NOT_REPEAT),
                },
            }
            _write_new_or_verify(sidecar, _json_bytes(side_doc))
            processed += 1
        group = item.relative_path.parent
        profiles.setdefault(group, []).append((item, q, intensity, side_doc))
        manifest_rows.append(
            {
                "relative_path": item.relative_path.as_posix(),
                "status": "complete",
                "input_edf": str(item.edf),
                "input_edf_sha256": edf_sha,
                "input_metadata": str(item.metadata),
                "input_metadata_scientific_sha256": metadata_scientific_sha,
                "source_processing_signature": item.processing_signature,
                "source_frame_signature": metadata["frame_signature"],
                "profile_csv": str(profile),
                "profile_sha256": side_doc["profile_sha256"],
                "integration_frame_signature": frame_signature,
                "q_points": config.npt,
                "q_min_A^-1": f"{q[0]:.17g}",
                "q_max_A^-1": f"{q[-1]:.17g}",
            }
        )

    for group, values in profiles.items():
        q_ref = values[0][1]
        for item, q, _intensity, _sidecar in values[1:]:
            if not np.array_equal(q, q_ref):
                raise ValueError(f"q-axis mismatch within directory {group}: {item.relative_path}")
        intensities = [value[2] for value in values]
        matrix = out / "matrices" / group / "profiles_matrix.csv"
        mean = out / "matrices" / group / "mean_profile.csv"
        column_names = [value[0].relative_path.name for value in values]
        if len(set(column_names)) != len(column_names):
            raise ValueError(f"non-unique matrix column names in {group}")
        _write_new_or_verify(
            matrix,
            _table_bytes(["q_A^-1", *column_names], [q_ref, *intensities]),
        )
        stack = np.vstack(intensities)
        mean_i = np.mean(stack, axis=0)
        std_i = np.std(stack, axis=0, ddof=1) if len(values) > 1 else np.zeros_like(mean_i)
        _write_new_or_verify(
            mean,
            _table_bytes(
                ["q_A^-1", "I_abs_mean_cm^-1", "I_abs_std_cm^-1", "n_frames"],
                [q_ref, mean_i, std_i, np.full(config.npt, len(values), dtype=np.float64)],
            ),
        )

    manifest_buffer = io.StringIO(newline="")
    fieldnames = list(manifest_rows[0])
    writer = csv.DictWriter(manifest_buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(manifest_rows)
    integration_manifest = out / "manifests" / "integration_manifest.csv"
    _write_new_or_verify(integration_manifest, manifest_buffer.getvalue().encode("utf-8"))

    excluded = {out / "manifests" / "checksums.sha256.csv", out / "config" / "completion.json"}
    artifacts = sorted(path for path in out.rglob("*") if path.is_file() and path not in excluded)
    checksum_buffer = io.StringIO(newline="")
    checksum_writer = csv.writer(checksum_buffer, lineterminator="\n")
    checksum_writer.writerow(["relative_path", "sha256", "size_bytes"])
    for artifact in artifacts:
        checksum_writer.writerow(
            [artifact.relative_to(out).as_posix(), _file_sha256(artifact), artifact.stat().st_size]
        )
    checksum_data = checksum_buffer.getvalue().encode("utf-8")
    checksum_path = out / "manifests" / "checksums.sha256.csv"
    _write_new_or_verify(checksum_path, checksum_data)
    completion = {
        "schema": SCHEMA_VERSION,
        "run_signature": run_signature,
        "frames": len(items),
        "directories": len(profiles),
        "checksums_manifest": str(checksum_path),
        "checksums_manifest_sha256": _sha256_bytes(checksum_data),
    }
    _write_new_or_verify(out / "config" / "completion.json", _json_bytes(completion))
    return {
        "status": "complete",
        "package_root": str(package),
        "output_root": str(out),
        "run_signature": run_signature,
        "frames": len(items),
        "directories": len(profiles),
        "processed": processed,
        "skipped": skipped,
        "manifest": str(integration_manifest),
        "checksums": str(checksum_path),
    }
