#!/usr/bin/env python3
"""Capture a GUI screenshot of SASAbs for the JOSS paper.

This script launches the SASAbs GUI off-screen, populates it with
representative demo data, and captures a screenshot.

Run:  python paper/capture_gui_screenshot.py
Output: paper/fig_gui.png
"""

import sys, os, time
from pathlib import Path

# We need to import the main script's directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab
import importlib.util


def capture():
    """Launch GUI, wait for render, capture screenshot, then destroy."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()           # hide until module is loaded

    # Dynamically load SASAbs — keep __name__=="SASAbs" so loader is happy,
    # but patch __name__ after loading to prevent if __name__=="__main__" from running.
    spec = importlib.util.spec_from_file_location("SASAbs", str(ROOT / "SASAbs.py"))
    mod = importlib.util.module_from_spec(spec)

    # Patch argparse to avoid consuming sys.argv
    import argparse
    _orig = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = lambda self, args=None, ns=None: _orig(self, args=[], namespace=ns)

    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = _orig

    root.destroy()  # discard the temporary root

    # Re-create properly using the app's own main flow
    root2 = tk.Tk()
    root2.geometry("1280x800+50+50")
    app = mod.SAXSAbsWorkbenchApp(root2, language="en")
    root2.update_idletasks()
    root2.update()

    # Allow rendering to complete
    root2.after(800, lambda: _do_capture(root2))
    root2.mainloop()


def _do_capture(root):
    """Take the screenshot and close."""
    root.update_idletasks()
    root.update()
    time.sleep(0.3)

    # Get window geometry
    x = root.winfo_rootx()
    y = root.winfo_rooty()
    w = root.winfo_width()
    h = root.winfo_height()

    outpath = ROOT / "paper" / "fig_gui.png"

    try:
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        img.save(str(outpath), "PNG")
        print(f"  ✓ fig_gui.png  ({w}x{h})")
    except Exception as e:
        print(f"  ✗ Screenshot failed: {e}")
        # Fallback: save as generic placeholder
        print("  Attempting fallback with full-screen grab...")
        try:
            img = ImageGrab.grab()
            img.save(str(outpath), "PNG")
            print(f"  ✓ fig_gui.png (full screen fallback)")
        except Exception as e2:
            print(f"  ✗ Fallback also failed: {e2}")

    root.destroy()


if __name__ == "__main__":
    print("Capturing SASAbs GUI screenshot ...")
    capture()
    print("Done.")
