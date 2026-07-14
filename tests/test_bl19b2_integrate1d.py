from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from saxsabs.workflows import bl19b2_integrate1d as integration


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_package(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "package"
    rel = Path("problem") / "sample_00001.tif"
    edf = package / "images_edf" / rel.parent / "sample_00001_abs2d_cm-1.edf"
    metadata = package / "metadata" / rel.parent / "sample_00001_abs2d.json"
    mask = package / "masks" / "bl19b2_mask.npy"
    poni = package / "config" / "geometry" / "geometry.poni"
    manifest = package / "manifests" / "processing_manifest.csv"
    for path in (edf, metadata, mask, poni, manifest):
        path.parent.mkdir(parents=True, exist_ok=True)
    edf.write_bytes(b"stable synthetic EDF")
    np.save(mask, np.zeros((2, 2), dtype=np.uint8))
    poni.write_text("synthetic poni\n", encoding="utf-8")
    metadata.write_text(
        json.dumps(
            {
                "schema": "saxsabs.bl19b2_abs2d.v4",
                "processing_signature": "2d-signature",
                "processing_signature_payload": {
                    "safe_poni_checksum_sha256": _sha(poni)
                },
                "frame_signature": "2d-frame-signature",
                "intensity_unit": "cm^-1",
                "outputs": {"edf": str(edf), "edf_sha256": _sha(edf)},
                "output_image": {"sha256": "validated-by-test-double"},
                "mask": {
                    "npy": str(mask),
                    "checksum_sha256": integration._mask_checksum(
                        np.load(mask, allow_pickle=False)
                    ),
                },
                "geometry": {"poni": str(poni)},
                "corrections_applied_in_image": {
                    "dark": True,
                    "background": True,
                    "monitor": True,
                    "transmission": True,
                    "absolute_k": True,
                    "thickness": True,
                    "mask": False,
                    "solid_angle": False,
                    "polarization": False,
                },
                "recommended_reintegration": {
                    "dark": None,
                    "flat": None,
                    "normalization_factor": 1.0,
                    "correctSolidAngle": True,
                    "polarization_factor": None,
                    "do_not_repeat": [
                        "dark",
                        "background",
                        "transmission",
                        "monitor",
                        "thickness",
                        "K",
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["relative_path", "status", "edf", "metadata", "processing_signature"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "relative_path": rel,
                "status": "processed",
                "edf": edf,
                "metadata": metadata,
                "processing_signature": "2d-signature",
            }
        )
    return package, manifest


def test_integration_applies_only_deferred_mask_and_solid_angle_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package, _manifest = _build_package(tmp_path)
    calls: list[dict[str, object]] = []

    class FakeIntegrator:
        def integrate1d(self, image, npt, **kwargs):
            calls.append({"image": np.asarray(image), "npt": npt, **kwargs})
            return SimpleNamespace(
                radial=np.linspace(0.001, 1.0, npt),
                intensity=np.linspace(2.0, 3.0, npt),
            )

    monkeypatch.setattr(integration, "_load_integrator", lambda _path: FakeIntegrator())
    monkeypatch.setattr(
        integration,
        "_load_validate_edf",
        lambda _item, _metadata, _mask: np.arange(4, dtype=np.float32).reshape(2, 2),
    )
    monkeypatch.setattr(integration, "_version", lambda _name: "test-pyfai")

    first = integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))
    assert first["processed"] == 1
    assert first["skipped"] == 0
    assert calls[0]["npt"] == 5500
    assert calls[0]["unit"] == "q_A^-1"
    assert calls[0]["method"] == "csr"
    assert calls[0]["correctSolidAngle"] is True
    assert calls[0]["polarization_factor"] is None
    assert calls[0]["dark"] is None
    assert calls[0]["flat"] is None
    assert calls[0]["normalization_factor"] == 1.0

    profile = package / "integration" / "profiles" / "problem" / "sample_00001_abs1d_cm-1.csv"
    assert profile.read_text(encoding="utf-8").splitlines()[0] == "q_A^-1,I_abs_cm^-1"
    assert (package / "integration" / "matrices" / "problem" / "profiles_matrix.csv").is_file()
    assert (package / "integration" / "matrices" / "problem" / "mean_profile.csv").is_file()
    assert (package / "integration" / "manifests" / "checksums.sha256.csv").is_file()

    second = integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))
    assert second["processed"] == 0
    assert second["skipped"] == 1
    assert len(calls) == 1


def test_resume_uses_canonical_selection_and_scientific_metadata_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package, manifest = _build_package(tmp_path)
    original_manifest = manifest.read_bytes()
    calls = 0

    class FakeIntegrator:
        def integrate1d(self, _image, npt, **_kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                radial=np.linspace(0.001, 1.0, npt),
                intensity=np.linspace(2.0, 3.0, npt),
            )

    monkeypatch.setattr(integration, "_load_integrator", lambda _path: FakeIntegrator())
    monkeypatch.setattr(
        integration,
        "_load_validate_edf",
        lambda _item, _metadata, _mask: np.ones((2, 2), dtype=np.float32),
    )
    monkeypatch.setattr(integration, "_version", lambda _name: "test-pyfai")

    first = integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))
    selection_snapshot = (
        package / "integration" / "manifests" / "input_2d_selection.json"
    ).read_bytes()

    with manifest.open("r", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["status"] = "skipped_existing"
    rows[0]["resume_note"] = "status and non-scientific columns may drift"
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*rows[0]])
        writer.writeheader()
        writer.writerows(rows)

    metadata_path = next((package / "metadata").rglob("*.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["last_resume_validation"] = {
        "validated_at_utc": "2026-07-13T01:02:03+00:00",
        "status": "success_existing",
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    resumed = integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))

    assert resumed["processed"] == 0
    assert resumed["skipped"] == 1
    assert resumed["run_signature"] == first["run_signature"]
    assert calls == 1
    assert (
        package
        / "integration"
        / "manifests"
        / "input_2d_processing_manifest.csv"
    ).read_bytes() == original_manifest
    assert (
        package / "integration" / "manifests" / "input_2d_selection.json"
    ).read_bytes() == selection_snapshot


def test_resume_rejects_any_other_2d_metadata_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package, _manifest = _build_package(tmp_path)

    class FakeIntegrator:
        def integrate1d(self, _image, npt, **_kwargs):
            return SimpleNamespace(
                radial=np.linspace(0.001, 1.0, npt),
                intensity=np.linspace(2.0, 3.0, npt),
            )

    monkeypatch.setattr(integration, "_load_integrator", lambda _path: FakeIntegrator())
    monkeypatch.setattr(
        integration,
        "_load_validate_edf",
        lambda _item, _metadata, _mask: np.ones((2, 2), dtype=np.float32),
    )
    monkeypatch.setattr(integration, "_version", lambda _name: "test-pyfai")
    integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))

    metadata_path = next((package / "metadata").rglob("*.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["scientific_tamper"] = "must change the canonical selection"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="existing integration artifact differs"):
        integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))


@pytest.mark.parametrize("field", ["relative_path", "processing_signature"])
def test_manifest_scientific_selection_changes_fail_closed(
    tmp_path: Path, field: str
):
    package, manifest = _build_package(tmp_path)
    with manifest.open("r", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    rows[0][field] = "other/sample_00001.tif" if field == "relative_path" else "tampered"
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*rows[0]])
        writer.writeheader()
        writer.writerows(rows)

    error = "outputs do not match relative_path" if field == "relative_path" else "signature mismatch"
    with pytest.raises(ValueError, match=error):
        integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))


def test_resume_recovers_matching_profile_without_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package, _manifest = _build_package(tmp_path)
    calls = 0

    class FakeIntegrator:
        def integrate1d(self, _image, npt, **_kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                radial=np.linspace(0.001, 1.0, npt),
                intensity=np.linspace(2.0, 3.0, npt),
            )

    monkeypatch.setattr(integration, "_load_integrator", lambda _path: FakeIntegrator())
    monkeypatch.setattr(
        integration,
        "_load_validate_edf",
        lambda _item, _metadata, _mask: np.ones((2, 2), dtype=np.float32),
    )
    monkeypatch.setattr(integration, "_version", lambda _name: "test-pyfai")
    integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))
    sidecar = (
        package
        / "integration"
        / "metadata"
        / "problem"
        / "sample_00001_abs1d.json"
    )
    sidecar.unlink()

    resumed = integration.run_bl19b2_integrate1d(
        integration.Integrate1DConfig(package)
    )

    assert resumed["processed"] == 1
    assert resumed["skipped"] == 0
    assert calls == 2
    assert sidecar.is_file()


def test_resume_rejects_mismatched_profile_without_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package, _manifest = _build_package(tmp_path)

    class FakeIntegrator:
        def integrate1d(self, _image, npt, **_kwargs):
            return SimpleNamespace(
                radial=np.linspace(0.001, 1.0, npt),
                intensity=np.linspace(2.0, 3.0, npt),
            )

    monkeypatch.setattr(integration, "_load_integrator", lambda _path: FakeIntegrator())
    monkeypatch.setattr(
        integration,
        "_load_validate_edf",
        lambda _item, _metadata, _mask: np.ones((2, 2), dtype=np.float32),
    )
    monkeypatch.setattr(integration, "_version", lambda _name: "test-pyfai")
    integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))
    profile = (
        package
        / "integration"
        / "profiles"
        / "problem"
        / "sample_00001_abs1d_cm-1.csv"
    )
    sidecar = (
        package
        / "integration"
        / "metadata"
        / "problem"
        / "sample_00001_abs1d.json"
    )
    sidecar.unlink()
    profile.write_bytes(profile.read_bytes() + b"0,0\n")

    with pytest.raises(ValueError, match="existing integration artifact differs"):
        integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))
    assert not sidecar.exists()


def test_manifest_rejects_traversal_before_reading_outputs(tmp_path: Path):
    package, manifest = _build_package(tmp_path)
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("problem\\sample_00001.tif", "../sample_00001.tif"), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe relative_path"):
        integration._read_manifest(integration.Integrate1DConfig(package))


@pytest.mark.parametrize(
    ("artifact", "error_match"),
    [
        ("mask", "mask array checksum mismatch"),
        ("poni", "PONI checksum mismatch"),
    ],
)
def test_integration_rejects_replaced_mask_or_poni(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
    error_match: str,
):
    package, _manifest = _build_package(tmp_path)
    if artifact == "mask":
        np.save(
            package / "masks" / "bl19b2_mask.npy",
            np.ones((2, 2), dtype=np.uint8),
        )
    else:
        (package / "config" / "geometry" / "geometry.poni").write_text(
            "replacement poni\n", encoding="utf-8"
        )
    monkeypatch.setattr(integration, "_load_integrator", lambda _path: object())

    with pytest.raises(ValueError, match=error_match):
        integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))


@pytest.mark.parametrize(
    ("field", "value", "error_match"),
    [
        ("correctSolidAngle", False, "correctSolidAngle must be true"),
        ("polarization_factor", 0.95, "polarization_factor must be null"),
        ("dark", "dark.edf", "dark must be null"),
        ("flat", "flat.edf", "flat must be null"),
        ("normalization_factor", 2.0, "normalization must be 1"),
    ],
)
def test_integration_rejects_tampered_reintegration_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    error_match: str,
):
    package, _manifest = _build_package(tmp_path)
    metadata_path = next((package / "metadata").rglob("*.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["recommended_reintegration"][field] = value
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(integration, "_load_integrator", lambda _path: object())

    with pytest.raises(ValueError, match=error_match):
        integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))


@pytest.mark.parametrize(
    ("field", "error_match"),
    [
        ("mask_checksum", "mask array checksum mismatch"),
        ("poni_pointer", "PONI pointer mismatch"),
        ("poni_checksum", "PONI checksum mismatch"),
    ],
)
def test_integration_rejects_tampered_2d_input_binding_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    error_match: str,
):
    package, _manifest = _build_package(tmp_path)
    metadata_path = next((package / "metadata").rglob("*.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if field == "mask_checksum":
        metadata["mask"]["checksum_sha256"] = "tampered"
    elif field == "poni_pointer":
        metadata["geometry"]["poni"] = str(package / "other.poni")
    else:
        metadata["processing_signature_payload"][
            "safe_poni_checksum_sha256"
        ] = "tampered"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(integration, "_load_integrator", lambda _path: object())

    with pytest.raises(ValueError, match=error_match):
        integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))


def test_manifest_rejects_unlisted_recursive_edf(tmp_path: Path):
    package, _manifest = _build_package(tmp_path)
    extra = package / "images_edf" / "problem" / "nested" / "unlisted_abs2d_cm-1.edf"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"unlisted")
    with pytest.raises(ValueError, match="manifest/EDF tree mismatch"):
        integration._read_manifest(integration.Integrate1DConfig(package))


def test_resume_rejects_tampered_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    package, _manifest = _build_package(tmp_path)

    class FakeIntegrator:
        def integrate1d(self, _image, npt, **_kwargs):
            return SimpleNamespace(
                radial=np.linspace(0.001, 1.0, npt), intensity=np.ones(npt)
            )

    monkeypatch.setattr(integration, "_load_integrator", lambda _path: FakeIntegrator())
    monkeypatch.setattr(
        integration,
        "_load_validate_edf",
        lambda _item, _metadata, _mask: np.ones((2, 2), dtype=np.float32),
    )
    monkeypatch.setattr(integration, "_version", lambda _name: "test-pyfai")
    integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))
    profile = package / "integration" / "profiles" / "problem" / "sample_00001_abs1d_cm-1.csv"
    profile.write_text(profile.read_text(encoding="utf-8") + "0,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="profile checksum mismatch"):
        integration.run_bl19b2_integrate1d(integration.Integrate1DConfig(package))
