from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.exists():
    sys.path.insert(0, str(_SRC_DIR))

from saxsabs.workbench_launcher import main, run_with_error_handling  # noqa: E402


if __name__ == "__main__":
    run_with_error_handling(main)
