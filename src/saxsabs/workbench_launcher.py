"""Installed launcher for the SAXSAbs Workbench GUI."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import logging
import os
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

from . import __version__


APP_NAME = "SAXSAbs Workbench"
APP_VERSION = __version__
SUPPORTED_LANGUAGES = ("en", "zh")
GUI_DEPENDENCIES = ("fabio", "pyFAI", "matplotlib")
_LOGGER = logging.getLogger(__name__)
_ACTIVE_LOG_PATH: Path | None = None


def _candidate_log_directories() -> tuple[Path, ...]:
    """Return user-scoped log locations without consulting the working directory."""
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        primary = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    elif os.environ.get("XDG_STATE_HOME"):
        primary = Path(os.environ["XDG_STATE_HOME"])
    else:
        primary = Path.home() / ".local" / "state"

    candidates = (
        primary / "SAXSAbs" / "logs",
        Path(tempfile.gettempdir()) / "SAXSAbs" / "logs",
    )
    # Environment variables can make the two locations identical.
    return tuple(dict.fromkeys(candidate.resolve(strict=False) for candidate in candidates))


def _setup_logging() -> Path | None:
    """Configure a launcher-owned file logger, falling back without aborting startup."""
    global _ACTIVE_LOG_PATH

    for handler in _LOGGER.handlers:
        if getattr(handler, "_saxsabs_launcher_file", False):
            return _ACTIVE_LOG_PATH

    for directory in _candidate_log_directories():
        log_path = directory / "saxsabs_workbench.log"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        except OSError:
            continue
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        setattr(handler, "_saxsabs_launcher_file", True)
        _LOGGER.addHandler(handler)
        _LOGGER.setLevel(logging.INFO)
        _ACTIVE_LOG_PATH = log_path
        return log_path

    _ACTIVE_LOG_PATH = None
    return None


def _resolve_app_source() -> Path:
    """Resolve only the GUI module shipped beside this package/source checkout."""
    package_dir = Path(__file__).resolve().parent
    package_parent = package_dir.parent
    candidates = [package_parent / "SASAbs.py"]
    if package_parent.name.casefold() == "src":
        candidates.append(package_parent.parent / "SASAbs.py")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Cannot find the SASAbs.py shipped with this launcher. Reinstall the package with "
        "the workbench files included, or launch the repository's saxsabs_workbench.py."
    )


def _require_gui_dependencies() -> None:
    missing = []
    for dependency in GUI_DEPENDENCIES:
        try:
            importlib.import_module(dependency)
        except ModuleNotFoundError:
            missing.append(dependency)
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(
            "Missing GUI optional dependencies: "
            f"{missing_list}. Install them with `pip install saxsabs[gui]`."
        )


def _load_legacy_module():
    app_source = _resolve_app_source()
    spec = importlib.util.spec_from_file_location("saxsabs_legacy_app", app_source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load application module: {app_source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--session", type=str, default="", help="Path to session json")
    parser.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default="en", help="UI language")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    return parser


def _accepts_language_keyword(app_cls: type) -> bool:
    try:
        signature = inspect.signature(app_cls)
    except (TypeError, ValueError):
        return True
    return any(
        parameter.name == "language" or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _create_app(app_cls: type, root: tk.Tk, language: str):
    if _accepts_language_keyword(app_cls):
        return app_cls(root, language=language)
    return app_cls(root)


def _show_launch_error(error_path: Path | None) -> None:
    if error_path is None:
        details = "No writable user or temporary log directory was available."
    else:
        details = f"See {error_path} for details."
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_NAME,
            f"Workbench launch failed. {details}\n\n工作台启动失败。{details}",
        )
        root.destroy()
    except Exception:
        pass


def _write_launch_error(error_text: str) -> Path | None:
    directories = []
    if _ACTIVE_LOG_PATH is not None:
        directories.append(_ACTIVE_LOG_PATH.parent)
    directories.extend(_candidate_log_directories())

    for directory in dict.fromkeys(directories):
        error_path = directory / "launch_error.log"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            error_path.write_text(error_text, encoding="utf-8")
        except OSError:
            continue
        return error_path
    return None


def run_with_error_handling(entrypoint: Callable[[], None] | None = None) -> None:
    if entrypoint is None:
        entrypoint = main
    try:
        entrypoint()
    except Exception:
        err = traceback.format_exc()
        _LOGGER.exception("Launcher failed")
        error_path = _write_launch_error(err)
        _show_launch_error(error_path)
        raise


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging()
    _LOGGER.info("Launcher started | lang=%s", args.lang)
    _require_gui_dependencies()

    mod = _load_legacy_module()
    app_cls = getattr(mod, "SAXSAbsWorkbenchApp", None)
    if app_cls is None:
        raise RuntimeError("SAXSAbsWorkbenchApp not found in legacy module")

    root = tk.Tk()
    app = _create_app(app_cls, root, args.lang)
    if args.session:
        _LOGGER.info("Applying session: %s", args.session)
        root.after(80, lambda: app.apply_session(args.session))
    root.mainloop()


if __name__ == "__main__":
    run_with_error_handling()
