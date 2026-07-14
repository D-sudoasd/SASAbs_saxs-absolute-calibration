"""Pure safety helpers for the legacy desktop workbench.

The GUI is intentionally kept thin: this module owns deterministic window
sizing and the signed-in-memory preflight contract used by the Run buttons.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class WindowGeometry:
    """Screen-aware initial window geometry in Tk logical pixels."""

    width: int
    height: int
    x: int
    y: int

    @property
    def tk_geometry(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


def choose_initial_window_geometry(
    screen_width: int,
    screen_height: int,
    *,
    preferred_width: int = 1280,
    preferred_height: int = 900,
    minimum_width: int = 900,
    minimum_height: int = 600,
    horizontal_margin: int = 64,
    vertical_margin: int = 80,
) -> WindowGeometry:
    """Return a centered geometry that fits even a 1024 x 700 viewport.

    Tk reports screen dimensions in its own logical coordinate system.  A
    margin is retained for the taskbar/window chrome, while the application
    minimum remains below 980 x 640 as required by the scrollable workbench.
    """

    values = {
        "screen_width": screen_width,
        "screen_height": screen_height,
        "preferred_width": preferred_width,
        "preferred_height": preferred_height,
        "minimum_width": minimum_width,
        "minimum_height": minimum_height,
        "horizontal_margin": horizontal_margin,
        "vertical_margin": vertical_margin,
    }
    coerced: dict[str, int] = {}
    for name, value in values.items():
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc
        is_dimension = name.startswith(("screen_", "preferred_", "minimum_"))
        if number < 0 or (is_dimension and number == 0):
            raise ValueError(f"{name} must be positive")
        coerced[name] = number

    available_width = max(1, coerced["screen_width"] - coerced["horizontal_margin"])
    available_height = max(1, coerced["screen_height"] - coerced["vertical_margin"])
    width = min(coerced["preferred_width"], available_width)
    height = min(coerced["preferred_height"], available_height)

    # On unusually small displays the physical screen wins over the declared
    # minimum; Tk cannot make a window fit if the minimum is larger than it.
    width = min(
        coerced["screen_width"],
        max(min(coerced["minimum_width"], available_width), width),
    )
    height = min(
        coerced["screen_height"],
        max(min(coerced["minimum_height"], available_height), height),
    )
    x = max(0, (coerced["screen_width"] - width) // 2)
    y = max(0, (coerced["screen_height"] - height) // 2)
    return WindowGeometry(width=width, height=height, x=x, y=y)


def format_mu_for_batch(mu_cm_inv: float) -> str:
    """Preserve scientific precision when moving a calculated mu into the GUI."""

    try:
        value = float(mu_cm_inv)
    except (TypeError, ValueError) as exc:
        raise ValueError("mu_cm_inv must be a real number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("mu_cm_inv must be finite and > 0")
    return format(value, ".12g")


def _canonicalize(value: Any) -> Any:
    if is_dataclass(value):
        return _canonicalize(asdict(value))
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda item: str(item[0]))
        return {str(key): _canonicalize(item) for key, item in items}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
        )
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"__float__": repr(value)}
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Unsupported preflight configuration value: {type(value).__name__}")


def configuration_fingerprint(config: Mapping[str, Any]) -> str:
    """Hash a scientific/execution configuration using canonical JSON."""

    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    payload = json.dumps(
        _canonicalize(config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class WorkbenchPreflightApproval:
    """A dry-run result bound to the exact configuration it checked."""

    fingerprint: str
    level: str

    @property
    def allows_run(self) -> bool:
        return self.level in {"READY", "CAUTION"}


def approve_preflight(
    config: Mapping[str, Any],
    level: str,
) -> WorkbenchPreflightApproval:
    normalized_level = str(level).strip().upper()
    if normalized_level not in {"READY", "CAUTION", "BLOCKED"}:
        raise ValueError(f"Unknown preflight level: {level!r}")
    return WorkbenchPreflightApproval(
        fingerprint=configuration_fingerprint(config),
        level=normalized_level,
    )


def require_current_preflight(
    approval: WorkbenchPreflightApproval | None,
    config: Mapping[str, Any],
) -> WorkbenchPreflightApproval:
    """Fail closed unless a non-blocked dry-run matches the current config."""

    if approval is None:
        raise RuntimeError(
            "Run blocked: complete Dry Check for the current configuration first."
        )
    if not approval.allows_run:
        raise RuntimeError(
            f"Run blocked: the latest Dry Check level is {approval.level}; resolve errors and check again."
        )
    current = configuration_fingerprint(config)
    if current != approval.fingerprint:
        raise RuntimeError(
            "Run blocked: configuration changed after Dry Check; run Dry Check again."
        )
    return approval
