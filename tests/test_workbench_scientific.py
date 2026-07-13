import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from saxsabs.core.calibration_context import CalibrationContext, sha256_file
from saxsabs.core.calibration import estimate_k_factor_robust
from saxsabs.constants import get_reference_data
from saxsabs.core.execution_policy import RunPolicy


def _load_workbench_module():
    pytest.importorskip("fabio")
    pytest.importorskip("pyFAI")

    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "SASAbs.py"
    spec = importlib.util.spec_from_file_location("saxsabs_workbench_scientific_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_workbench_uses_certified_srm3600_thickness_default():
    module = _load_workbench_module()

    assert module.DEFAULT_STANDARD_THICKNESS_MM == pytest.approx(1.055)


def test_workbench_requires_explicit_thickness_after_selecting_non_srm_standard():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)

    class Var:
        def __init__(self, value=None):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app.t1_std_combo = SimpleNamespace(get=lambda: "Water")
    app._t1_std_option_map = {"Water": "Water_20C"}
    app.t1_std_type = Var("SRM3600")
    app.t1_params = {"std_thk": Var(module.DEFAULT_STANDARD_THICKNESS_MM)}
    app.t1_water_row = SimpleNamespace(pack_forget=lambda: None, pack=lambda **_kwargs: None)
    ref_frame = SimpleNamespace(pack_forget=lambda: None, pack=lambda **_kwargs: None)
    app.t1_ref_row = {"frame": ref_frame}

    app._on_std_type_changed()

    assert app.t1_std_type.get() == "Water_20C"
    assert app.t1_params["std_thk"].get() == 0.0


def test_workbench_blank_normalization_exposure_matches_dark_and_does_not_divide_by_blank_t(
    monkeypatch,
):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)

    blank = SimpleNamespace(data=np.array([[30.0]]), header={})
    monkeypatch.setattr(module.fabio, "open", lambda _path: blank)
    app._assert_same_shape = lambda *_args: None
    app.parse_header = lambda *_args, **_kwargs: (10.0, 1.0, 0.99)

    image, norms, paths = app.build_composite_bg_net(
        ["blank.tif"],
        np.array([[2.0]]),
        "rate",
        (10.0, 1.0, 0.99),
        dark_exposure_s=1.0,
        ref_shape=(1, 1),
    )

    # Dark contributes 2 counts/s, so the 10 s blank contains 20 dark counts.
    # NIST blank normalization is (30 - 20) / (10 * I0), without division by T_blank.
    np.testing.assert_allclose(image, [[1.0]])
    assert norms == [10.0]
    assert paths == ["blank.tif"]


def test_workbench_requires_dark_exposure_metadata():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.parse_header = lambda *_args, **_kwargs: (None, None, None)

    with pytest.raises(ValueError, match="dark.*exposure|曝光"):
        app.read_required_dark_exposure("dark.tif")


def test_workbench_builds_one_correction_policy_for_calibration_and_batch():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    mask = np.array([[False, True]])
    flat = np.array([[1.0, 1.1]])

    kwargs = app.build_integration_correction_kwargs(
        correct_solid_angle=True,
        error_model="azimuthal",
        mask=mask,
        flat=flat,
        polarization_factor=0.95,
    )

    assert kwargs["correctSolidAngle"] is True
    assert kwargs["error_model"] == "azimuthal"
    assert kwargs["mask"] is mask
    assert kwargs["flat"] is flat
    assert kwargs["polarization_factor"] == pytest.approx(0.95)


def test_workbench_sample_task_uses_exposure_matched_dark_before_integration(
    tmp_path,
    monkeypatch,
):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    sample_path = tmp_path / "sample.tif"
    sample_path.write_text("sample", encoding="utf-8")
    output_dir = tmp_path / "profiles"
    output_dir.mkdir()
    integrated = {}

    class FakeAI:
        def integrate1d(self, image, _npt, **_kwargs):
            integrated["image"] = np.asarray(image).copy()
            return SimpleNamespace(
                radial=np.array([0.01, 0.02, 0.03]),
                intensity=np.array([9.0, 9.0, 9.0]),
                sigma=None,
            )

    monkeypatch.setattr(
        module.fabio,
        "open",
        lambda _path: SimpleNamespace(data=np.array([[70.0]]), header={}),
    )
    app.parse_header = lambda *_args, **_kwargs: (10.0, 1.0, 0.5)

    context = {
        "selected_modes": ["1d_full"],
        "save_dirs": {"1d_full": output_dir},
        "parallel": False,
        "image_cache": {},
        "cache_lock": SimpleNamespace(__enter__=lambda self: self, __exit__=lambda *args: None),
        "ai_shared": FakeAI(),
        "run_policy": RunPolicy(resume_enabled=False, overwrite_existing=False),
        "resume": False,
        "overwrite": False,
        "export_cal2d": False,
        "poni_path": tmp_path / "geometry.poni",
        "ref_mode": "fixed",
        "fixed_dark_data": np.array([[2.0]]),
        "fixed_dark_exposure_s": 1.0,
        "fixed_bg_norm": 10.0,
        "fixed_bg_net": np.array([[1.0]]),
        "fixed_bg_path": "blank.tif",
        "fixed_dark_path": "dark.tif",
        "mask_arr": None,
        "flat_arr": None,
        "calc_mode": "fixed",
        "fixed_thk_cm": 0.1,
        "monitor_mode": "rate",
        "k_factor": 1.0,
        "apply_solid_angle": False,
        "error_model": "none",
        "polarization_applied": False,
        "polarization": None,
        "bg_alpha": 1.0,
        "output_format": "tsv",
    }

    result = app.process_sample_task(1, str(sample_path), "sample", context)

    # (70 - 2*10)/(10*1*0.5) - 1 = 9
    np.testing.assert_allclose(integrated["image"], [[9.0]])
    assert result["row"]["Status"] == "成功"


def _calibration_context(module, poni: Path, mask: Path | None = None, flat: Path | None = None):
    return CalibrationContext(
        formula_version=module.WORKBENCH_FORMULA_VERSION,
        monitor_mode="rate",
        poni_sha256=sha256_file(poni),
        mask_sha256=sha256_file(mask) if mask is not None else None,
        flat_sha256=sha256_file(flat) if flat is not None else None,
        correct_solid_angle=True,
        polarization_factor=None,
        standard_key="SRM3600",
        standard_thickness_cm=0.1055,
    )


def test_workbench_blocks_manual_k_without_calibration_context(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.calibration_context = None
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")

    with pytest.raises(ValueError, match="CalibrationContext|上下文"):
        app.require_calibration_context_for_batch(
            k_factor=2.5,
            monitor_mode="rate",
            poni_path=poni,
            mask_path=None,
            flat_path=None,
            correct_solid_angle=True,
            polarization_factor=None,
        )


def test_workbench_accepts_only_matching_calibration_context(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    poni = tmp_path / "geometry.poni"
    mask = tmp_path / "mask.npy"
    flat = tmp_path / "flat.npy"
    poni.write_text("poni", encoding="utf-8")
    mask.write_bytes(b"mask")
    flat.write_bytes(b"flat")
    app.calibration_context = _calibration_context(module, poni, mask, flat)
    app.calibration_k_value = 2.5

    result = app.require_calibration_context_for_batch(
        k_factor=2.5,
        monitor_mode="rate",
        poni_path=poni,
        mask_path=mask,
        flat_path=flat,
        correct_solid_angle=True,
        polarization_factor=None,
    )

    assert result.fingerprint() == app.calibration_context.fingerprint()

    flat.write_bytes(b"changed-flat")
    with pytest.raises(ValueError, match="flat_sha256"):
        app.require_calibration_context_for_batch(
            k_factor=2.5,
            monitor_mode="rate",
            poni_path=poni,
            mask_path=mask,
            flat_path=flat,
            correct_solid_angle=True,
            polarization_factor=None,
        )


class _Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _record_app(module):
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.global_vars = {
        "k_factor": _Var(1.0),
        "monitor_mode": _Var("integrated"),
        "poni_path": _Var(""),
        "mask_path": _Var(""),
        "flat_path": _Var(""),
        "apply_solid_angle": _Var(False),
        "k_solid_angle": _Var("unknown"),
        "polarization_enabled": _Var(False),
        "polarization_factor": _Var(0.0),
    }
    app.calibration_context = None
    app.calibration_k_value = None
    app.calibration_uncertainty = None
    return app


def test_workbench_k_uncertainty_keeps_srm_builtin_and_marks_unknown_standards():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    q_ref, i_ref = get_reference_data("SRM3600")
    result = estimate_k_factor_robust(
        q_meas=q_ref,
        i_meas_per_cm=i_ref / 2.0,
        q_window=(float(q_ref.min()), float(q_ref.max())),
    )

    srm = app.build_calibration_uncertainty_payload(
        result.k_statistical_standard_uncertainty,
        result.k_standard_uncertainty,
        result.k_expanded_uncertainty,
        result.coverage_factor,
    )
    unknown = app.build_calibration_uncertainty_payload(0.01, None, None, None)

    assert srm["standard_uncertainty_status"] == "available"
    assert srm["k_standard_uncertainty"] is not None
    assert srm["k_expanded_uncertainty"] is not None
    assert unknown["standard_uncertainty_status"] == "unknown"
    assert unknown["k_standard_uncertainty"] is None
    assert unknown["k_expanded_uncertainty"] is None
    assert unknown["coverage_factor"] is None


def test_workbench_non_srm_selection_resets_certificate_thickness():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.t1_std_combo = SimpleNamespace(get=lambda: "Custom")
    app._t1_std_option_map = {"Custom": "Custom"}
    app.t1_std_type = _Var("SRM3600")
    app.t1_params = {"std_thk": _Var(module.DEFAULT_STANDARD_THICKNESS_MM)}
    app.t1_water_row = SimpleNamespace(pack_forget=lambda: None, pack=lambda **_kwargs: None)
    frame = SimpleNamespace(pack_forget=lambda: None, pack=lambda **_kwargs: None)
    app.t1_ref_row = {"frame": frame}

    app._on_std_type_changed()

    assert app.t1_std_type.get() == "Custom"
    assert app.t1_params["std_thk"].get() == 0.0


def test_workbench_sample_thickness_modes_are_explicit_and_mutually_exclusive():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    assert module.DEFAULT_SAMPLE_MU_CM_INV is None

    fixed = app.resolve_sample_thickness_config(
        mode="fixed", mu_value="", fixed_thickness_mm=1.2
    )
    assert fixed == {"mode": "fixed", "mu_cm_inv": None, "fixed_thickness_cm": 0.12}

    with pytest.raises(ValueError, match="mu|衰减"):
        app.resolve_sample_thickness_config(
            mode="auto", mu_value="", fixed_thickness_mm=1.2
        )

    beer_lambert = app.resolve_sample_thickness_config(
        mode="auto", mu_value="20.2", fixed_thickness_mm=0
    )
    assert beer_lambert == {
        "mode": "auto",
        "mu_cm_inv": 20.2,
        "fixed_thickness_cm": None,
    }


def test_workbench_calibration_record_round_trips_k_context_and_uncertainty(tmp_path):
    module = _load_workbench_module()
    app = _record_app(module)
    poni = tmp_path / "geometry.poni"
    mask = tmp_path / "mask.npy"
    flat = tmp_path / "flat.npy"
    poni.write_text("poni", encoding="utf-8")
    mask.write_bytes(b"mask")
    flat.write_bytes(b"flat")
    context = _calibration_context(module, poni, mask, flat)
    record_path = tmp_path / "calibration_record.json"
    uncertainty = app.build_calibration_uncertainty_payload(0.01, 0.02, 0.04, 2.0)

    app.save_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=context,
        calibration_uncertainty=uncertainty,
        poni_path=poni,
        mask_path=mask,
        flat_path=flat,
    )
    app.load_calibration_record(record_path)

    assert app.global_vars["k_factor"].get() == pytest.approx(2.5)
    assert app.calibration_k_value == pytest.approx(2.5)
    assert app.calibration_context.fingerprint() == context.fingerprint()
    assert app.calibration_uncertainty == uncertainty
    assert app.global_vars["poni_path"].get() == str(poni)
    assert app.global_vars["mask_path"].get() == str(mask)
    assert app.global_vars["flat_path"].get() == str(flat)


@pytest.mark.parametrize("missing_context", [True, False])
def test_workbench_calibration_record_rejects_missing_or_tampered_context(
    tmp_path,
    missing_context,
):
    module = _load_workbench_module()
    app = _record_app(module)
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    context = _calibration_context(module, poni)
    record_path = tmp_path / "calibration_record.json"
    app.save_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=context,
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
    )
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    if missing_context:
        payload.pop("calibration_context")
    else:
        payload["calibration_context"]["monitor_mode"] = "integrated"
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="[Cc]ontext|fingerprint|完整性"):
        app.load_calibration_record(record_path)

    assert app.calibration_context is None
    assert app.calibration_k_value is None


def test_apply_session_invalidates_legacy_k_without_context(tmp_path):
    module = _load_workbench_module()
    app = _record_app(module)
    app.calibration_context = object()
    app.calibration_k_value = 2.5
    app.session_geometry_fallback = {}
    app.t1_files = {"std": _Var("")}
    app.show_error = lambda *_args, **_kwargs: None
    shown = []
    app.show_info = lambda _title, message: shown.append(message)
    session_path = tmp_path / "session.json"
    session_path.write_text('{"calibration": {"k_factor": 9.0}}', encoding="utf-8")

    app.apply_session(str(session_path))

    assert app.calibration_context is None
    assert app.calibration_k_value is None
    assert any("ignored" in message.lower() or "忽略" in message for message in shown)


def test_apply_session_safely_loads_complete_relative_calibration_record(tmp_path):
    module = _load_workbench_module()
    app = _record_app(module)
    app.session_geometry_fallback = {}
    app.t1_files = {"std": _Var("")}
    app.show_error = lambda *_args, **_kwargs: None
    shown = []
    app.show_info = lambda _title, message: shown.append(message)
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    context = _calibration_context(module, poni)
    record_path = tmp_path / "calibration_record.json"
    app.save_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=context,
        calibration_uncertainty=None,
        poni_path=poni,
        mask_path=None,
        flat_path=None,
    )
    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps({"calibration": {"calibration_record_path": record_path.name}}),
        encoding="utf-8",
    )

    app.apply_session(str(session_path))

    assert app.calibration_k_value == pytest.approx(2.5)
    assert app.calibration_context.fingerprint() == context.fingerprint()
    assert any("record loaded" in message.lower() for message in shown)


def test_calibrated_2d_reintegration_matches_direct_absolute_1d_with_same_policy():
    pytest.importorskip("pyFAI")
    from pyFAI.integrator.azimuthal import AzimuthalIntegrator

    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    yy, xx = np.indices((64, 64), dtype=np.float64)
    img_net = 2.0 + 0.03 * xx + 0.05 * yy + 0.2 * np.sin(xx / 7.0)
    mask = np.zeros((64, 64), dtype=bool)
    mask[:2, :] = True
    flat = 0.95 + 0.001 * xx
    ai = AzimuthalIntegrator(
        dist=0.2,
        poni1=0.0032,
        poni2=0.0032,
        pixel1=1e-4,
        pixel2=1e-4,
        wavelength=1e-10,
    )
    kwargs = app.build_integration_correction_kwargs(
        correct_solid_angle=True,
        error_model="none",
        mask=mask,
        flat=flat,
        polarization_factor=0.95,
    )
    scale = 2.5 / 0.2

    direct = ai.integrate1d(img_net, 48, unit="q_A^-1", **kwargs)
    calibrated_2d = img_net * scale
    regenerated = ai.integrate1d(calibrated_2d, 48, unit="q_A^-1", **kwargs)

    np.testing.assert_allclose(
        np.asarray(regenerated.intensity),
        np.asarray(direct.intensity) * scale,
        rtol=2e-6,
        atol=1e-6,
    )
