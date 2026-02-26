"""Installed launcher for the SAXSAbs Workbench GUI."""

from __future__ import annotations

import argparse
import importlib.util
import logging
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

from . import __version__


APP_NAME = "SAXSAbs Workbench"
APP_VERSION = __version__
SUPPORTED_LANGUAGES = ("en", "zh")
LOG_PATH = Path.cwd() / "logs" / "saxsabs_workbench.log"


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def _resolve_app_source() -> Path:
    candidates = [
        Path.cwd() / "SASAbs.py",
        Path(__file__).resolve().parents[2] / "SASAbs.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Cannot find SASAbs.py. Run this command inside the repository root, "
        "or launch the GUI with: python saxsabs_workbench.py"
    )


def _load_legacy_module():
    app_source = _resolve_app_source()
    spec = importlib.util.spec_from_file_location("saxsabs_legacy_app", app_source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load application module: {app_source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--session", type=str, default="", help="Path to session json")
    parser.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default="en", help="UI language")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    args = parser.parse_args(argv)
    logging.info("Launcher started | lang=%s", args.lang)

    mod = _load_legacy_module()
    app_cls = getattr(mod, "SAXSAbsWorkbenchApp", None)
    if app_cls is None:
        raise RuntimeError("SAXSAbsWorkbenchApp not found in legacy module")

    root = tk.Tk()
    try:
        app = app_cls(root, language=args.lang)
    except TypeError:
        app = app_cls(root)
    if args.session:
        logging.info("Applying session: %s", args.session)
        root.after(80, lambda: app.apply_session(args.session))
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        logging.exception("Launcher failed")
        (Path.cwd() / "launch_error.log").write_text(err, encoding="utf-8")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                APP_NAME,
                "启动失败。请查看 launch_error.log 获取详细错误信息。",
            )
            root.destroy()
        except Exception:
            pass
        raise
