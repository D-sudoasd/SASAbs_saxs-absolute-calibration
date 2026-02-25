from __future__ import annotations

import argparse
import importlib.util
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import messagebox


APP_SOURCE = Path(__file__).resolve().parent / "SASAbs.py"


def _load_legacy_module():
    spec = importlib.util.spec_from_file_location("saxsabs_legacy_app", APP_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load application module: {APP_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description="SAXSAbs Workbench")
    parser.add_argument("--session", type=str, default="", help="Path to session json")
    args = parser.parse_args(argv)

    mod = _load_legacy_module()
    app_cls = getattr(mod, "SAXSAbsWorkbenchApp", None)
    if app_cls is None:
        raise RuntimeError("SAXSAbsWorkbenchApp not found in legacy module")

    root = tk.Tk()
    app = app_cls(root)
    if args.session:
        root.after(80, lambda: app.apply_session(args.session))
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        (Path(__file__).resolve().parent / "launch_error.log").write_text(err, encoding="utf-8")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "SAXSAbs Workbench",
                "启动失败。请查看 launch_error.log 获取详细错误信息。",
            )
            root.destroy()
        except Exception:
            pass
        raise
