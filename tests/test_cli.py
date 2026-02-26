import json
import sys
from pathlib import Path

import pytest

from saxsabs.cli import main


def test_cli_norm_factor(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "argv", ["saxsabs", "norm-factor", "--mode", "integrated", "--mon", "10", "--trans", "0.5"])
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
