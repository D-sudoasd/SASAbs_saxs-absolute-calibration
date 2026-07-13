import json
import sys
from pathlib import Path

import pytest

from saxsabs.cli import main
from saxsabs.workflows import bl19b2_abs2d


def test_cli_norm_factor(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["saxsabs", "norm-factor", "--mode", "integrated", "--mon", "10", "--trans", "0.5"],
    )
    main()
    out = capsys.readouterr().out.strip()
    assert out == "5.0"


def test_cli_norm_factor_rejects_non_finite_result(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sys,
        "argv",
        ["saxsabs", "norm-factor", "--mode", "integrated", "--mon", "10", "--trans", "0"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "non-finite" in err
    assert "trans must be 0 < T <= 1" in err


def test_cli_parse_header(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    f = tmp_path / "header.json"
    f.write_text('{"ExposureTime":"1000 ms","I0":"100","Transmission":"80%"}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["saxsabs", "parse-header", "--header-json", str(f)])
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["exp_s"] == 1.0
    assert out["i0"] == 100.0
    assert out["trans"] == 0.8


def test_cli_estimate_k(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    meas = tmp_path / "meas.csv"
    ref = tmp_path / "ref.csv"
    meas.write_text("q,i\n0.01,17.1\n0.02,15.4\n0.05,13.4\n0.10,11.8\n", encoding="utf-8")
    ref.write_text("q,i\n0.01,34.2\n0.02,30.8\n0.05,26.8\n0.10,23.6\n", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "estimate-k",
            "--meas",
            str(meas),
            "--ref",
            str(ref),
            "--qmin",
            "0.01",
            "--qmax",
            "0.2",
        ],
    )
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["k_factor"] == pytest.approx(2.0, rel=1e-6)
    assert out["k_std_semantics"] == "inlier ratio scatter; not combined K uncertainty"
    assert out["k_statistical_standard_uncertainty"] == pytest.approx(0.0, abs=1e-12)
    assert out["k_standard_uncertainty"] is None
    assert out["k_expanded_uncertainty"] is None
    assert out["coverage_factor"] is None


def test_cli_estimate_k_accepts_common_intensity_column_names(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    meas = tmp_path / "meas.csv"
    ref = tmp_path / "ref.csv"
    meas.write_text(
        "q,intensity,error\n0.01,17.1,0.1\n0.02,15.4,0.1\n0.05,13.4,0.1\n0.10,11.8,0.1\n",
        encoding="utf-8",
    )
    ref.write_text(
        "q,intensity,error\n0.01,34.2,0.1\n0.02,30.8,0.1\n0.05,26.8,0.1\n0.10,23.6,0.1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["saxsabs", "estimate-k", "--meas", str(meas), "--ref", str(ref)],
    )
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["k_factor"] == pytest.approx(2.0, rel=1e-6)


def test_cli_estimate_k_accepts_scattering_column_names_with_units(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    meas = tmp_path / "meas.csv"
    ref = tmp_path / "ref.csv"
    meas.write_text(
        "Q_A^-1,I_abs\n0.01,17.1\n0.02,15.4\n0.05,13.4\n0.10,11.8\n",
        encoding="utf-8",
    )
    ref.write_text(
        "Q_A^-1,I_abs\n0.01,34.2\n0.02,30.8\n0.05,26.8\n0.10,23.6\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["saxsabs", "estimate-k", "--meas", str(meas), "--ref", str(ref)],
    )
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["k_factor"] == pytest.approx(2.0, rel=1e-6)


def test_cli_estimate_k_accepts_explicit_column_overrides(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    meas = tmp_path / "meas.csv"
    ref = tmp_path / "ref.csv"
    meas.write_text(
        "angle,counts\n0.01,17.1\n0.02,15.4\n0.05,13.4\n0.10,11.8\n",
        encoding="utf-8",
    )
    ref.write_text(
        "q_ref,absolute\n0.01,34.2\n0.02,30.8\n0.05,26.8\n0.10,23.6\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "estimate-k",
            "--meas",
            str(meas),
            "--ref",
            str(ref),
            "--q-col",
            "angle",
            "--i-col",
            "counts",
            "--ref-q-col",
            "q_ref",
            "--ref-i-col",
            "absolute",
        ],
    )
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["k_factor"] == pytest.approx(2.0, rel=1e-6)


def test_cli_estimate_k_invalid_override_lists_available_columns(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    meas = tmp_path / "meas.csv"
    ref = tmp_path / "ref.csv"
    meas.write_text(
        "q,intensity\n0.01,17.1\n0.02,15.4\n0.05,13.4\n0.10,11.8\n",
        encoding="utf-8",
    )
    ref.write_text("q,i\n0.01,34.2\n0.02,30.8\n0.05,26.8\n0.10,23.6\n", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "estimate-k",
            "--meas",
            str(meas),
            "--ref",
            str(ref),
            "--q-col",
            "missing_q",
            "--i-col",
            "intensity",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "missing_q" in err
    assert "Available columns: q, intensity" in err


def test_cli_parse_external1d(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    profile = tmp_path / "profile.csv"
    profile.write_text("q,i,err\n0.01,10,0.2\n0.02,9,0.2\n0.03,8,0.2\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["saxsabs", "parse-external1d", "--input", str(profile)])
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["points"] == 3
    assert out["x_col"] == "q"
    assert out["i_col"] == "i"
    assert out["err_col"] == "err"


def test_cli_bl19b2_abs2d_passes_pydidas_yaml_and_mask_to_workflow(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def fake_run(config: bl19b2_abs2d.BL19B2Abs2DConfig) -> dict[str, str]:
        captured["config"] = config
        return {"status": "dry-run", "output_root": str(config.resolved_output_root())}

    input_root = tmp_path / "dat001"
    cali = tmp_path / "reference_saxs" / "Cali.yaml"
    mask = tmp_path / "reference_saxs" / "Mask.edf"
    output_root = tmp_path / "dat001_absolute_corrected_2D"
    monkeypatch.setattr(bl19b2_abs2d, "run_bl19b2_abs2d", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "bl19b2-abs2d",
            "--input-root",
            str(input_root),
            "--pydidas-cali-yaml",
            str(cali),
            "--mask",
            str(mask),
            "--output-root",
            str(output_root),
            "--mu",
            "20.2",
            "--monitor-mode",
            "rate",
            "--dry-run",
            "--no-preview",
        ],
    )

    main()

    out = json.loads(capsys.readouterr().out)
    config = captured["config"]
    assert out["status"] == "dry-run"
    assert config.input_root == input_root
    assert config.pydidas_cali_yaml == cali
    assert config.mask_path == mask
    assert config.poni_path is None
    assert config.output_root == output_root
    assert config.dry_run
    assert not config.write_preview


def test_cli_bl19b2_abs2d_passes_explicit_reference_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def fake_run(config: bl19b2_abs2d.BL19B2Abs2DConfig) -> dict[str, str]:
        captured["config"] = config
        return {"status": "dry-run", "output_root": str(config.resolved_output_root())}

    input_root = tmp_path / "dat001"
    poni = tmp_path / "geometry.poni"
    dark = tmp_path / "refs" / "dark_run42.tif"
    background = tmp_path / "refs" / "empty_run42.tif"
    standard = tmp_path / "refs" / "gc_run42.tif"
    direct = tmp_path / "refs" / "direct_run42.tif"
    monkeypatch.setattr(bl19b2_abs2d, "run_bl19b2_abs2d", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "bl19b2-abs2d",
            "--input-root",
            str(input_root),
            "--poni",
            str(poni),
            "--dark",
            str(dark),
            "--background",
            str(background),
            "--standard",
            str(standard),
            "--direct-beam",
            str(direct),
            "--mu",
            "20.2",
            "--monitor-mode",
            "rate",
            "--dry-run",
        ],
    )

    main()

    out = json.loads(capsys.readouterr().out)
    config = captured["config"]
    assert out["status"] == "dry-run"
    assert config.dark_path == dark
    assert config.background_path == background
    assert config.standard_path == standard
    assert config.direct_path == direct


def test_cli_bl19b2_abs2d_passes_monitor_and_fixed_thickness_modes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def fake_run(config: bl19b2_abs2d.BL19B2Abs2DConfig) -> dict[str, str]:
        captured["config"] = config
        return {"status": "dry-run", "output_root": str(config.resolved_output_root())}

    monkeypatch.setattr(bl19b2_abs2d, "run_bl19b2_abs2d", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "bl19b2-abs2d",
            "--input-root",
            str(tmp_path / "dat001"),
            "--poni",
            str(tmp_path / "geometry.poni"),
            "--monitor-mode",
            "integrated",
            "--sample-thickness-cm",
            "0.0123",
            "--monitor-relative-standard-uncertainty",
            "0.01",
            "--sample-thickness-relative-standard-uncertainty",
            "0.02",
            "--alpha-standard-uncertainty",
            "0.03",
            "--standard-thickness-relative-standard-uncertainty",
            "0.04",
            "--dry-run",
        ],
    )

    main()

    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
    assert captured["config"].monitor_mode == "integrated"
    assert captured["config"].sample_thickness_cm == 0.0123
    assert captured["config"].mu_cm_inv is None
    assert captured["config"].monitor_relative_standard_uncertainty == 0.01
    assert captured["config"].sample_thickness_relative_standard_uncertainty == 0.02
    assert captured["config"].alpha_standard_uncertainty == 0.03
    assert captured["config"].standard_thickness_relative_standard_uncertainty == 0.04


def test_cli_bl19b2_abs2d_passes_standard_side_and_system_coverage_uncertainties(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def fake_run(config: bl19b2_abs2d.BL19B2Abs2DConfig) -> dict[str, str]:
        captured["config"] = config
        return {"status": "dry-run", "output_root": str(config.resolved_output_root())}

    monkeypatch.setattr(bl19b2_abs2d, "run_bl19b2_abs2d", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs", "bl19b2-abs2d",
            "--input-root", str(tmp_path / "dat001"),
            "--poni", str(tmp_path / "geometry.poni"),
            "--monitor-mode", "rate",
            "--sample-thickness-cm", "0.1",
            "--standard-transmission-abs-uncertainty", "0.01",
            "--standard-monitor-relative-standard-uncertainty", "0.02",
            "--calibration-background-monitor-relative-standard-uncertainty", "0.03",
            "--system-coverage-factor", "2.0",
            "--dry-run",
        ],
    )

    main()

    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
    config = captured["config"]
    assert config.standard_transmission_abs_uncertainty == pytest.approx(0.01)
    assert config.standard_monitor_relative_standard_uncertainty == pytest.approx(0.02)
    assert config.calibration_background_monitor_relative_standard_uncertainty == pytest.approx(0.03)
    assert config.system_coverage_factor == pytest.approx(2.0)

def test_cli_bl19b2_abs2d_passes_explicit_calibration_controls(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def fake_run(config: bl19b2_abs2d.BL19B2Abs2DConfig) -> dict[str, str]:
        captured["config"] = config
        return {"status": "dry-run", "output_root": str(config.resolved_output_root())}

    monkeypatch.setattr(bl19b2_abs2d, "run_bl19b2_abs2d", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "bl19b2-abs2d",
            "--input-root",
            str(tmp_path / "dat001"),
            "--poni",
            str(tmp_path / "geometry.poni"),
            "--monitor-mode",
            "rate",
            "--mu",
            "20.2",
            "--standard-key",
            "CUSTOM_STANDARD",
            "--no-correct-solid-angle-for-k",
            "--polarization-factor",
            "0.95",
            "--dry-run",
        ],
    )

    main()

    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
    config = captured["config"]
    assert config.standard_key == "CUSTOM_STANDARD"
    assert config.correct_solid_angle_for_k is False
    assert config.polarization_factor == pytest.approx(0.95)


def test_cli_bl19b2_v1_legacy_requires_explicit_historical_assumptions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def fake_run(config: bl19b2_abs2d.BL19B2Abs2DConfig) -> dict[str, str]:
        captured["config"] = config
        return {"status": "dry-run", "output_root": str(config.resolved_output_root())}

    monkeypatch.setattr(bl19b2_abs2d, "run_bl19b2_abs2d", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "bl19b2-abs2d-v1-legacy",
            "--input-root",
            str(tmp_path / "dat001"),
            "--poni",
            str(tmp_path / "geometry.poni"),
            "--legacy-assume-monitor-rate",
            "--legacy-assume-mu-20-2",
            "--dry-run",
        ],
    )

    main()

    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
    assert captured["config"].monitor_mode == "rate"
    assert captured["config"].mu_cm_inv == pytest.approx(20.2)


@pytest.mark.parametrize(
    "safety_option",
    ["--legacy-assume-monitor-rate", "--legacy-assume-mu-20-2"],
)
def test_cli_bl19b2_v1_legacy_rejects_incomplete_historical_assumptions(
    safety_option: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "bl19b2-abs2d-v1-legacy",
            "--input-root",
            str(tmp_path / "dat001"),
            "--poni",
            str(tmp_path / "geometry.poni"),
            safety_option,
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "explicit" in capsys.readouterr().err.lower()

@pytest.mark.parametrize("status", ["partial", "failed"])
def test_cli_bl19b2_abs2d_returns_nonzero_for_incomplete_scientific_run(
    status: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        bl19b2_abs2d,
        "run_bl19b2_abs2d",
        lambda config: {"status": status, "output_root": str(config.resolved_output_root())},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "bl19b2-abs2d",
            "--input-root",
            str(tmp_path / "dat001"),
            "--poni",
            str(tmp_path / "geometry.poni"),
            "--mu",
            "20.2",
            "--monitor-mode",
            "rate",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_cli_bl19b2_abs2d_rejects_two_geometry_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "saxsabs",
            "bl19b2-abs2d",
            "--input-root",
            str(tmp_path / "dat001"),
            "--poni",
            str(tmp_path / "geometry.poni"),
            "--pydidas-cali-yaml",
            str(tmp_path / "Cali.yaml"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
