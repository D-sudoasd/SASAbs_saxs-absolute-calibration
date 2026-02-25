from pathlib import Path

import numpy as np

from saxsabs.io.parsers import parse_header_values, read_external_1d_profile


def test_parse_header_values_ms_and_percent():
    exp, mon, trans = parse_header_values(
        {
            "ExposureTime": "200 ms",
            "I0": "1.2e6",
            "Transmission": "85%",
        }
    )
    assert np.isclose(exp, 0.2)
    assert np.isclose(mon, 1.2e6)
    assert np.isclose(trans, 0.85)


def test_parse_header_values_us_and_plain_percent_number():
    exp, mon, trans = parse_header_values(
        {
            "acq_time": "500 us",
            "monitor": "10000",
            "sample_transmission": "72",
        }
    )
    assert np.isclose(exp, 0.0005)
    assert np.isclose(mon, 10000.0)
    assert np.isclose(trans, 0.72)


def test_read_external_1d_profile_csv(tmp_path: Path):
    f = tmp_path / "profile.csv"
    f.write_text(
        "q,intensity,error\n"
        "0.10,100,5\n"
        "0.20,90,4\n"
        "0.30,80,4\n",
        encoding="utf-8",
    )

    out = read_external_1d_profile(f)
    assert out["x"].size == 3
    assert out["x_col"].lower() == "q"
    assert out["i_col"].lower() == "intensity"
    assert np.isclose(out["i_rel"][0], 100.0)


def test_read_external_1d_profile_space_delimited(tmp_path: Path):
    f = tmp_path / "profile.dat"
    f.write_text(
        "# q i sigma\n"
        "0.10 10 1\n"
        "0.20 20 2\n"
        "0.30 30 3\n",
        encoding="utf-8",
    )

    out = read_external_1d_profile(f)
    assert out["x"].size == 3
    assert np.isfinite(out["err_rel"]).all()
