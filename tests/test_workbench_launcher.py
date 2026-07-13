import ast
import importlib.util
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest

from saxsabs import __version__
import saxsabs.workbench_launcher as launcher


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_workbench_launcher_version(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        launcher.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert __version__ in out


def test_workbench_launcher_version_does_not_setup_logging(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    def fail_logging_setup() -> None:
        raise AssertionError("--version should not configure launcher logging")

    monkeypatch.setattr(launcher, "_setup_logging", fail_logging_setup)

    with pytest.raises(SystemExit) as exc:
        launcher.main(["--version"])

    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_resolve_app_source_uses_shipped_module_not_cwd_shadow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    installed_source = tmp_path / "site-packages" / "SASAbs.py"
    installed_source.parent.mkdir()
    installed_source.write_text("# installed legacy GUI\n", encoding="utf-8")
    outside_cwd = tmp_path / "not-repo"
    outside_cwd.mkdir()
    cwd_shadow = outside_cwd / "SASAbs.py"
    cwd_shadow.write_text("raise AssertionError('cwd shadow loaded')\n", encoding="utf-8")
    fake_launcher = tmp_path / "site-packages" / "saxsabs" / "workbench_launcher.py"

    monkeypatch.chdir(outside_cwd)
    monkeypatch.setattr(launcher, "__file__", str(fake_launcher))

    assert launcher._resolve_app_source() == installed_source.resolve()
    assert launcher._resolve_app_source() != cwd_shadow.resolve()
    loaded = launcher._load_legacy_module()
    assert Path(loaded.__file__).resolve() == installed_source.resolve()


def test_resolve_app_source_uses_source_tree_not_cwd_shadow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cwd_shadow = tmp_path / "SASAbs.py"
    cwd_shadow.write_text("raise AssertionError('cwd shadow loaded')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert launcher._resolve_app_source() == (REPO_ROOT / "SASAbs.py").resolve()


def test_wheel_includes_legacy_gui_module(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(REPO_ROOT),
            "--no-deps",
            "--no-build-isolation",
            "--no-cache-dir",
            "-w",
            str(tmp_path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == 0, (
        "wheel build failed\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    wheels = list(tmp_path.glob("saxsabs-*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        entry_point_files = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        assert len(entry_point_files) == 1
        entry_points = wheel.read(entry_point_files[0]).decode("utf-8")

    assert "SASAbs.py" in names
    assert "saxsabs/workbench_launcher.py" in names
    assert "saxsabs-workbench = saxsabs.workbench_launcher:run_with_error_handling" in entry_points


def test_missing_gui_dependency_message_names_gui_extra(monkeypatch: pytest.MonkeyPatch):
    missing = {"fabio", "pyFAI", "matplotlib"}

    def fake_import_module(name: str):
        if name in missing:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return types.SimpleNamespace()

    monkeypatch.setattr(launcher.importlib, "import_module", fake_import_module)

    with pytest.raises(RuntimeError) as exc:
        launcher._require_gui_dependencies()

    message = str(exc.value)
    assert "saxsabs[gui]" in message
    for dependency in missing:
        assert dependency in message


def test_main_checks_gui_dependencies_before_loading_sasabs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(launcher, "_setup_logging", lambda: None)

    def fail_load() -> types.SimpleNamespace:
        raise AssertionError("SASAbs.py should not load before the GUI dependency check")

    def fail_gui_dependencies() -> None:
        raise RuntimeError(
            "Install GUI optional dependencies with `pip install saxsabs[gui]`: fabio"
        )

    monkeypatch.setattr(launcher, "_load_legacy_module", fail_load)
    monkeypatch.setattr(launcher, "_require_gui_dependencies", fail_gui_dependencies, raising=False)

    with pytest.raises(RuntimeError, match=r"saxsabs\[gui\].*fabio"):
        launcher.main([])


def test_main_does_not_swallow_internal_app_typeerror(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(launcher, "_setup_logging", lambda: None)
    monkeypatch.setattr(launcher, "_require_gui_dependencies", lambda: None, raising=False)

    calls = []

    class FakeRoot:
        def mainloop(self) -> None:
            pass

    class FakeApp:
        def __init__(self, root: FakeRoot, language: str = "default") -> None:
            calls.append(language)
            if language == "en":
                raise TypeError("internal construction failure")

    monkeypatch.setattr(launcher.tk, "Tk", FakeRoot)
    monkeypatch.setattr(
        launcher,
        "_load_legacy_module",
        lambda: types.SimpleNamespace(SAXSAbsWorkbenchApp=FakeApp),
    )

    with pytest.raises(TypeError, match="internal construction failure"):
        launcher.main([])

    assert calls == ["en"]


def test_setup_logging_falls_back_without_writing_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cwd = tmp_path / "read-only-cwd"
    cwd.mkdir()
    blocked = tmp_path / "blocked-location"
    blocked.write_text("not a directory", encoding="utf-8")
    user_log_dir = tmp_path / "user-state" / "logs"
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(
        launcher,
        "_candidate_log_directories",
        lambda: (blocked, user_log_dir),
    )

    try:
        log_path = launcher._setup_logging()
        assert log_path == user_log_dir / "saxsabs_workbench.log"
        assert log_path.is_file()
        assert not (cwd / "logs").exists()
    finally:
        for handler in list(launcher._LOGGER.handlers):
            if getattr(handler, "_saxsabs_launcher_file", False):
                launcher._LOGGER.removeHandler(handler)
                handler.close()
        launcher._ACTIVE_LOG_PATH = None


def test_run_with_error_handling_writes_user_log_and_shows_messagebox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cwd = tmp_path / "read-only-cwd"
    cwd.mkdir()
    user_log_dir = tmp_path / "user-state" / "logs"
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(launcher, "_candidate_log_directories", lambda: (user_log_dir,))
    monkeypatch.setattr(launcher, "_ACTIVE_LOG_PATH", None)
    shown_messages = []

    class FakeTk:
        def withdraw(self) -> None:
            pass

        def destroy(self) -> None:
            pass

    monkeypatch.setattr(launcher.tk, "Tk", FakeTk)
    monkeypatch.setattr(
        launcher.messagebox,
        "showerror",
        lambda title, body: shown_messages.append((title, body)),
    )

    def fail_launch() -> None:
        raise RuntimeError("launch exploded")

    with pytest.raises(RuntimeError, match="launch exploded"):
        launcher.run_with_error_handling(fail_launch)

    error_log = user_log_dir / "launch_error.log"
    assert "launch exploded" in error_log.read_text(encoding="utf-8")
    assert not (cwd / "launch_error.log").exists()
    assert not (cwd / "logs").exists()
    assert shown_messages
    assert shown_messages[0][0] == launcher.APP_NAME
    assert str(error_log) in shown_messages[0][1]


def test_run_with_error_handling_degrades_when_no_log_directory_is_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    blocked_a = tmp_path / "blocked-a"
    blocked_b = tmp_path / "blocked-b"
    blocked_a.write_text("not a directory", encoding="utf-8")
    blocked_b.write_text("not a directory", encoding="utf-8")
    shown_paths = []
    monkeypatch.setattr(
        launcher,
        "_candidate_log_directories",
        lambda: (blocked_a, blocked_b),
    )
    monkeypatch.setattr(launcher, "_ACTIVE_LOG_PATH", None)
    monkeypatch.setattr(launcher, "_show_launch_error", shown_paths.append)

    def fail_launch() -> None:
        raise RuntimeError("launch exploded")

    with pytest.raises(RuntimeError, match="launch exploded"):
        launcher.run_with_error_handling(fail_launch)

    assert shown_paths == [None]


def test_pyw_invokes_shared_error_wrapper():
    tree = ast.parse((REPO_ROOT / "saxsabs_workbench.pyw").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "run_with_error_handling"
        for call in calls
    )
    assert not any(isinstance(call.func, ast.Name) and call.func.id == "main" for call in calls)


def test_pyw_imports_package_launcher_not_cwd_module():
    tree = ast.parse((REPO_ROOT / "saxsabs_workbench.pyw").read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

    assert any(node.module == "saxsabs.workbench_launcher" for node in imports)
    assert not any(node.module == "saxsabs_workbench" for node in imports)


def test_batch_launcher_keeps_caller_cwd_and_uses_absolute_script_path():
    batch = (REPO_ROOT / "Start_SAXSAbs_Workbench.bat").read_text(encoding="utf-8")

    assert "cd /d" not in batch.casefold()
    assert '"%~dp0saxsabs_workbench.pyw"' in batch


def test_root_workbench_version_ignores_hostile_cwd(tmp_path: Path):
    (tmp_path / "SASAbs.py").write_text(
        "raise AssertionError('cwd SASAbs shadow loaded')\n", encoding="utf-8"
    )
    (tmp_path / "saxsabs.py").write_text(
        "raise AssertionError('cwd saxsabs shadow loaded')\n", encoding="utf-8"
    )

    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "saxsabs_workbench.py"), "--version"],
        cwd=tmp_path,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert __version__ in completed.stdout


def test_root_workbench_version_reuses_package_launcher_version(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(launcher, "APP_VERSION", "9.8.7-test")
    spec = importlib.util.spec_from_file_location(
        "saxsabs_workbench_version_test",
        REPO_ROOT / "saxsabs_workbench.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.APP_VERSION == "9.8.7-test"
