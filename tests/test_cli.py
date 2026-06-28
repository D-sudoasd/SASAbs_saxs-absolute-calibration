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
