import json
from pathlib import Path

import numpy as np
import pytest

from saxsabs.io.calibrated2d import (
    Calibrated2DExportConfig,
    build_absolute_detector_image,
    make_sample_id,
    write_calibrated2d_package,
)


def test_build_absolute_detector_image_applies_k_thickness_and_flat():
    img_net = np.array([[2.0, 4.0], [6.0, 8.0]], dtype=float)
    flat = np.array([[1.0, 2.0], [0.0, np.nan]], dtype=float)

    out = build_absolute_detector_image(
        img_net,
        k_factor=3.0,
        thickness_cm=2.0,
        flat=flat,
        apply_flat=True,
    )

    expected = np.array([[3.0, 3.0], [np.nan, np.nan]], dtype=float)
    np.testing.assert_allclose(out, expected, equal_nan=True)


def test_calibrated2d_helpers_are_available_from_top_level_package():
    import saxsabs

    assert saxsabs.build_absolute_detector_image is build_absolute_detector_image
    assert saxsabs.write_calibrated2d_package is write_calibrated2d_package


def test_write_calibrated2d_package_rejects_unsafe_hashed_sample_id(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni_version: 2\nDetector: Detector\n", encoding="utf-8")
    raw = tmp_path / "raw.tif"
    raw.write_text("placeholder", encoding="utf-8")
    root = tmp_path / "processed_calibrated_2d"

    config = Calibrated2DExportConfig(
        root_dir=root,
        sample_id="../unsafe_12345678",
        raw_sample_path=raw,
        poni_path=poni,
        image=np.ones((2, 2), dtype=float),
    )

    with pytest.raises(ValueError, match="sample_id"):
        write_calibrated2d_package(config)

    assert not root.exists()


@pytest.mark.parametrize(
    ("image", "error_match"),
    [
        (np.empty((0, 2), dtype=float), "non-empty 2-D"),
        (np.array([[np.nan, np.inf], [np.nan, 1.0]], dtype=float), "non-finite"),
    ],
)
def test_write_calibrated2d_package_rejects_scientifically_unsafe_image_data(
    tmp_path: Path,
    image: np.ndarray,
    error_match: str,
):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni_version: 2\nDetector: Detector\n", encoding="utf-8")
    raw = tmp_path / "raw.tif"
    raw.write_text("placeholder", encoding="utf-8")
    root = tmp_path / "processed_calibrated_2d"

    config = Calibrated2DExportConfig(
        root_dir=root,
        sample_id="sample001",
        raw_sample_path=raw,
        poni_path=poni,
        image=image,
    )

    with pytest.raises(ValueError, match=error_match):
        write_calibrated2d_package(config)

    assert not root.exists()


def test_write_calibrated2d_package_rejects_float32_overflow_after_cast(tmp_path: Path):
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni_version: 2\nDetector: Detector\n", encoding="utf-8")
    raw = tmp_path / "raw.tif"
    raw.write_text("placeholder", encoding="utf-8")
    root = tmp_path / "processed_calibrated_2d"

    config = Calibrated2DExportConfig(
        root_dir=root,
        sample_id="sample001",
        raw_sample_path=raw,
        poni_path=poni,
        image=np.full((2, 2), 1e100, dtype=np.float64),
        dtype="float32",
    )

    with pytest.raises(ValueError, match="dtype conversion|non-finite"):
        write_calibrated2d_package(config)

    assert not root.exists()


def test_write_calibrated2d_package_writes_edf_mask_poni_and_metadata(tmp_path: Path):
    fabio = pytest.importorskip("fabio", reason="fabio is required for EDF calibrated 2D export")

    src_a = tmp_path / "run_a" / "sample001.tif"
    src_b = tmp_path / "run_b" / "sample001.tif"
    src_a.parent.mkdir()
    src_b.parent.mkdir()
    src_a.write_text("placeholder", encoding="utf-8")
    src_b.write_text("placeholder", encoding="utf-8")
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni_version: 2\nDetector: Detector\n", encoding="utf-8")

    image = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float)
    mask = np.array([[False, True], [False, False]])
    sample_id = make_sample_id("sample001", src_a)
    other_sample_id = make_sample_id("sample001", src_b)

    assert sample_id != other_sample_id

    config = Calibrated2DExportConfig(
        root_dir=tmp_path / "processed_calibrated_2d",
        sample_id=sample_id,
        raw_sample_path=src_a,
        poni_path=poni,
        image=image,
        mask=mask,
        dtype="float32",
        overwrite=False,
        metadata={
            "normalization": {"mode": "rate", "formula": "exp * I0 * T"},
            "integration_policy": {
                "correctSolidAngle": True,
                "polarization_factor": None,
                "flat_applied_in_image": True,
                "mask_convention": "pyFAI: 0=valid, 1=masked",
            },
        },
    )

    result = write_calibrated2d_package(config)

    assert result.image_path.exists()
    assert result.mask_npy_path.exists()
    assert result.mask_edf_path.exists()
    assert result.poni_path.exists()
    assert result.metadata_path.exists()
    assert result.manifest_row["sample_id"] == sample_id

    written = fabio.open(str(result.image_path)).data
    assert written.dtype == np.float32
    np.testing.assert_allclose(written, image.astype(np.float32))

    loaded_mask = np.load(result.mask_npy_path)
    assert loaded_mask.dtype == np.uint8
    np.testing.assert_array_equal(loaded_mask, np.array([[0, 1], [0, 0]], dtype=np.uint8))

    meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert meta["schema"] == "saxsabs.calibrated2d.v1"
    assert meta["image_type"] == "detector_space_absolute_calibrated_net_image"
    assert meta["intensity_unit"] == "cm^-1"
    assert meta["files"]["raw_sample"].startswith(f"{src_a.name}#")
    assert str(src_a) not in meta["files"]["raw_sample"]
    assert result.manifest_row["raw_sample"] == meta["files"]["raw_sample"]
    assert meta["files"]["calibrated_image"].startswith("../images/")
    assert meta["files"]["poni"].startswith("../geometry/")
    assert meta["files"]["mask_npy"].startswith("../masks/")
    assert meta["corrections_applied_in_image"]["absolute_k"] is True
    assert meta["recommended_pyfai_reintegration"]["normalization_factor"] == 1.0


def test_write_calibrated2d_package_allows_absolute_raw_sample_path_opt_in(tmp_path: Path):
    pytest.importorskip("fabio", reason="fabio is required for EDF calibrated 2D export")

    raw = tmp_path / "run_a" / "sample001.tif"
    raw.parent.mkdir()
    raw.write_text("placeholder", encoding="utf-8")
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni_version: 2\nDetector: Detector\n", encoding="utf-8")

    config = Calibrated2DExportConfig(
        root_dir=tmp_path / "processed_calibrated_2d",
        sample_id="sample001",
        raw_sample_path=raw,
        poni_path=poni,
        image=np.ones((2, 2), dtype=float),
        raw_sample_path_mode="absolute",
    )

    result = write_calibrated2d_package(config)
    meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert meta["files"]["raw_sample"] == str(raw)
    assert result.manifest_row["raw_sample"] == str(raw)


def test_write_calibrated2d_package_allows_configured_finite_fraction_threshold(tmp_path: Path):
    pytest.importorskip("fabio", reason="fabio is required for EDF calibrated 2D export")

    raw = tmp_path / "run_a" / "sample001.tif"
    raw.parent.mkdir()
    raw.write_text("placeholder", encoding="utf-8")
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni_version: 2\nDetector: Detector\n", encoding="utf-8")

    config = Calibrated2DExportConfig(
        root_dir=tmp_path / "processed_calibrated_2d",
        sample_id="sample001",
        raw_sample_path=raw,
        poni_path=poni,
        image=np.array([[1.0, 2.0], [3.0, np.nan]], dtype=float),
        mask=np.array([[0, 0], [0, 1]], dtype=np.uint8),
        min_finite_fraction=0.75,
    )

    result = write_calibrated2d_package(config)
    meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert meta["qc"]["finite_fraction"] == pytest.approx(0.75)


def test_real_float32_export_reopens_and_reintegrates_like_direct_absolute_2d(
    tmp_path: Path,
):
    fabio = pytest.importorskip("fabio", reason="fabio is required for EDF round-trip")
    pyfai = pytest.importorskip("pyFAI", reason="pyFAI is required for reintegration")
    from pyFAI.integrator.azimuthal import AzimuthalIntegrator

    raw = tmp_path / "raw" / "sample001.tif"
    raw.parent.mkdir()
    raw.write_bytes(b"independent synthetic raw identity")

    shape = (64, 64)
    yy, xx = np.indices(shape, dtype=np.float64)
    img_net = 1.5 + 0.025 * xx + 0.04 * yy + 0.15 * np.sin(xx / 6.0)
    mask = np.zeros(shape, dtype=np.uint8)
    mask[:3, :] = 1
    mask[30:34, 30:34] = 1
    k_factor = 2.5
    thickness_cm = 0.2
    image_abs = build_absolute_detector_image(
        img_net,
        k_factor=k_factor,
        thickness_cm=thickness_cm,
        apply_flat=False,
    )

    ai = AzimuthalIntegrator(
        dist=0.2,
        poni1=0.0032,
        poni2=0.0032,
        pixel1=1.0e-4,
        pixel2=1.0e-4,
        wavelength=1.0e-10,
    )
    source_poni = tmp_path / "source_geometry.poni"
    ai.save(str(source_poni))
    policy = {
        "correctSolidAngle": True,
        "polarization_factor": 0.95,
        "flat_applied_in_image": False,
        "mask_convention": "pyFAI: 0=valid, 1=masked",
    }

    result = write_calibrated2d_package(
        Calibrated2DExportConfig(
            root_dir=tmp_path / "processed_calibrated_2d",
            sample_id="sample001",
            raw_sample_path=raw,
            poni_path=source_poni,
            image=image_abs,
            mask=mask,
            dtype="float32",
            metadata={"integration_policy": policy},
        )
    )

    image_handle = fabio.open(str(result.image_path))
    try:
        reopened_abs = np.asarray(image_handle.data).copy()
        reopened_header = dict(image_handle.header)
    finally:
        image_handle.close()
    mask_handle = fabio.open(str(result.mask_edf_path))
    try:
        reopened_mask_edf = np.asarray(mask_handle.data).copy()
    finally:
        mask_handle.close()

    reopened_mask_npy = np.load(result.mask_npy_path, allow_pickle=False)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    metadata_dir = result.metadata_path.parent
    assert reopened_abs.dtype == np.float32
    assert reopened_header["SAXSAbsSchema"] == "saxsabs.calibrated2d.v1"
    np.testing.assert_array_equal(reopened_mask_npy, mask)
    np.testing.assert_array_equal(reopened_mask_edf, mask)
    assert result.poni_path.read_bytes() == source_poni.read_bytes()
    assert (metadata_dir / metadata["files"]["calibrated_image"]).resolve() == (
        result.image_path.resolve()
    )
    assert (metadata_dir / metadata["files"]["poni"]).resolve() == result.poni_path.resolve()
    assert (metadata_dir / metadata["files"]["mask_npy"]).resolve() == (
        result.mask_npy_path.resolve()
    )
    recommended = metadata["recommended_pyfai_reintegration"]
    assert recommended["correctSolidAngle"] is True
    assert recommended["polarization_factor"] == pytest.approx(0.95)
    assert recommended["normalization_factor"] == pytest.approx(1.0)

    integration_kwargs = {
        "mask": mask,
        "correctSolidAngle": policy["correctSolidAngle"],
        "polarization_factor": policy["polarization_factor"],
    }
    direct = ai.integrate1d(
        image_abs,
        48,
        unit="q_A^-1",
        **integration_kwargs,
    )
    reopened_ai = pyfai.load(str(result.poni_path))
    regenerated = reopened_ai.integrate1d(
        reopened_abs,
        48,
        unit="q_A^-1",
        mask=reopened_mask_npy,
        correctSolidAngle=recommended["correctSolidAngle"],
        polarization_factor=recommended["polarization_factor"],
    )

    np.testing.assert_allclose(regenerated.radial, direct.radial, rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(
        regenerated.intensity,
        direct.intensity,
        rtol=3e-6,
        atol=2e-6,
    )
