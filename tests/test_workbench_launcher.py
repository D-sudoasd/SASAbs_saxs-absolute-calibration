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


def test_resolve_app_source_uses_installed_sasabs_module_outside_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    installed_source = tmp_path / "site-packages" / "SASAbs.py"
    installed_source.parent.mkdir()
    installed_source.write_text("# installed legacy GUI\n", encoding="utf-8")
    outside_cwd = tmp_path / "not-repo"
    outside_cwd.mkdir()
    fake_launcher = tmp_path / "site-packages" / "saxsabs" / "workbench_launcher.py"

    monkeypatch.chdir(outside_cwd)
    monkeypatch.setattr(launcher, "__file__", str(fake_launcher))

    def fake_find_spec(name: str):
        if name == "SASAbs":
            return types.SimpleNamespace(origin=str(installed_source))
        return None

    monkeypatch.setattr(launcher.importlib.util, "find_spec", fake_find_spec)

    assert launcher._resolve_app_source() == installed_source


def test_wheel_includes_legacy_gui_module(tmp_path: Path):
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(REPO_ROOT),
            "--no-deps",
            "-w",
            str(tmp_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    wheels = list(tmp_path.glob("saxsabs-*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        entry_point_files = [
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        ]
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
        raise RuntimeError("Install GUI optional dependencies with `pip install saxsabs[gui]`: fabio")

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


def test_run_with_error_handling_writes_log_and_shows_messagebox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
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

    error_log = tmp_path / "launch_error.log"
    assert "launch exploded" in error_log.read_text(encoding="utf-8")
    assert shown_messages
    assert shown_messages[0][0] == launcher.APP_NAME
    assert "launch_error.log" in shown_messages[0][1]


def test_pyw_invokes_shared_error_wrapper():
    tree = ast.parse((REPO_ROOT / "saxsabs_workbench.pyw").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "run_with_error_handling"
        for call in calls
    )
    assert not any(isinstance(call.func, ast.Name) and call.func.id == "main" for call in calls)


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
