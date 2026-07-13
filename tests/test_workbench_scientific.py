import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from saxsabs.core.calibration_context import (
    CalibrationContext,
    builtin_reference_identity,
    canonical_reference_sha256,
    sha256_file,
)
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


def _trust_cached_record_for_gate_unit_test(app):
    """Keep narrow gate unit tests focused on post-record operator checks."""
    app._refresh_and_verify_active_calibration_record = (
        lambda *, k_factor: SimpleNamespace(k_factor=k_factor)
    )

def test_workbench_uses_certified_srm3600_thickness_default():
    module = _load_workbench_module()

    assert module.DEFAULT_STANDARD_THICKNESS_MM == pytest.approx(1.055)


@pytest.mark.parametrize(
    "standard_alias",
    [
        "SRM3600",
        "srm-3600",
        "nist_srm3600",
        "NIST SRM 3600",
        "NIST-SRM-3600",
    ],
)
def test_workbench_srm3600_aliases_lock_certificate_thickness(standard_alias: str):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)

    assert module.DEFAULT_STANDARD_THICKNESS_MM / 10.0 == pytest.approx(0.1055)
    assert app.validate_standard_thickness_mm(
        standard_alias,
        1.055,
    ) == pytest.approx(1.055)
    with pytest.raises(ValueError, match="SRM 3600.*1.055"):
        app.validate_standard_thickness_mm(standard_alias, 1.0)


def test_tab3_requires_calibrated_k_source(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.calibration_context = None
    app.calibration_k_value = None

    with pytest.raises(ValueError, match="CalibrationContext|标定"):
        app.require_trusted_k_for_external(1.0)

    source_paths = []
    for name in ("poni", "standard", "background", "dark"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        source_paths.append(path)
    poni, standard, background, dark = source_paths
    app.calibration_context = _calibration_context(module, poni, complete=False)
    app.calibration_k_value = 2.5
    with pytest.raises(ValueError, match="来源不完整|缺少"):
        app.require_trusted_k_for_external(2.5)

    app.calibration_context = _calibration_context(module, poni)
    app.calibration_record_provenance_complete = True
    app.calibration_record_source_files_verified = True
    app.calibration_k_value = 2.5
    _trust_cached_record_for_gate_unit_test(app)
    assert app.require_trusted_k_for_external(2.5) is app.calibration_context
    with pytest.raises(ValueError, match="修改|匹配"):
        app.require_trusted_k_for_external(2.6)

def test_tab3_raw_monitor_mode_must_match_calibrated_k(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    app.calibration_context = _calibration_context(module, poni)
    app.calibration_record_provenance_complete = True
    app.calibration_record_source_files_verified = True
    app.calibration_k_value = 2.5
    _trust_cached_record_for_gate_unit_test(app)

    with pytest.raises(ValueError, match="monitor_mode|I0"):
        app.require_trusted_k_for_external(
            2.5, pipeline_mode="raw", monitor_mode="integrated"
        )
    assert app.require_trusted_k_for_external(
        2.5, pipeline_mode="scaled", monitor_mode="integrated"
    ) is app.calibration_context


def test_tab3_two_theta_requires_wavelength_and_converts_to_q():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    profile = {"x": np.array([1.0, 2.0, 3.0]), "x_col": "2theta"}

    with pytest.raises(ValueError, match="波长|wavelength"):
        app.resolve_external_x_axis("profile.dat", profile, mode="auto", wavelength_a="")

    q, label, conversion = app.resolve_external_x_axis(
        "profile.dat", profile, mode="auto", wavelength_a="1.0"
    )
    np.testing.assert_allclose(q, 4.0 * np.pi * np.sin(np.deg2rad(profile["x"] / 2.0)))
    assert label == "Q_A^-1"
    assert conversion == "two_theta_deg_to_q_a^-1"


@pytest.mark.parametrize(
    ("x_col", "mode", "wavelength"),
    [
        ("2theta", "chi_deg", "1.0"),
        ("chi", "q_a^-1", ""),
        ("q_A^-1", "chi_deg", ""),
        ("q_A^-1", "two_theta_deg", "1.0"),
    ],
)
def test_tab3_rejects_named_axis_conflicting_with_explicit_mode(x_col, mode, wavelength):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    profile = {"x": np.array([1.0, 2.0, 3.0]), "x_col": x_col}

    with pytest.raises(ValueError, match="冲突|conflict|不能"):
        app.resolve_external_x_axis(
            "profile.dat", profile, mode=mode, wavelength_a=wavelength
        )


def test_tab3_auto_prefers_explicit_q_header_over_chi_suffix():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    profile = {"x": np.array([0.01, 0.02, 0.03]), "x_col": "q_A^-1"}

    x, label, conversion = app.resolve_external_x_axis(
        "misleading.chi", profile, mode="auto", wavelength_a=""
    )

    np.testing.assert_array_equal(x, profile["x"])
    assert label == "Q_A^-1"
    assert conversion == "none"


def test_tab3_rejects_cross_axis_profile_subtraction():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    sample = {"x_label": "Q_A^-1", "x_conversion": "none"}
    background = {"x_label": "Chi_deg", "x_conversion": "none"}

    with pytest.raises(ValueError, match="物理轴|axis|Q_A"):
        app.assert_external_profile_axis_compatible(sample, background, "BG")

    converted_q = {
        "x_label": "Q_A^-1",
        "x_conversion": "two_theta_deg_to_q_a^-1",
    }
    app.assert_external_profile_axis_compatible(sample, converted_q, "Buffer")


def test_tab3_q_nm_inverse_converts_to_q_angstrom_inverse():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    profile = {"x": np.array([1.0, 2.0, 3.0]), "x_col": "q_nm^-1"}

    q, label, conversion = app.resolve_external_x_axis(
        "profile.dat", profile, mode="auto", wavelength_a=""
    )

    np.testing.assert_allclose(q, [0.1, 0.2, 0.3])
    assert label == "Q_A^-1"
    assert conversion == "q_nm^-1_to_q_a^-1"


@pytest.mark.parametrize("mode", ["auto", "q_a^-1"])
def test_tab3_ambiguous_named_q_unit_fails_closed(mode):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    profile = {"x": np.array([1.0, 2.0, 3.0]), "x_col": "q"}

    with pytest.raises(ValueError, match="单位|unit|歧义"):
        app.resolve_external_x_axis("profile.dat", profile, mode=mode, wavelength_a="")


def test_tab3_profile_parser_preserves_operator_fingerprint_header(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    fingerprint = "a" * 64
    profile_path = tmp_path / "profile.dat"
    profile_path.write_text(
        f"# calibration_context_fingerprint: {fingerprint}\n"
        "# q_A^-1 I_rel\n"
        "0.01 1\n0.02 2\n0.03 3\n",
        encoding="utf-8",
    )

    profile = app.read_external_1d_profile(profile_path)

    assert profile["x_col"] == "q_A^-1"
    assert profile["operator_provenance"]["calibration_context_fingerprint"] == fingerprint


def test_tab3_formal_external_profile_requires_matching_operator_provenance(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    context = _calibration_context(module, poni)
    profile = {"x_label": "Q_A^-1", "x_conversion": "none"}

    with pytest.raises(ValueError, match="operator provenance|来源|fingerprint"):
        app.require_external_profile_operator_provenance(profile, context, "sample.dat")

    profile["operator_provenance"] = {
        "calibration_context_fingerprint": "0" * 64,
    }
    with pytest.raises(ValueError, match="fingerprint|不匹配"):
        app.require_external_profile_operator_provenance(profile, context, "sample.dat")

    profile["operator_provenance"] = {
        "calibration_context_fingerprint": context.fingerprint(),
    }
    assert app.require_external_profile_operator_provenance(
        profile, context, "sample.dat"
    ) == context.fingerprint()


def test_tab3_auto_axis_fails_closed_for_unknown_x_column():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    profile = {"x": np.array([1.0, 2.0, 3.0]), "x_col": "x"}

    with pytest.raises(ValueError, match="X轴|axis"):
        app.resolve_external_x_axis("profile.dat", profile, mode="auto", wavelength_a="")


def test_tab3_raw_fallback_parameters_must_be_explicit():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.get_external_meta_for_file = lambda *_args: None
    app.parse_external_1d_header_meta = lambda *_args: {
        "exp": None,
        "mon": None,
        "trans": None,
        "thk_mm": None,
    }
    app.t3_sample_exp = _Var("")
    app.t3_sample_i0 = _Var("")
    app.t3_sample_t = _Var("")

    with pytest.raises(ValueError, match="显式|explicit"):
        app.resolve_external_sample_params("profile.dat", {}, "rate")

    app.t3_sample_exp.set("2")
    app.t3_sample_i0.set("3")
    app.t3_sample_t.set("0.5")
    result = app.resolve_external_sample_params("profile.dat", {}, "rate")
    assert result["norm"] == pytest.approx(3.0)
    assert result["source"] == "fixed_explicit"


def test_tab2_auto_references_do_not_require_fixed_bg_or_dark(monkeypatch):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.t2_bg_candidates = ["auto-bg.tif"]
    app.t2_dark_candidates = ["auto-dark.tif"]
    app.build_reference_library = lambda paths: [
        {"path": path, "exp": 1.0, "mon": 10.0, "trans": 1.0}
        for path in paths
    ]

    def fixed_reference_must_not_be_opened(_path):
        raise AssertionError("auto mode opened a fixed reference")

    monkeypatch.setattr(module.fabio, "open", fixed_reference_must_not_be_opened)
    result = app.prepare_batch_references(
        ref_mode="auto",
        bg_path="",
        dark_path="",
        monitor_mode="rate",
    )

    assert result["ref_mode"] == "auto"
    assert result["fixed_bg_net"] is None
    assert result["fixed_dark_data"] is None
    assert result["bg_library"][0]["path"] == "auto-bg.tif"
    assert result["dark_library"][0]["path"] == "auto-dark.tif"


def test_tab2_fixed_references_still_fail_closed_when_paths_are_missing():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)

    with pytest.raises(ValueError, match="固定参考模式.*背景或暗场"):
        app.prepare_batch_references(
            ref_mode="fixed",
            bg_path="",
            dark_path="",
            monitor_mode="rate",
        )

def test_tab2_dry_run_marks_calibration_gate_failure_as_blocked():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.language = "en"
    app.t2_files = ["sample.tif"]
    app.global_vars = {
        "k_factor": _Var(2.5),
        "poni_path": _Var("geometry.poni"),
        "bg_exp": _Var(1.0),
        "bg_i0": _Var(10.0),
    }
    app.t2_calc_mode = _Var("fixed")
    app.t2_mu = _Var("")
    app.t2_fixed_thk = _Var(1.0)
    app.t2_mask_path = _Var("")
    app.t2_flat_path = _Var("")
    app.t2_apply_solid_angle = _Var(True)
    app.t2_workers = _Var(1)
    app.t2_ref_mode = _Var("fixed")
    app.t2_strict_instrument = _Var(False)
    app.get_monitor_mode = lambda: "rate"
    app.get_selected_modes = lambda: ["1d_full"]
    app.resolve_t2_polarization = lambda: (False, None)
    app.resolve_sample_thickness_config = lambda **_kwargs: {
        "mode": "fixed",
        "mu_cm_inv": None,
        "fixed_thickness_cm": 0.1,
    }
    app.compute_norm_factor = lambda *_args: 1.0
    app.parse_header = lambda _path: (1.0, 10.0, 0.5)

    def reject_context(**_kwargs):
        raise ValueError("CalibrationContext missing")

    app.require_calibration_context_for_batch = reject_context
    captured = {}

    class StopAfterGate(Exception):
        pass

    def capture_gate(**kwargs):
        captured.update(kwargs)
        raise StopAfterGate

    app._evaluate_preflight_gate = capture_gate
    with pytest.raises(StopAfterGate):
        app.dry_run()

    assert captured["total_files"] == 1
    assert captured["failed_files"] == 1
    assert captured["warnings_count"] >= 1

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


def _calibration_context(
    module,
    poni: Path,
    mask: Path | None = None,
    flat: Path | None = None,
    *,
    complete: bool = True,
):
    source_hash = sha256_file(poni)
    reference_identity = builtin_reference_identity("SRM3600")
    provenance = {}
    if complete:
        provenance = {
            "standard_data_sha256": source_hash,
            "background_data_sha256": (source_hash,),
            "dark_data_sha256": (source_hash,),
            "standard_monitor": 10.0,
            "standard_transmission": 0.5,
            "standard_exposure_s": 1.0,
            "background_monitors": (10.0,),
            "background_transmissions": (1.0,),
            "background_exposure_s": (1.0,),
            "dark_exposure_s": (1.0,),
            "q_window": (0.01, 0.2),
            "reference_model_id": reference_identity.model_id,
            "reference_model_version": reference_identity.model_version,
            "reference_canonical_sha256": reference_identity.canonical_sha256,
            "background_scale_alpha": 1.0,
            "background_composition_rule": "arithmetic_mean_of_normalized_backgrounds",
            "integration_unit": "q_A^-1",
            "integration_method": "pyFAI.integrate1d",
            "integration_npt": 1000,
            "integration_engine_version": "test-pyfai",
            "robust_estimator": "median_with_mad_rejection",
            "robust_mad_multiplier": 3.0,
            "robust_positive_floor": 1e-9,
            "robust_min_points": 3,
            "robust_zero_mad_relative_tolerance": 1e-12,
        }
    return CalibrationContext(
        formula_version=module.WORKBENCH_FORMULA_VERSION,
        monitor_mode="rate",
        poni_sha256=source_hash,
        mask_sha256=sha256_file(mask) if mask is not None else None,
        flat_sha256=sha256_file(flat) if flat is not None else None,
        correct_solid_angle=True,
        polarization_factor=None,
        standard_key="SRM3600",
        standard_thickness_cm=0.1055,
        **provenance,
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


def test_workbench_blocks_incomplete_context_for_formal_tab2_output(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    app.calibration_context = _calibration_context(module, poni, complete=False)
    app.calibration_k_value = 2.5

    with pytest.raises(ValueError, match="来源不完整|provenance|缺少"):
        app.require_calibration_context_for_batch(
            k_factor=2.5,
            monitor_mode="rate",
            poni_path=poni,
            mask_path=None,
            flat_path=None,
            correct_solid_angle=True,
            polarization_factor=None,
        )


def test_workbench_blocks_complete_context_without_active_record(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    poni = tmp_path / "geometry.poni"
    poni.write_text("poni", encoding="utf-8")
    app.calibration_context = _calibration_context(module, poni)
    app.calibration_record_provenance_complete = False
    app.calibration_record_source_files_verified = False
    app.calibration_k_value = 2.5

    with pytest.raises(ValueError, match="CalibrationRecord|记录"):
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
    app.calibration_record_provenance_complete = True
    app.calibration_record_source_files_verified = True
    app.calibration_k_value = 2.5
    _trust_cached_record_for_gate_unit_test(app)

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
    # The SRM certificate coverage factor describes the reference values only;
    # it is not a system-wide factor for the workbench calibration budget.
    assert result.reference_coverage_factor is not None
    assert srm["k_expanded_uncertainty"] is None
    assert srm["coverage_factor"] is None
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

def test_tab3_workbench_parser_roundtrips_cansas_xml(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    output = tmp_path / "profile.xml"
    q = np.array([0.01, 0.02, 0.03])
    intensity = np.array([10.0, 9.0, 8.0])
    error = np.array([0.1, 0.2, 0.3])
    module.write_cansas1d_xml(output, q, intensity, error)

    profile = app.read_external_1d_profile(output)

    np.testing.assert_allclose(profile["x"], q)
    np.testing.assert_allclose(profile["i_rel"], intensity)
    np.testing.assert_allclose(profile["err_rel"], error)
    assert profile["x_col"] == "Q"
    assert profile["i_col"] == "I"
    assert profile["err_col"] == "Idev"
    assert profile["operator_provenance"] == {}


def test_tab3_external_buffer_empty_path_fails_closed_and_updates_status():
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.t3_buffer_enabled = _Var(True)
    app.t3_buffer_path = _Var("")
    app.t3_alpha = _Var(1.0)
    app.t3_buffer_status = _Var("")
    app.read_external_1d_profile = lambda _path: pytest.fail("parser must not be called")

    with pytest.raises(ValueError, match="Buffer"):
        app.prepare_external_buffer(
            pipeline_mode="scaled",
            calibration_context=SimpleNamespace(fingerprint=lambda: "a" * 64),
        )

    assert "Buffer error:" in app.t3_buffer_status.get()


def test_tab3_run_preloads_buffer_once_and_reports_provenance(tmp_path):
    module = _load_workbench_module()
    app = module.SAXSAbsWorkbenchApp.__new__(module.SAXSAbsWorkbenchApp)
    app.language = "en"
    fingerprint = "a" * 64

    def write_profile(path, values):
        path.write_text(
            f"# calibration_context_fingerprint: {fingerprint}\n"
            "# q_A^-1 I_rel Error\n"
            + "\n".join(
                f"{q:.3f} {intensity:.3f} 0.1"
                for q, intensity in zip((0.01, 0.02, 0.03), values)
            )
            + "\n",
            encoding="utf-8",
        )

    sample_a = tmp_path / "sample_a.dat"
    sample_b = tmp_path / "sample_b.dat"
    buffer_path = tmp_path / "buffer.dat"
    write_profile(sample_a, (10.0, 9.0, 8.0))
    write_profile(sample_b, (12.0, 11.0, 10.0))
    write_profile(buffer_path, (1.0, 1.0, 1.0))

    app.t3_files = [str(sample_a), str(sample_b)]
    app.global_vars = {"k_factor": _Var(1.0)}
    app.t3_pipeline_mode = _Var("scaled")
    app.t3_corr_mode = _Var("k_only")
    app.t3_fixed_thk = _Var(1.0)
    app.t3_buffer_enabled = _Var(True)
    app.t3_buffer_path = _Var(str(buffer_path))
    app.t3_alpha = _Var(0.5)
    app.t3_buffer_status = _Var("")
    app.t3_output_root = _Var(str(tmp_path / "output"))
    app.t3_resume_enabled = _Var(False)
    app.t3_overwrite = _Var(False)
    app.t3_output_format = _Var("tsv")
    app.t3_x_mode = _Var("auto")
    app.t3_wavelength_a = _Var("")
    app.t3_meta_csv_path = _Var("")
    app.t3_bg1d_path = _Var("")
    app.t3_dark1d_path = _Var("")
    app.t3_prog_bar = {}
    app.root = SimpleNamespace(update_idletasks=lambda: None)
    app.get_monitor_mode = lambda: "rate"
    context = SimpleNamespace(fingerprint=lambda: fingerprint)
    app.require_trusted_k_for_external = lambda *_args, **_kwargs: context
    app.log = lambda _message: None
    app.show_info = lambda *_args, **_kwargs: None
    app.show_error = lambda _title, message: pytest.fail(message)

    read_counts = {}
    real_read = app.read_external_1d_profile

    def counted_read(path):
        key = str(Path(path).resolve())
        read_counts[key] = read_counts.get(key, 0) + 1
        return real_read(path)

    app.read_external_1d_profile = counted_read
    app.run_external_1d_batch()

    resolved_buffer = str(buffer_path.resolve())
    assert read_counts[resolved_buffer] == 1
    assert "Buffer loaded:" in app.t3_buffer_status.get()

    report_dir = tmp_path / "output" / "processed_external_1d_reports"
    report_path = next(report_dir.glob("external1d_report_*.csv"))
    report = __import__("pandas").read_csv(report_path)
    assert report["BufferEnabled"].tolist() == [True, True]
    assert report["BufferApplied"].tolist() == [True, True]
    assert report["BufferPath"].tolist() == [resolved_buffer, resolved_buffer]
    assert report["BufferSHA256"].nunique() == 1
    assert report["BufferAlpha"].tolist() == pytest.approx([0.5, 0.5])
    assert report["BufferContextFingerprint"].tolist() == [fingerprint, fingerprint]

    meta_path = next(report_dir.glob("external1d_meta_*.json"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["buffer"] == {
        "enabled": True,
        "path": resolved_buffer,
        "sha256": sha256_file(buffer_path),
        "alpha": 0.5,
        "calibration_context_fingerprint": fingerprint,
    }

def _make_complete_custom_record(module, tmp_path):
    files = {}
    for name in ("poni", "standard", "background", "dark", "reference"):
        path = tmp_path / f"{name}.dat"
        path.write_text(f"original-{name}\n", encoding="utf-8")
        files[name] = path

    reference_q = np.array([0.01, 0.02, 0.03], dtype=np.float64)
    reference_i = np.array([100.0, 90.0, 80.0], dtype=np.float64)
    payload = _calibration_context(module, files["poni"]).to_dict()
    payload.update(
        {
            "poni_sha256": sha256_file(files["poni"]),
            "standard_key": "CustomReference",
            "standard_thickness_cm": 0.1,
            "standard_data_sha256": sha256_file(files["standard"]),
            "background_data_sha256": (sha256_file(files["background"]),),
            "dark_data_sha256": (sha256_file(files["dark"]),),
            "reference_curve_sha256": sha256_file(files["reference"]),
            "reference_model_id": "test.custom.reference",
            "reference_model_version": "v1",
            "reference_canonical_sha256": canonical_reference_sha256(
                reference_q, reference_i
            ),
        }
    )
    context = CalibrationContext.from_dict(payload)
    app = _record_app(module)
    record_path = tmp_path / "calibration_record.json"
    app.save_calibration_record(
        record_path,
        k_factor=2.5,
        calibration_context=context,
        calibration_uncertainty=None,
        poni_path=files["poni"],
        mask_path=None,
        flat_path=None,
        standard_data_path=files["standard"],
        background_data_paths=(files["background"],),
        dark_data_paths=(files["dark"],),
        reference_curve_path=files["reference"],
        reference_q=reference_q,
        reference_i=reference_i,
    )
    app.load_calibration_record(record_path)
    files["record"] = record_path
    return app, files


def _require_formal_tab2_context(app, poni_path):
    return app.require_calibration_context_for_batch(
        k_factor=2.5,
        monitor_mode="rate",
        poni_path=poni_path,
        mask_path=None,
        flat_path=None,
        correct_solid_angle=True,
        polarization_factor=None,
    )


@pytest.mark.parametrize("operation", ["modify", "delete"])
@pytest.mark.parametrize(
    "target",
    ["standard", "background", "dark", "reference", "record"],
)
def test_formal_gates_revalidate_record_and_sources_after_load(tmp_path, target, operation):
    module = _load_workbench_module()
    app, files = _make_complete_custom_record(module, tmp_path)

    assert _require_formal_tab2_context(app, files["poni"]) is app.calibration_context
    assert app.require_trusted_k_for_external(2.5) is app.calibration_context

    target_path = files[target]
    if operation == "delete":
        target_path.unlink()
    elif target == "record":
        target_path.write_text("{tampered-record", encoding="utf-8")
    else:
        target_path.write_bytes(target_path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="CalibrationRecord"):
        _require_formal_tab2_context(app, files["poni"])
    with pytest.raises(ValueError, match="CalibrationRecord"):
        app.require_trusted_k_for_external(2.5)


@pytest.mark.parametrize(
    ("output_format", "suffix"),
    [
        ("tsv", ".dat"),
        ("csv", ".csv"),
        ("cansas_xml", ".xml"),
        ("nxcansas_h5", ".h5"),
    ],
)
def test_project_owned_profile_roundtrips_through_formal_tab3_gate(
    tmp_path,
    output_format,
    suffix,
):
    if output_format == "nxcansas_h5":
        pytest.importorskip("h5py")
    module = _load_workbench_module()
    app, _files = _make_complete_custom_record(module, tmp_path)
    active_context = app.require_trusted_k_for_external(2.5)

    written = app.save_profile_table(
        tmp_path / "absolute.dat",
        np.array([0.01, 0.02, 0.03]),
        np.array([10.0, 9.0, 8.0]),
        np.array([0.1, 0.2, 0.3]),
        "Q_A^-1",
        output_format=output_format,
        calibration_context=active_context,
    )
    assert written.suffix == suffix

    profile = app.read_external_1d_profile(written)
    refreshed_context = app.require_trusted_k_for_external(2.5)
    fingerprint = app.require_external_profile_operator_provenance(
        profile,
        refreshed_context,
        written.name,
    )

    assert fingerprint == active_context.fingerprint()
    assert profile["operator_provenance"]["calibration_context_fingerprint"] == fingerprint
