"""Installed launcher for the SAXSAbs Workbench GUI."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import logging
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


def _setup_logging() -> None:
    log_path = Path.cwd() / "logs" / "saxsabs_workbench.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path),
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def _installed_module_source() -> Path | None:
    spec = importlib.util.find_spec("SASAbs")
    origin = getattr(spec, "origin", None)
    if not origin or origin in {"built-in", "frozen"}:
        return None
    path = Path(origin)
    if path.exists():
        return path
    return None


def _resolve_app_source() -> Path:
    candidates = [
        Path.cwd() / "SASAbs.py",
        Path(__file__).resolve().parents[2] / "SASAbs.py",
    ]
    installed_source = _installed_module_source()
    if installed_source is not None:
        candidates.append(installed_source)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Cannot find SASAbs.py. Reinstall the package with the workbench files included, "
        "or launch the GUI from the repository with: python saxsabs_workbench.py"
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


def _show_launch_error(error_path: Path) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_NAME,
            "Workbench launch failed. See "
            f"{error_path} for details.\n\n启动失败。请查看 {error_path} 获取详细错误信息。",
        )
        root.destroy()
    except Exception:
        pass


def run_with_error_handling(entrypoint: Callable[[], None] | None = None) -> None:
    if entrypoint is None:
        entrypoint = main
    try:
        entrypoint()
    except Exception:
        err = traceback.format_exc()
        logging.exception("Launcher failed")
        error_path = Path.cwd() / "launch_error.log"
        try:
            error_path.write_text(err, encoding="utf-8")
        except OSError:
            logging.exception("Failed to write launch_error.log")
        _show_launch_error(error_path)
        raise


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging()
    logging.info("Launcher started | lang=%s", args.lang)
    _require_gui_dependencies()

    mod = _load_legacy_module()
    app_cls = getattr(mod, "SAXSAbsWorkbenchApp", None)
    if app_cls is None:
        raise RuntimeError("SAXSAbsWorkbenchApp not found in legacy module")

    root = tk.Tk()
    app = _create_app(app_cls, root, args.lang)
    if args.session:
        logging.info("Applying session: %s", args.session)
        root.after(80, lambda: app.apply_session(args.session))
    root.mainloop()


if __name__ == "__main__":
    run_with_error_handling()
