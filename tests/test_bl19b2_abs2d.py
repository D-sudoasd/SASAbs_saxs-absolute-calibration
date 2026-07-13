import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

import saxsabs.workflows.bl19b2_abs2d as bl19b2
from saxsabs.workflows.bl19b2_abs2d import (
    BL19B2Header,
    BL19B2Abs2DConfig,
    MaskInfo,
    ReferencePaths,
    SCHEMA_VERSION,
    StandardCalibration,
    _frame_qc_row_from_metadata,
    build_combined_mask,
    build_output_paths,
    build_rerun_command,
    classify_sample_frame,
    estimate_thickness_cm,
    find_reference_paths,
    format_code_state_text,
    is_sample_tiff,
    parse_bl19b2_description,
    parse_pydidas_cali_yaml,
    run_bl19b2_abs2d,
    subtract_dark_for_exposure,
    validate_config,
    write_edf_image,
    write_pydidas_poni,
    write_provenance_package,
)


def _write_pydidas_cali(path: Path, **overrides: str) -> None:
    values = {
        "detector_dist": "3.0481453478823366",
        "detector_name": "Pilatus 2M",
        "detector_poni1": "0.12616381951025174",
        "detector_poni2": "0.12722516651641888",
        "detector_pxsizex": "172.0",
        "detector_pxsizey": "172.0",
        "detector_rot1": "0.0",
        "detector_rot2": "0.0",
        "detector_rot3": "0.0",
        "xray_wavelength": "0.413280661444",
    }
    values.update({key: str(value) for key, value in overrides.items()})
    path.write_text(
        "\n".join(f"{key}: {value}" for key, value in values.items()),
        encoding="utf-8",
    )


def _write_required_reference_files(ref: Path) -> None:
    ref.mkdir(parents=True)
    for name in ("dark001.tif", "BG001.tif", "GC001.tif"):
        (ref / name).write_bytes(b"placeholder")


def test_parse_bl19b2_description_extracts_header_fields():
    text = (
        "# Pixel_size 172e-6 m x 172e-6 m\n"
        "# Exposure_time 120.0000000 s\n"
        "# MON=3822.4\n"
        "# ABS=0.213587\n"
        "# E0=30.000086\n"
        "# CAML=3063\n"
        "# DRTX=687.766613\n"
        "# DRTY=782.668375\n"
    )

    header = parse_bl19b2_description(text)

    assert header.exposure_s == 120.0
    assert header.monitor == 3822.4
    assert header.transmission == 0.213587
    assert header.energy_kev == 30.000086
    assert header.distance_mm == 3063.0
    assert header.beam_x_px == 687.766613
    assert header.beam_y_px == 782.668375
    assert header.pixel_size_m == 172e-6


def test_estimate_thickness_uses_beer_lambert_mu():
    thickness = estimate_thickness_cm(0.213587, mu_cm_inv=20.2)

    assert thickness == np.float64(-np.log(0.213587) / 20.2)


def test_estimate_thickness_rejects_pathological_near_unity_transmission():
    with pytest.raises(ValueError, match="ill-conditioned"):
        estimate_thickness_cm(0.999999, mu_cm_inv=20.2)


def test_estimate_thickness_rejects_pathological_near_zero_transmission():
    with pytest.raises(ValueError, match="ill-conditioned"):
        estimate_thickness_cm(0.000001, mu_cm_inv=20.2)
    with pytest.raises(ValueError, match="both T and attenuation"):
        estimate_thickness_cm(
            0.01,
            mu_cm_inv=20.2,
            transmission_abs_uncertainty=0.004,
        )


def test_compute_norm_factor_distinguishes_rate_and_integrated_monitor_modes():
    assert bl19b2.compute_norm_factor(10.0, 100.0, 0.5, monitor_mode="rate") == 500.0
    assert bl19b2.compute_norm_factor(10.0, 100.0, 0.5, monitor_mode="integrated") == 50.0


def test_background_transmission_is_qc_only_and_blocks_material_deviation():
    used, warnings = bl19b2._background_transmission(BL19B2Header(transmission=1.01619))

    assert used == 1.0
    assert any("not applied" in item for item in warnings)
    with pytest.raises(ValueError, match="background definition"):
        bl19b2._background_transmission(BL19B2Header(transmission=0.95))


class _FakeDetector:
    shape = (2, 3)
    pixel1 = 172e-6
    pixel2 = 172e-6


class _FakeIntegrator:
    detector = _FakeDetector()
    dist = 3.0
    wavelength = (12.398419843320026 / 30.0) * 1e-10

    @staticmethod
    def getFit2D() -> dict[str, float]:
        return {"centerX": 1.0, "centerY": 0.5}


def test_instrument_consistency_checks_header_against_standard_and_poni():
    standard = BL19B2Header(
        energy_kev=30.0,
        distance_mm=3000.0,
        pixel_size_m=172e-6,
        beam_x_px=1.0,
        beam_y_px=0.5,
    )
    sample = BL19B2Header(
        energy_kev=30.01,
        distance_mm=3001.0,
        pixel_size_m=172e-6,
        beam_x_px=1.2,
        beam_y_px=0.5,
    )

    warnings = bl19b2.validate_instrument_consistency(
        sample,
        image_shape=(2, 3),
        integrator=_FakeIntegrator(),
        label="sample",
        reference_header=standard,
    )

    assert warnings == ()


def test_instrument_consistency_blocks_shape_and_header_mismatch():
    header = BL19B2Header(energy_kev=29.0)

    with pytest.raises(ValueError, match="shape mismatch"):
        bl19b2.validate_instrument_consistency(
            header,
            image_shape=(3, 3),
            integrator=_FakeIntegrator(),
            label="sample",
        )
    with pytest.raises(ValueError, match="energy_kev vs PONI"):
        bl19b2.validate_instrument_consistency(
            header,
            image_shape=(2, 3),
            integrator=_FakeIntegrator(),
            label="sample",
        )


def test_instrument_consistency_rejects_missing_header_fields():
    with pytest.raises(ValueError, match="is missing"):
        bl19b2.validate_instrument_consistency(
            BL19B2Header(),
            image_shape=(2, 3),
            integrator=_FakeIntegrator(),
            label="sample",
        )


def test_classify_sample_frame_rejects_missing_or_unphysical_transmission():
    ok = classify_sample_frame(BL19B2Header(exposure_s=10.0, monitor=100.0, transmission=0.5))
    missing = classify_sample_frame(BL19B2Header(exposure_s=10.0, monitor=None, transmission=0.5))
    too_high = classify_sample_frame(BL19B2Header(exposure_s=10.0, monitor=100.0, transmission=1.01))

    assert ok.status == "ok"
    assert missing.status == "rejected"
    assert "MON" in missing.reason
    assert too_high.status == "rejected"
    assert "transmission" in too_high.reason


def test_is_sample_tiff_excludes_reference_and_generated_paths(tmp_path: Path):
    root = tmp_path / "dat001"
    sample = root / "3#_sample" / "frame_001.tif"
    ref = root / "reference_saxs" / "GC001.tif"
    csv_output = root / "3#_sample" / "csv_output" / "frame_001.tif"
    processed = root / "3#_sample" / "processed_robust_1d_full" / "frame_001.tif"

    assert is_sample_tiff(sample, root)
    assert not is_sample_tiff(ref, root)
    assert not is_sample_tiff(csv_output, root)
    assert not is_sample_tiff(processed, root)


def test_build_output_paths_preserves_relative_folder_and_uses_abs2d_suffix(tmp_path: Path):
    root = tmp_path / "dat001"
    out_root = tmp_path / "dat001_absolute_corrected_2D"
    source = root / "10#_NO_50SWAGED_NTE_400-2" / "frame_001.tif"

    paths = build_output_paths(source, input_root=root, output_root=out_root)

    assert paths.h5 == out_root / "images_h5" / "10#_NO_50SWAGED_NTE_400-2" / (
        "frame_001_abs2d_cm-1.h5"
    )
    assert paths.edf.name == "frame_001_abs2d_cm-1.edf"
    assert paths.metadata.name == "frame_001_abs2d.json"
    assert paths.preview.name == "frame_001_preview.png"


def test_parse_pydidas_cali_yaml_converts_geometry_units(tmp_path: Path):
    mask = tmp_path / "Mask.edf"
    cali = tmp_path / "Cali.yaml"
    cali.write_text(
        "\n".join(
            [
                "detector_dist: 3.0481453478823366",
                f"detector_mask_file: {mask}",
                "detector_name: Pilatus 2M",
                "detector_poni1: 0.12616381951025174",
                "detector_poni2: 0.12722516651641888",
                "detector_pxsizex: 172.0",
                "detector_pxsizey: 172.0",
                "detector_rot1: 0.0",
                "detector_rot2: 0.0",
                "detector_rot3: 0.0",
                "xray_wavelength: 0.413280661444",
            ]
        ),
        encoding="utf-8",
    )

    geometry = parse_pydidas_cali_yaml(cali)

    assert geometry.distance_m == 3.0481453478823366
    assert geometry.poni1_m == 0.12616381951025174
    assert geometry.poni2_m == 0.12722516651641888
    assert geometry.pixel1_m == 0.000172
    assert geometry.pixel2_m == 0.000172
    assert geometry.wavelength_m == 4.13280661444e-11
    assert geometry.mask_path == mask


@pytest.mark.parametrize("raw_mask", [".", "", "none", "null", "None", "NULL"])
def test_parse_pydidas_cali_yaml_treats_mask_sentinels_as_no_yaml_mask(
    tmp_path: Path,
    raw_mask: str,
):
    cali = tmp_path / "Cali.yaml"
    _write_pydidas_cali(cali, detector_mask_file=raw_mask)

    geometry = parse_pydidas_cali_yaml(cali)

    assert geometry.mask_path is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("detector_pxsizex", "0"),
        ("detector_pxsizey", "-172.0"),
        ("detector_dist", "0"),
        ("xray_wavelength", "-0.413280661444"),
    ],
)
def test_parse_pydidas_cali_yaml_rejects_nonpositive_required_geometry_values(
    tmp_path: Path,
    field: str,
    value: str,
):
    cali = tmp_path / "Cali.yaml"
    _write_pydidas_cali(cali, **{field: value})

    with pytest.raises(ValueError, match=field):
        parse_pydidas_cali_yaml(cali)


def test_write_pydidas_poni_uses_pyfai_units(tmp_path: Path):
    cali = tmp_path / "Cali.yaml"
    cali.write_text(
        "\n".join(
            [
                "detector_dist: 3.0481453478823366",
                "detector_name: Pilatus 2M",
                "detector_poni1: 0.12616381951025174",
                "detector_poni2: 0.12722516651641888",
                "detector_pxsizex: 172.0",
                "detector_pxsizey: 172.0",
                "detector_rot1: 0.0",
                "detector_rot2: 0.0",
                "detector_rot3: 0.0",
                "xray_wavelength: 0.413280661444",
            ]
        ),
        encoding="utf-8",
    )
    poni = tmp_path / "BL19B2_SAXS_Califile.poni"

    write_pydidas_poni(cali, poni)

    text = poni.read_text(encoding="utf-8")
    assert "Detector: Pilatus2M" in text
    assert '"pixel1": 0.000172' in text
    assert '"pixel2": 0.000172' in text
    assert "Distance: 3.0481453478823366" in text
    assert "Poni1: 0.12616381951025174" in text
    assert "Poni2: 0.12722516651641888" in text
    assert "Wavelength: 4.13280661444e-11" in text


def test_find_reference_paths_uses_pydidas_mask_when_available(tmp_path: Path):
    root = tmp_path / "dat001"
    ref = root / "reference_saxs"
    _write_required_reference_files(ref)
    mask = ref / "Mask.edf"
    mask.write_bytes(b"mask")
    cali = ref / "Cali.yaml"
    cali.write_text(f"detector_mask_file: {mask}\n", encoding="utf-8")

    refs = find_reference_paths(root, pydidas_cali_yaml=cali)

    assert refs.mask == mask


def test_find_reference_paths_prefers_explicit_mask(tmp_path: Path):
    root = tmp_path / "dat001"
    ref = root / "reference_saxs"
    _write_required_reference_files(ref)
    mask_from_yaml = ref / "Mask.edf"
    explicit_mask = ref / "explicit_mask.edf"
    mask_from_yaml.write_bytes(b"mask")
    explicit_mask.write_bytes(b"explicit")
    cali = ref / "Cali.yaml"
    cali.write_text(f"detector_mask_file: {mask_from_yaml}\n", encoding="utf-8")

    refs = find_reference_paths(root, mask_path=explicit_mask, pydidas_cali_yaml=cali)

    assert refs.mask == explicit_mask


def test_find_reference_paths_accepts_explicit_reference_files(tmp_path: Path):
    root = tmp_path / "dat001"
    ref = root / "reference_saxs"
    ref.mkdir(parents=True)
    dark = ref / "dark_run42.tif"
    background = ref / "empty_cell_run42.tif"
    standard = ref / "glassy_carbon_run42.tif"
    direct = ref / "direct_beam_run42.tif"
    for path in (dark, background, standard, direct):
        path.write_bytes(b"placeholder")

    refs = find_reference_paths(
        root,
        dark_path="reference_saxs/dark_run42.tif",
        background_path=background,
        standard_path=standard,
        direct_path=direct,
    )

    assert refs.dark == dark
    assert refs.background == background
    assert refs.standard == standard
    assert refs.direct == direct


def test_find_reference_paths_treats_yaml_mask_sentinel_as_absent_and_falls_back(
    tmp_path: Path,
):
    root = tmp_path / "dat001"
    ref = root / "reference_saxs"
    _write_required_reference_files(ref)
    fallback_mask = ref / "Mask.edf"
    fallback_mask.write_bytes(b"fallback")
    cali = ref / "Cali.yaml"
    _write_pydidas_cali(cali, detector_mask_file=".")

    refs = find_reference_paths(root, pydidas_cali_yaml=cali)

    assert refs.mask == fallback_mask


def test_find_reference_paths_ignores_yaml_mask_directory_and_falls_back(tmp_path: Path):
    root = tmp_path / "dat001"
    ref = root / "reference_saxs"
    _write_required_reference_files(ref)
    yaml_mask_dir = ref / "mask_directory"
    yaml_mask_dir.mkdir()
    fallback_mask = ref / "Mask.edf"
    fallback_mask.write_bytes(b"fallback")
    cali = ref / "Cali.yaml"
    _write_pydidas_cali(cali, detector_mask_file=str(yaml_mask_dir))

    refs = find_reference_paths(root, pydidas_cali_yaml=cali)

    assert refs.mask == fallback_mask


def test_find_reference_paths_rejects_explicit_mask_directory(tmp_path: Path):
    root = tmp_path / "dat001"
    ref = root / "reference_saxs"
    _write_required_reference_files(ref)
    explicit_mask_dir = ref / "explicit_mask"
    explicit_mask_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="mask.*file"):
        find_reference_paths(root, mask_path=explicit_mask_dir)


def test_find_reference_paths_does_not_return_fallback_mask_directory(tmp_path: Path):
    root = tmp_path / "dat001"
    ref = root / "reference_saxs"
    _write_required_reference_files(ref)
    (ref / "MASK_file.edf").mkdir()

    refs = find_reference_paths(root)

    assert refs.mask is None


def test_frame_qc_row_from_metadata_restores_existing_resume_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "dat001"
    out_root = tmp_path / "dat001_absolute_corrected_2D"
    source = root / "3#_sample" / "frame_001.tif"
    paths = build_output_paths(source, input_root=root, output_root=out_root)
    paths.metadata.parent.mkdir(parents=True)
    paths.preview.parent.mkdir(parents=True)
    paths.preview.write_bytes(b"preview")
    source_identity = {"sha256": "source-sha", "size_bytes": 6, "header": {}}
    frame_signature = bl19b2._frame_signature("sig-1", source_identity)
    monkeypatch.setattr(bl19b2, "_source_identity", lambda path: source_identity)
    monkeypatch.setattr(bl19b2, "_validate_existing_outputs", lambda paths, metadata: None)
    paths.metadata.write_text(
        """
{
  "outputs": {
    "hdf5": "frame_001_abs2d_cm-1.h5",
    "edf": "frame_001_abs2d_cm-1.edf",
    "metadata": "frame_001_abs2d.json",
    "preview": "%s"
  },
  "schema": "%s",
  "formula_version": "%s",
  "processing_signature": "sig-1",
  "frame_signature": "%s",
  "source_identity": {"sha256": "source-sha", "size_bytes": 6, "header": {}},
  "mask": {"npy": "mask.npy"},
  "normalization": {"norm_sample": 10.0, "transmission_abs": 0.5},
  "thickness": {"thickness_cm": 0.034},
  "absolute_calibration": {"k_factor": 11.4},
  "qc": {"finite_fraction": 1.0, "negative_fraction": 0.01},
  "warnings": ["BG ABS=1.01619 recorded for QC only; background transmission is not applied"]
}
"""
        % (
            str(paths.preview).replace("\\", "\\\\"),
            SCHEMA_VERSION,
            bl19b2.FORMULA_VERSION,
            frame_signature,
        ),
        encoding="utf-8",
    )

    row = _frame_qc_row_from_metadata(
        source=source,
        rel=source.relative_to(root),
        paths=paths,
        expected_signature="sig-1",
    )

    assert row is not None
    assert row["status"] == "success_existing"
    assert row["relative_path"] == str(Path("3#_sample") / "frame_001.tif")
    assert row["finite_fraction"] == 1.0
    assert row["k_factor"] == 11.4
    assert "BG ABS" in row["warnings"]


def test_subtract_dark_scales_dark_to_sample_exposure():
    image = np.array([[12.0, 22.0]])
    dark = np.array([[1.0, 2.0]])

    out = subtract_dark_for_exposure(
        image,
        dark,
        image_exposure_s=20.0,
        dark_exposure_s=10.0,
    )

    np.testing.assert_allclose(out, np.array([[10.0, 18.0]]))


def test_subtract_dark_matches_old_formula_when_exposure_is_same():
    image = np.array([[12.0, 22.0]])
    dark = np.array([[1.0, 2.0]])

    out = subtract_dark_for_exposure(
        image,
        dark,
        image_exposure_s=10.0,
        dark_exposure_s=10.0,
    )

    np.testing.assert_allclose(out, image - dark)


def test_bl19b2_uncertainty_budget_matches_independent_fixed_thickness_calculation():
    intensity = np.array([[179.5]])

    budget = bl19b2.compute_bl19b2_uncertainty_budget(
        intensity,
        sample_raw=np.array([[100.0]]),
        background_raw=np.array([[25.0]]),
        dark_raw=np.array([[4.0]]),
        sample_exposure_s=2.0,
        background_exposure_s=4.0,
        dark_exposure_s=1.0,
        norm_sample=10.0,
        norm_background=20.0,
        alpha=0.5,
        k_factor=2.0,
        thickness_cm=0.1,
        transmission=0.5,
        mu_cm_inv=None,
        k_statistical_standard_uncertainty=0.2,
        k_standard_uncertainty=0.5,
        standard_thickness_relative_standard_uncertainty=0.03,
        transmission_abs_uncertainty=0.01,
        monitor_relative_standard_uncertainty=0.01,
        thickness_relative_standard_uncertainty=0.02,
        mu_relative_standard_uncertainty=None,
        alpha_standard_uncertainty=0.1,
        coverage_factor=2.0,
    )

    assert budget.unknown_components == ()
    assert budget.statistical[0, 0] == pytest.approx(20.5487225880)
    assert budget.k[0, 0] == pytest.approx(17.95)
    assert budget.standard[0, 0] == pytest.approx(41.4796498298)
    assert budget.transmission[0, 0] == pytest.approx(3.68)
    assert budget.monitor[0, 0] == pytest.approx(1.8405501895)
    assert budget.thickness[0, 0] == pytest.approx(3.59)
    assert budget.mu[0, 0] == 0.0
    assert budget.alpha[0, 0] == pytest.approx(0.9)
    assert budget.combined_standard_uncertainty[0, 0] == pytest.approx(49.9564007410)
    assert budget.expanded_uncertainty[0, 0] == pytest.approx(99.9128014821)
    config = BL19B2Abs2DConfig(
        input_root=Path("dat001"),
        poni_path=Path("geometry.poni"),
        sample_thickness_cm=0.1,
        monitor_mode="rate",
        transmission_abs_uncertainty=0.01,
        monitor_relative_standard_uncertainty=0.01,
        sample_thickness_relative_standard_uncertainty=0.02,
        alpha_standard_uncertainty=0.1,
        standard_thickness_relative_standard_uncertainty=0.03,
    )
    calibration = StandardCalibration(
        k_factor=2.0,
        k_std=0.2,
        q_min_overlap=0.01,
        q_max_overlap=0.2,
        points_used=4,
        points_total=4,
        standard_thickness_cm=0.1055,
        norm_standard=10.0,
        norm_background=20.0,
        bg_transmission_used=1.0,
        standard_thickness_source="nist_srm3600_certificate",
        k_statistical_standard_uncertainty=0.2,
        k_standard_uncertainty=0.5,
        k_expanded_uncertainty=1.0,
        coverage_factor=2.0,
    )
    summary = bl19b2._frame_uncertainty_metadata(config, calibration, budget)
    assert summary["status"] == "complete"
    assert summary["unknown_components"] == []
    assert summary["combined_standard_uncertainty"]["max"] == pytest.approx(49.9564007410)
    assert summary["datasets"]["combined_standard"].endswith(
        "/uncertainty/combined_standard"
    )


def test_bl19b2_uncertainty_budget_preserves_unknown_beer_lambert_inputs():
    transmission = 0.5
    mu = 20.0
    thickness = -math.log(transmission) / mu
    net = 9.2 - 0.5 * 0.45
    intensity = np.array([[net * 2.0 / thickness]])

    budget = bl19b2.compute_bl19b2_uncertainty_budget(
        intensity,
        sample_raw=np.array([[100.0]]),
        background_raw=np.array([[25.0]]),
        dark_raw=np.array([[4.0]]),
        sample_exposure_s=2.0,
        background_exposure_s=4.0,
        dark_exposure_s=1.0,
        norm_sample=10.0,
        norm_background=20.0,
        alpha=0.5,
        k_factor=2.0,
        thickness_cm=thickness,
        transmission=transmission,
        mu_cm_inv=mu,
        k_statistical_standard_uncertainty=0.2,
        k_standard_uncertainty=None,
        standard_thickness_relative_standard_uncertainty=None,
        transmission_abs_uncertainty=None,
        monitor_relative_standard_uncertainty=None,
        thickness_relative_standard_uncertainty=None,
        mu_relative_standard_uncertainty=None,
        alpha_standard_uncertainty=None,
        coverage_factor=2.0,
    )

    assert set(budget.unknown_components) == {
        "standard",
        "transmission",
        "monitor",
        "mu",
        "alpha",
    }
    assert np.all(budget.thickness == 0.0)
    assert np.all(np.isnan(budget.combined_standard_uncertainty))
    assert np.all(np.isnan(budget.expanded_uncertainty))
    config = BL19B2Abs2DConfig(
        input_root=Path("dat001"),
        poni_path=Path("geometry.poni"),
        mu_cm_inv=mu,
        monitor_mode="rate",
    )
    calibration = StandardCalibration(
        k_factor=2.0,
        k_std=0.2,
        q_min_overlap=0.01,
        q_max_overlap=0.2,
        points_used=4,
        points_total=4,
        standard_thickness_cm=0.1055,
        norm_standard=10.0,
        norm_background=20.0,
        bg_transmission_used=1.0,
        standard_thickness_source="nist_srm3600_certificate",
        k_statistical_standard_uncertainty=0.2,
        k_standard_uncertainty=None,
        k_expanded_uncertainty=None,
        coverage_factor=2.0,
    )
    summary = bl19b2._frame_uncertainty_metadata(config, calibration, budget)
    assert summary["status"] == "partial"
    assert summary["combined_standard_uncertainty"] is None
    assert "monitor" in summary["unknown_components"]


def test_bl19b2_uncertainty_requires_standard_thickness_uncertainty_for_complete_budget():
    budget = bl19b2.compute_bl19b2_uncertainty_budget(
        np.array([[1.0]]),
        sample_raw=np.array([[4.0]]),
        background_raw=np.array([[1.0]]),
        dark_raw=np.array([[0.0]]),
        sample_exposure_s=1.0,
        background_exposure_s=1.0,
        dark_exposure_s=1.0,
        norm_sample=2.0,
        norm_background=2.0,
        alpha=1.0,
        k_factor=2.0,
        thickness_cm=1.0,
        transmission=0.5,
        mu_cm_inv=None,
        k_statistical_standard_uncertainty=0.1,
        k_standard_uncertainty=0.2,
        standard_thickness_relative_standard_uncertainty=None,
        transmission_abs_uncertainty=0.0,
        monitor_relative_standard_uncertainty=0.0,
        thickness_relative_standard_uncertainty=0.0,
        mu_relative_standard_uncertainty=None,
        alpha_standard_uncertainty=0.0,
        coverage_factor=2.0,
    )

    assert "standard" in budget.unknown_components
    assert np.isnan(budget.standard[0, 0])
    assert np.isnan(budget.combined_standard_uncertainty[0, 0])


def test_bl19b2_independent_monitor_uncertainty_keeps_zero_net_pixel_unknown():
    budget = bl19b2.compute_bl19b2_uncertainty_budget(
        np.array([[0.0]]),
        sample_raw=np.array([[4.0]]),
        background_raw=np.array([[4.0]]),
        dark_raw=np.array([[0.0]]),
        sample_exposure_s=1.0,
        background_exposure_s=1.0,
        dark_exposure_s=1.0,
        norm_sample=2.0,
        norm_background=2.0,
        alpha=1.0,
        k_factor=1.0,
        thickness_cm=1.0,
        transmission=0.5,
        mu_cm_inv=None,
        k_statistical_standard_uncertainty=0.0,
        k_standard_uncertainty=0.0,
        standard_thickness_relative_standard_uncertainty=0.0,
        transmission_abs_uncertainty=0.0,
        monitor_relative_standard_uncertainty=0.1,
        thickness_relative_standard_uncertainty=0.0,
        mu_relative_standard_uncertainty=None,
        alpha_standard_uncertainty=0.0,
        coverage_factor=2.0,
    )

    assert "monitor" in budget.unknown_components
    assert np.isnan(budget.monitor[0, 0])
    assert np.isnan(budget.combined_standard_uncertainty[0, 0])


def test_build_combined_mask_unions_user_detector_and_dark_hot_pixels():
    user_mask = np.array([[0, 1], [0, 0]], dtype=np.uint8)
    detector_mask = np.array([[0, 0], [1, 0]], dtype=np.uint8)
    dark = np.array([[0.0, 0.0], [0.0, 11.0]])

    mask, counts = build_combined_mask(
        detector_mask,
        user_mask,
        dark,
        dark_hot_pixel_threshold=10.0,
    )

    np.testing.assert_array_equal(mask, np.array([[0, 1], [1, 1]], dtype=np.uint8))
    assert counts["user_mask_pixels"] == 1
    assert counts["detector_mask_pixels"] == 1
    assert counts["dark_hot_pixels"] == 1
    assert counts["combined_mask_pixels"] == 3


def test_frame_qc_row_blocks_v2_or_signature_mismatch(tmp_path: Path):
    root = tmp_path / "dat001"
    out_root = tmp_path / "dat001_absolute_corrected_2D"
    source = root / "3#_sample" / "frame_001.tif"
    paths = build_output_paths(source, input_root=root, output_root=out_root)
    paths.metadata.parent.mkdir(parents=True)
    paths.metadata.write_text(
        json.dumps({"schema": "saxsabs.bl19b2_abs2d.v2", "processing_signature": "old"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema mismatch"):
        _frame_qc_row_from_metadata(
            source=source,
            rel=source.relative_to(root),
            paths=paths,
            expected_signature="new",
        )


@pytest.mark.parametrize(
    ("metadata_payload", "error_match"),
    [
        (
            {"schema": SCHEMA_VERSION, "processing_signature": "old-signature"},
            "processing_signature",
        ),
        ("{not valid json", "metadata"),
    ],
)
def test_run_bl19b2_abs2d_blocks_existing_outputs_that_cannot_be_safely_resumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata_payload: dict[str, str] | str,
    error_match: str,
):
    input_root = tmp_path / "dat001"
    ref = input_root / "reference_saxs"
    sample = input_root / "3#_sample" / "frame_001.tif"
    sample.parent.mkdir(parents=True)
    _write_required_reference_files(ref)
    sample.write_bytes(b"sample")
    poni = tmp_path / "source.poni"
    poni.write_text("poni_version: 2\nDetector: Detector\n", encoding="utf-8")
    output_root = tmp_path / "dat001_absolute_corrected_2D"
    paths = build_output_paths(sample, input_root=input_root, output_root=output_root)
    for target in (paths.h5, paths.edf, paths.metadata):
        target.parent.mkdir(parents=True, exist_ok=True)
    paths.h5.write_bytes(b"existing h5")
    paths.edf.write_bytes(b"existing edf")
    if isinstance(metadata_payload, dict):
        paths.metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")
    else:
        paths.metadata.write_text(metadata_payload, encoding="utf-8")

    def fake_header(path: Path) -> BL19B2Header:
        name = Path(path).name
        if name == "dark001.tif":
            return BL19B2Header(exposure_s=10.0, monitor=100.0, transmission=1.0)
        return BL19B2Header(exposure_s=10.0, monitor=100.0, transmission=0.5)

    mask_info = MaskInfo(
        mask=np.zeros((2, 2), dtype=np.uint8),
        npy_path=output_root / "masks" / "bl19b2_mask.npy",
        edf_path=output_root / "masks" / "bl19b2_mask.edf",
        checksum_sha256="mask-sha",
        user_mask_path=None,
        user_mask_pixels=0,
        detector_mask_pixels=0,
        dark_hot_pixels=0,
        combined_mask_pixels=0,
        dark_hot_pixel_threshold=10.0,
    )
    calibration = StandardCalibration(
        k_factor=1.0,
        k_std=0.0,
        q_min_overlap=0.01,
        q_max_overlap=0.2,
        points_used=2,
        points_total=2,
        standard_thickness_cm=0.01,
        norm_standard=1.0,
        norm_background=1.0,
        bg_transmission_used=1.0,
        standard_thickness_source="test",
    )
    writer_calls: list[Path] = []

    monkeypatch.setattr(bl19b2, "read_tiff_header", fake_header)
    monkeypatch.setattr(bl19b2, "read_detector_image", lambda path: np.ones((2, 2), dtype=float))
    monkeypatch.setattr(bl19b2, "load_and_write_mask", lambda **kwargs: mask_info)
    monkeypatch.setattr(bl19b2, "calibrate_standard", lambda *args, **kwargs: (calibration, np.zeros((2, 2))))
    monkeypatch.setattr(
        bl19b2,
        "build_processing_signature",
        lambda *args, **kwargs: ("expected-signature", {"formula_version": "test"}),
    )
    monkeypatch.setattr(bl19b2, "write_hdf5_image", lambda path, image, metadata: writer_calls.append(Path(path)))
    monkeypatch.setattr(bl19b2, "write_edf_image", lambda path, image, metadata: writer_calls.append(Path(path)))

    config = BL19B2Abs2DConfig(
        input_root=input_root,
        poni_path=poni,
        output_root=output_root,
        mu_cm_inv=20.2,
        monitor_mode="rate",
        overwrite=False,
        write_preview=False,
    )

    with pytest.raises(ValueError, match=error_match):
        run_bl19b2_abs2d(config)

    assert writer_calls == []
    assert paths.h5.read_bytes() == b"existing h5"
    assert paths.edf.read_bytes() == b"existing edf"


def test_write_edf_image_uses_nested_metadata_for_header(tmp_path: Path):
    fabio = pytest.importorskip("fabio")
    image = np.ones((2, 2), dtype=np.float32)
    path = tmp_path / "frame_abs2d_cm-1.edf"
    metadata = {
        "raw_sample": "sample.tif",
        "processing_signature": "sig-2",
        "absolute_calibration": {
            "k_factor": 11.4,
            "k_std": 0.3,
            "k_std_semantics": "inlier ratio scatter; not combined K uncertainty",
            "k_statistical_standard_uncertainty": 0.1,
            "k_standard_uncertainty": 0.4,
            "k_expanded_uncertainty": 0.8,
            "coverage_factor": 2.0,
        },
        "thickness": {"thickness_cm": 0.079},
        "normalization": {
            "norm_sample": 123.0,
            "transmission_abs": 0.2,
            "exposure_s": 300.0,
        },
        "dark": {"exposure_s": 10.0},
        "mask": {"edf": "mask.edf"},
        "corrections_applied_in_image": {"solid_angle": False, "polarization": False},
    }

    write_edf_image(path, image, metadata)

    header = fabio.open(str(path)).header
    assert header["KFactor"] == "11.4"
    assert header["KStd"] == "0.3"
    assert header["KStatStdU"] == "0.1"
    assert header["KStandardU"] == "0.4"
    assert header["KExpandedU"] == "0.8"
    assert header["KCoverage"] == "2"
    assert header["ThicknessCm"] == "0.079"
    assert header["NormSample"] == "123"
    assert header["TransmissionAbs"] == "0.2"
    assert header["DarkExposure"] == "10"
    assert header["MaskPath"] == "mask.edf"
    assert header["SolidAngleAppliedInImage"] == "false"
    assert header["PolarizationAppliedInImage"] == "false"


def test_validate_config_rejects_nonpositive_standard_thickness(tmp_path: Path):
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "geometry.poni",
        standard_thickness_cm=0.0,
        monitor_mode="rate",
    )

    with pytest.raises(ValueError, match="standard_thickness_cm"):
        validate_config(config)


def test_validate_config_requires_exactly_one_sample_thickness_mode(tmp_path: Path):
    base = {
        "input_root": tmp_path / "dat001",
        "poni_path": tmp_path / "geometry.poni",
    }

    with pytest.raises(ValueError, match="exactly one"):
        validate_config(BL19B2Abs2DConfig(**base))
    with pytest.raises(ValueError, match="exactly one"):
        validate_config(
            BL19B2Abs2DConfig(**base, mu_cm_inv=20.2, sample_thickness_cm=0.01)
        )


def test_validate_config_requires_explicit_monitor_mode(tmp_path: Path):
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "geometry.poni",
        mu_cm_inv=20.2,
    )

    with pytest.raises(ValueError, match="monitor_mode"):
        validate_config(config)


@pytest.mark.parametrize("alpha", [0.0, -1.0, math.nan])
def test_validate_config_rejects_nonpositive_or_nonfinite_alpha(
    alpha: float,
    tmp_path: Path,
):
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "geometry.poni",
        mu_cm_inv=20.2,
        monitor_mode="rate",
        alpha=alpha,
    )

    with pytest.raises(ValueError, match="alpha"):
        validate_config(config)


@pytest.mark.parametrize(
    "field",
    [
        "transmission_abs_uncertainty",
        "monitor_relative_standard_uncertainty",
        "mu_relative_standard_uncertainty",
        "alpha_standard_uncertainty",
        "standard_thickness_relative_standard_uncertainty",
    ],
)
def test_validate_config_rejects_negative_uncertainty(field: str, tmp_path: Path):
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "geometry.poni",
        mu_cm_inv=20.2,
        monitor_mode="rate",
        **{field: -0.01},
    )

    with pytest.raises(ValueError, match=field):
        validate_config(config)


def test_standard_thickness_defaults_only_for_srm3600(tmp_path: Path):
    srm = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "geometry.poni",
        mu_cm_inv=20.2,
        monitor_mode="rate",
    )
    other = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "geometry.poni",
        mu_cm_inv=20.2,
        standard_key="OTHER",
        monitor_mode="rate",
    )

    assert bl19b2._resolve_standard_thickness_cm(srm) == (0.1055, "nist_srm3600_certificate")
    with pytest.raises(ValueError, match="standard_thickness_cm"):
        bl19b2._resolve_standard_thickness_cm(other)


def test_output_dtype_rejects_float32_overflow_on_unmasked_pixel():
    image = np.array([[float(np.finfo(np.float32).max) * 2.0, np.nan]], dtype=np.float64)
    mask = np.array([[0, 1]], dtype=np.uint8)

    with pytest.raises(ValueError, match="non-finite unmasked"):
        bl19b2._coerce_output_dtype(image, "float32", mask=mask)


def test_processing_signature_records_all_absolute_scale_choices(tmp_path: Path):
    refs = ReferencePaths(
        dark=tmp_path / "dark.tif",
        background=tmp_path / "background.tif",
        standard=tmp_path / "standard.tif",
    )
    for path in (refs.dark, refs.background, refs.standard):
        path.write_bytes(path.name.encode("ascii"))
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni_version: 2\n", encoding="utf-8")
    mask_info = MaskInfo(
        mask=np.zeros((1, 1), dtype=np.uint8),
        npy_path=tmp_path / "mask.npy",
        edf_path=tmp_path / "mask.edf",
        checksum_sha256="mask-sha",
        user_mask_path=None,
        user_mask_pixels=0,
        detector_mask_pixels=0,
        dark_hot_pixels=0,
        combined_mask_pixels=0,
        dark_hot_pixel_threshold=10.0,
    )
    config = BL19B2Abs2DConfig(
        input_root=tmp_path,
        poni_path=poni,
        mu_cm_inv=20.2,
        monitor_mode="integrated",
        dtype="float64",
        transmission_abs_uncertainty=0.001,
        monitor_relative_standard_uncertainty=0.01,
        mu_relative_standard_uncertainty=0.02,
        alpha_standard_uncertainty=0.03,
        standard_thickness_relative_standard_uncertainty=0.04,
    )
    calibration = StandardCalibration(
        k_factor=11.4,
        k_std=0.3,
        q_min_overlap=0.01,
        q_max_overlap=0.2,
        points_used=12,
        points_total=12,
        standard_thickness_cm=0.1055,
        norm_standard=10.0,
        norm_background=20.0,
        bg_transmission_used=1.0,
        standard_thickness_source="nist_srm3600_certificate",
        k_statistical_standard_uncertainty=0.1,
        k_standard_uncertainty=0.4,
        k_expanded_uncertainty=0.8,
        coverage_factor=2.0,
    )

    _, payload = bl19b2.build_processing_signature(
        config,
        mask_info=mask_info,
        calibration=calibration,
        safe_poni_path=poni,
        reference_paths=refs,
    )

    assert payload["monitor_mode"] == "integrated"
    assert payload["dtype"] == "float64"
    assert payload["mu_cm_inv"] == 20.2
    assert payload["sample_thickness_cm"] is None
    assert payload["standard_thickness_cm"] == 0.1055
    assert payload["transmission_abs_uncertainty"] == 0.001
    assert payload["monitor_relative_standard_uncertainty"] == 0.01
    assert payload["mu_relative_standard_uncertainty"] == 0.02
    assert payload["alpha_standard_uncertainty"] == 0.03
    assert payload["standard_thickness_relative_standard_uncertainty"] == 0.04
    assert payload["standard_calibration"]["k_standard_uncertainty"] == 0.4
    assert payload["standard_calibration"]["k_expanded_uncertainty"] == 0.8
    assert payload["standard_calibration"]["coverage_factor"] == 2.0


def test_resume_validates_source_and_hdf5_edf_checksums(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    pytest.importorskip("h5py")
    pytest.importorskip("fabio")
    root = tmp_path / "dat001"
    source = root / "sample" / "frame.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"raw-source")
    paths = build_output_paths(source, input_root=root, output_root=tmp_path / "out")
    header = BL19B2Header(exposure_s=10.0, monitor=100.0, transmission=0.5)
    source_identity = bl19b2._source_identity(source, header)
    image = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    budget = bl19b2.propagate_absolute_uncertainty(
        image,
        statistical_standard_uncertainty=0.1,
        k_relative_standard_uncertainty=0.0,
        standard_relative_standard_uncertainty=0.0,
        transmission_relative_standard_uncertainty=0.0,
        monitor_relative_standard_uncertainty=0.0,
        thickness_relative_standard_uncertainty=0.0,
        mu_relative_standard_uncertainty=0.0,
        alpha_standard_uncertainty=0.0,
        coverage_factor=2.0,
    )
    metadata = {
        "schema": SCHEMA_VERSION,
        "formula_version": bl19b2.FORMULA_VERSION,
        "processing_signature": "global-signature",
        "source_identity": source_identity,
        "frame_signature": bl19b2._frame_signature("global-signature", source_identity),
        "outputs": {
            "hdf5": str(paths.h5),
            "edf": str(paths.edf),
            "metadata": str(paths.metadata),
            "preview": "",
        },
        "output_image": {
            "shape": [2, 2],
            "dtype": "float32",
            "sha256": bl19b2._array_sha256(image),
        },
        "normalization": {"norm_sample": 500.0, "transmission_abs": 0.5},
        "thickness": {"thickness_cm": 0.034},
        "absolute_calibration": {
            "k_factor": 11.4,
            "k_std": 0.3,
            "k_std_semantics": "inlier ratio scatter; not combined K uncertainty",
            "k_statistical_standard_uncertainty": 0.1,
            "k_standard_uncertainty": 0.4,
            "k_expanded_uncertainty": 0.8,
            "coverage_factor": 2.0,
        },
        "uncertainty": {
            "status": "complete",
            "unknown_components": [],
            "combined_standard_uncertainty": {"status": "known"},
            "expanded_uncertainty": {"status": "known"},
        },
        "mask": {"npy": ""},
        "qc": {"finite_fraction": 1.0, "negative_fraction": 0.0},
        "warnings": [],
    }
    bl19b2.write_hdf5_image(paths.h5, image, metadata, budget)
    bl19b2.write_edf_image(paths.edf, image, metadata)
    metadata["outputs"]["hdf5_sha256"] = bl19b2._file_sha256(paths.h5)
    metadata["outputs"]["edf_sha256"] = bl19b2._file_sha256(paths.edf)
    bl19b2._write_json(paths.metadata, metadata)
    monkeypatch.setattr(bl19b2, "read_tiff_header", lambda path: header)

    row = _frame_qc_row_from_metadata(
        source=source,
        rel=source.relative_to(root),
        paths=paths,
        expected_signature="global-signature",
    )
    assert row["status"] == "success_existing"
    assert row["k_standard_uncertainty"] == 0.4
    assert row["k_expanded_uncertainty"] == 0.8

    original_hdf5 = paths.h5.read_bytes()
    import h5py

    with h5py.File(paths.h5, "r+") as h5:
        del h5["entry/data/uncertainty/monitor"]
    metadata["outputs"]["hdf5_sha256"] = bl19b2._file_sha256(paths.h5)
    bl19b2._write_json(paths.metadata, metadata)
    with pytest.raises(ValueError, match="HDF5 output is unreadable or incomplete"):
        _frame_qc_row_from_metadata(
            source=source,
            rel=source.relative_to(root),
            paths=paths,
            expected_signature="global-signature",
        )
    paths.h5.write_bytes(original_hdf5)
    metadata["outputs"]["hdf5_sha256"] = bl19b2._file_sha256(paths.h5)
    bl19b2._write_json(paths.metadata, metadata)

    metadata["absolute_calibration"]["k_standard_uncertainty"] = 99.0
    bl19b2._write_json(paths.metadata, metadata)
    with pytest.raises(ValueError, match="HDF5 K calibration"):
        _frame_qc_row_from_metadata(
            source=source,
            rel=source.relative_to(root),
            paths=paths,
            expected_signature="global-signature",
        )
    metadata["absolute_calibration"]["k_standard_uncertainty"] = 0.4
    bl19b2._write_json(paths.metadata, metadata)

    paths.edf.write_bytes(paths.edf.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="EDF file checksum"):
        _frame_qc_row_from_metadata(
            source=source,
            rel=source.relative_to(root),
            paths=paths,
            expected_signature="global-signature",
        )


def test_build_rerun_command_records_cli_paths_and_parameters(tmp_path: Path):
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "BL19B2_SAXS_Califile.poni",
        output_root=tmp_path / "dat001_absolute_corrected_2D_v3",
        mu_cm_inv=20.2,
        alpha=1.0,
        monitor_mode="rate",
        q_window=(0.01, 0.2),
        npt=1000,
        dtype="float32",
        dark_hot_pixel_threshold=10.0,
        transmission_abs_uncertainty=0.001,
        monitor_relative_standard_uncertainty=0.01,
        mu_relative_standard_uncertainty=0.02,
        alpha_standard_uncertainty=0.03,
        standard_thickness_relative_standard_uncertainty=0.04,
    )

    command = build_rerun_command(config, poni_path=tmp_path / "safe" / "BL19B2_SAXS_Califile.poni")

    assert f"& '{sys.executable}' -m saxsabs.cli bl19b2-abs2d" in command
    assert f"--input-root '{tmp_path / 'dat001'}'" in command
    assert f"--poni '{tmp_path / 'safe' / 'BL19B2_SAXS_Califile.poni'}'" in command
    assert "--mu 20.2" in command
    assert "--qmin 0.01" in command
    assert "--dark-hot-pixel-threshold 10" in command
    assert "--transmission-abs-uncertainty 0.001" in command
    assert "--monitor-relative-standard-uncertainty 0.01" in command
    assert "--mu-relative-standard-uncertainty 0.02" in command
    assert "--alpha-standard-uncertainty 0.03" in command
    assert "--standard-thickness-relative-standard-uncertainty 0.04" in command


def test_build_rerun_command_records_pydidas_yaml_and_mask(tmp_path: Path):
    cali = tmp_path / "Cali.yaml"
    mask = tmp_path / "Mask.edf"
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        pydidas_cali_yaml=cali,
        mask_path=mask,
        output_root=tmp_path / "dat001_absolute_corrected_2D_v3",
        mu_cm_inv=20.2,
        monitor_mode="rate",
    )

    command = build_rerun_command(config, poni_path=tmp_path / "safe" / "BL19B2_SAXS_Califile.poni")

    assert f"--pydidas-cali-yaml '{cali}'" in command
    assert f"--mask '{mask}'" in command
    assert "--poni " not in command


def test_build_rerun_command_records_explicit_reference_paths(tmp_path: Path):
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "BL19B2_SAXS_Califile.poni",
        output_root=tmp_path / "dat001_absolute_corrected_2D_v3",
        mu_cm_inv=20.2,
        monitor_mode="rate",
        dark_path=tmp_path / "refs" / "dark_run42.tif",
        background_path=tmp_path / "refs" / "empty_run42.tif",
        standard_path=tmp_path / "refs" / "gc_run42.tif",
        direct_path=tmp_path / "refs" / "direct_run42.tif",
    )

    command = build_rerun_command(config, poni_path=tmp_path / "safe" / "BL19B2_SAXS_Califile.poni")

    assert f"--dark '{tmp_path / 'refs' / 'dark_run42.tif'}'" in command
    assert f"--background '{tmp_path / 'refs' / 'empty_run42.tif'}'" in command
    assert f"--standard '{tmp_path / 'refs' / 'gc_run42.tif'}'" in command
    assert f"--direct-beam '{tmp_path / 'refs' / 'direct_run42.tif'}'" in command


def test_generated_readme_matches_solid_angle_calibration_setting(tmp_path: Path):
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "geometry.poni",
        mu_cm_inv=20.2,
        monitor_mode="rate",
        correct_solid_angle_for_k=False,
    )

    bl19b2._write_readme(tmp_path, config)

    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "correctSolidAngle = False" in text
    assert "correctSolidAngle = True" not in text


def test_format_code_state_text_records_dirty_diff():
    text = format_code_state_text(
        {
            "repo_root": "repo",
            "available": True,
            "branch": "main",
            "commit": "abc123",
            "status": "dirty",
            "status_short": " M src/file.py",
            "diff_stat": "src/file.py | 2 ++",
            "diff": "diff --git a/src/file.py b/src/file.py",
            "untracked_files": "new_file.py",
            "untracked_file_snapshots": [{"path": "new_file.py", "content": "print('tracked')"}],
        }
    )

    assert "status: dirty" in text
    assert " M src/file.py" in text
    assert "diff --git" in text
    assert "new_file.py" in text
    assert "print('tracked')" in text


def test_write_provenance_package_records_reproducibility_files(tmp_path: Path):
    config = BL19B2Abs2DConfig(
        input_root=tmp_path / "dat001",
        poni_path=tmp_path / "source.poni",
        output_root=tmp_path / "dat001_absolute_corrected_2D_v3",
        mu_cm_inv=20.2,
        monitor_mode="rate",
    )
    safe_poni = config.resolved_output_root() / "config" / "geometry" / "BL19B2.poni"
    refs = ReferencePaths(
        dark=tmp_path / "dat001" / "reference_saxs" / "dark001.tif",
        background=tmp_path / "dat001" / "reference_saxs" / "BG001.tif",
        standard=tmp_path / "dat001" / "reference_saxs" / "GC001.tif",
        direct=tmp_path / "dat001" / "reference_saxs" / "drt001.tif",
        mask=tmp_path / "dat001" / "reference_saxs" / "MASK_file.edf",
    )
    mask_info = MaskInfo(
        mask=np.zeros((2, 2), dtype=np.uint8),
        npy_path=config.resolved_output_root() / "masks" / "bl19b2_mask.npy",
        edf_path=config.resolved_output_root() / "masks" / "bl19b2_mask.edf",
        checksum_sha256="mask-sha",
        user_mask_path=refs.mask,
        user_mask_pixels=1,
        detector_mask_pixels=2,
        dark_hot_pixels=1,
        combined_mask_pixels=3,
        dark_hot_pixel_threshold=10.0,
    )
    calibration = StandardCalibration(
        k_factor=11.4,
        k_std=0.3,
        q_min_overlap=0.01,
        q_max_overlap=0.2,
        points_used=12,
        points_total=12,
        standard_thickness_cm=0.001,
        norm_standard=10.0,
        norm_background=20.0,
        bg_transmission_used=1.0,
        standard_thickness_source="beer_lambert_from_abs_mu",
        k_statistical_standard_uncertainty=0.1,
        k_standard_uncertainty=0.4,
        k_expanded_uncertainty=0.8,
        coverage_factor=2.0,
    )

    paths = write_provenance_package(
        config=config,
        safe_poni_path=safe_poni,
        reference_paths=refs,
        mask_info=mask_info,
        calibration=calibration,
        processing_signature="sig",
        signature_payload={"formula_version": bl19b2.FORMULA_VERSION},
        counts={"sample_total": 2, "processed": 1, "skipped": 1, "failed": 0, "rejected": 0},
        software_versions={"python": "3.x", "packages": {"saxsabs": "1.1.1", "pyFAI": "2026"}},
        code_state={
            "repo_root": "repo",
            "available": True,
            "branch": "main",
            "commit": "abc",
            "status": "dirty",
            "status_short": " M file",
            "diff_stat": "file | 1 +",
            "diff": "diff --git",
            "untracked_files": "new.py",
        },
        run_status="complete",
    )

    summary = json.loads(paths.provenance_summary.read_text(encoding="utf-8"))
    assert paths.run_command.exists()
    assert paths.processing_environment.exists()
    assert paths.code_state.exists()
    assert summary["processing_signature"] == "sig"
    assert summary["processing_signature_payload"]["formula_version"] == bl19b2.FORMULA_VERSION
    assert summary["mask"]["checksum_sha256"] == "mask-sha"
    assert summary["standard_calibration"]["k_factor"] == 11.4
    assert summary["standard_calibration"]["k_standard_uncertainty"] == 0.4
    assert summary["standard_calibration"]["k_expanded_uncertainty"] == 0.8
    assert summary["software_versions"]["packages"]["pyFAI"] == "2026"
    assert summary["code_state"]["status"] == "dirty"
    assert "diff --git" in paths.code_state.read_text(encoding="utf-8")


def test_future_beamtime_template_is_parseable_and_contains_cli_fields():
    yaml = pytest.importorskip("yaml")
    template = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "bl19b2_abs2d_template"
        / "processing_config.example.yml"
    )

    data = yaml.safe_load(template.read_text(encoding="utf-8"))

    assert data["schema"] == "saxsabs.bl19b2_abs2d.config.v1"
    assert data["input_root"]
    active_geometry_sources = [
        key for key in ("pydidas_cali_yaml", "poni_path") if data.get(key) not in (None, "")
    ]
    assert active_geometry_sources == ["pydidas_cali_yaml"]
    assert data["output_root"]
    assert data["references"]["dark"] == "reference_saxs/dark001.tif"
    assert data["references"]["mask"] in (
        "reference_saxs/MASK_file.edf",
        "reference_saxs/Mask.edf",
    )
    assert data["calibration"]["mu_cm_inv"] == 20.2
    assert data["uncertainty"]["monitor_relative_standard_uncertainty"] is None
    assert data["uncertainty"]["mu_relative_standard_uncertainty"] is None
    assert data["uncertainty"]["alpha_standard_uncertainty"] is None
    assert data["uncertainty"]["standard_thickness_relative_standard_uncertainty"] is None
    assert data["calibration"]["dark_hot_pixel_threshold"] == 10.0
    assert "bl19b2-abs2d" in data["full_run_command"]
