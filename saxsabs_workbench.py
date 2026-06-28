from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.exists():
    sys.path.insert(0, str(_SRC_DIR))

from saxsabs.workbench_launcher import APP_NAME, APP_VERSION, main, run_with_error_handling  # noqa: E402

__all__ = ["APP_NAME", "APP_VERSION", "main", "run_with_error_handling"]


if __name__ == "__main__":
    run_with_error_handling(main)
