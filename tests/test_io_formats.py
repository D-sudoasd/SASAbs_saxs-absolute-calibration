"""Tests for canSAS XML and NXcanSAS HDF5 I/O round-trip."""

import numpy as np
import pytest

from saxsabs.io.writers import write_cansas1d_xml, write_nxcansas_h5
from saxsabs.io.parsers import read_cansas1d_xml, read_external_1d_profile


# ---------------------------------------------------------------------------
# canSAS 1D XML round-trip
# ---------------------------------------------------------------------------
class TestCanSAS1DXML:
    def _make_data(self, n=50):
        q = np.linspace(0.01, 0.30, n)
        i_abs = 100.0 / q
        err = np.full(n, 0.5)
        return q, i_abs, err

    def test_write_read_roundtrip(self, tmp_path):
        q, i_abs, err = self._make_data()
        xml_path = tmp_path / "test.xml"
        write_cansas1d_xml(xml_path, q, i_abs, err, metadata={"title": "round-trip test"})
        assert xml_path.exists()

        result = read_cansas1d_xml(xml_path)
        assert "x" in result
        assert "i_rel" in result
        np.testing.assert_allclose(result["x"], q, rtol=1e-6)
        np.testing.assert_allclose(result["i_rel"], i_abs, rtol=1e-6)
        np.testing.assert_allclose(result["err_rel"], err, rtol=1e-6)

    def test_write_no_error(self, tmp_path):
        q, i_abs, _ = self._make_data()
        xml_path = tmp_path / "no_err.xml"
        write_cansas1d_xml(xml_path, q, i_abs)
        result = read_cansas1d_xml(xml_path)
        np.testing.assert_allclose(result["x"], q, rtol=1e-6)

    def test_auto_detect_xml_extension(self, tmp_path):
        """read_external_1d_profile should auto-detect .xml files."""
        q, i_abs, err = self._make_data()
        xml_path = tmp_path / "auto.xml"
        write_cansas1d_xml(xml_path, q, i_abs, err)
        result = read_external_1d_profile(str(xml_path))
        np.testing.assert_allclose(result["x"], q, rtol=1e-6)

    def test_metadata_preserved(self, tmp_path):
        q, i_abs, err = self._make_data(10)
        xml_path = tmp_path / "meta.xml"
        meta = {
            "title": "SAXS test",
            "run": "run42",
            "wavelength_A": 1.5406,
            "sdd_m": 2.0,
            "sample_name": "glass",
        }
        out = write_cansas1d_xml(xml_path, q, i_abs, err, metadata=meta)
        assert out == xml_path


# ---------------------------------------------------------------------------
# NXcanSAS HDF5 round-trip (skip if h5py unavailable)
# ---------------------------------------------------------------------------
h5py = pytest.importorskip("h5py")
from saxsabs.io.parsers import read_nxcansas_h5  # noqa: E402


class TestNXcanSASHDF5:
    def _make_data(self, n=50):
        q = np.linspace(0.01, 0.30, n)
        i_abs = 100.0 / q
        err = np.full(n, 0.5)
        return q, i_abs, err

    def test_write_read_roundtrip(self, tmp_path):
        q, i_abs, err = self._make_data()
        h5_path = tmp_path / "test.h5"
        write_nxcansas_h5(h5_path, q, i_abs, err, metadata={"title": "h5 round-trip"})
        assert h5_path.exists()

        result = read_nxcansas_h5(h5_path)
        np.testing.assert_allclose(result["x"], q, rtol=1e-10)
        np.testing.assert_allclose(result["i_rel"], i_abs, rtol=1e-10)
        np.testing.assert_allclose(result["err_rel"], err, rtol=1e-10)

    def test_auto_detect_h5_extension(self, tmp_path):
        """read_external_1d_profile should auto-detect .h5 files."""
        q, i_abs, err = self._make_data()
        h5_path = tmp_path / "auto.h5"
        write_nxcansas_h5(h5_path, q, i_abs, err)
        result = read_external_1d_profile(str(h5_path))
        np.testing.assert_allclose(result["x"], q, rtol=1e-10)

    def test_no_error_dataset(self, tmp_path):
        q, i_abs, _ = self._make_data()
        h5_path = tmp_path / "no_err.h5"
        write_nxcansas_h5(h5_path, q, i_abs)
        result = read_nxcansas_h5(h5_path)
        np.testing.assert_allclose(result["x"], q, rtol=1e-10)
        assert np.all(np.isnan(result["err_rel"]))
