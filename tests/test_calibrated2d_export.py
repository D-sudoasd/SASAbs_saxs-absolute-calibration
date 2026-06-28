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
    assert meta["files"]["raw_sample"] == str(src_a)
    assert meta["files"]["calibrated_image"].startswith("../images/")
    assert meta["files"]["poni"].startswith("../geometry/")
    assert meta["files"]["mask_npy"].startswith("../masks/")
    assert meta["corrections_applied_in_image"]["absolute_k"] is True
    assert meta["recommended_pyfai_reintegration"]["normalization_factor"] == 1.0
