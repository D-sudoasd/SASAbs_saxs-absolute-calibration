"""Monitor-mode-aware normalization logic for SAXS absolute intensity.

Two normalization modes are supported:

* **rate** – the detector signal is a *rate* (counts per second), so the
  normalization factor is ``exposure_time * monitor_counts * transmission``.
* **integrated** – the detector signal is already integrated over the
  acquisition window, so the factor simplifies to
  ``monitor_counts * transmission``.
"""

from __future__ import annotations

import math


MONITOR_NORM_MODES = ("rate", "integrated")


def monitor_norm_formula(mode: str) -> str:
    """Return a human-readable formula string for the given normalization mode.

    Args:
        mode: One of ``'rate'`` or ``'integrated'`` (case-insensitive).

    Returns:
        A formula string such as ``'exp * I0 * T'``.

    Raises:
        ValueError: If *mode* is not recognized.
    """
    mode_n = str(mode).strip().lower()
    if mode_n == "rate":
        return "exp * I0 * T"
    if mode_n == "integrated":
        return "I0 * T"
    raise ValueError(f"Unknown I0 normalization mode: {mode}")


def compute_norm_factor(exp: float | None, mon: float | None, trans: float | None, mode: str) -> float:
    """Compute the normalization factor for absolute intensity conversion.

    Args:
        exp: Exposure time in seconds.  Required when *mode* is ``'rate'``;
            ignored for ``'integrated'``.
        mon: Beam-monitor counts (I₀).
        trans: Sample transmission factor (0 < T ≤ 1).
        mode: ``'rate'`` or ``'integrated'``.

    Returns:
        The normalization product.  Returns ``math.nan`` when any required
        input is missing, non-positive, or non-finite.

    Raises:
        ValueError: If *mode* is not recognized.
    """
    if mon is None or trans is None:
        return math.nan
    try:
        mon_v = float(mon)
        trans_v = float(trans)
    except Exception:
        return math.nan

    if not (math.isfinite(mon_v) and math.isfinite(trans_v)):
        return math.nan
    if mon_v <= 0 or trans_v <= 0:
        return math.nan

    mode_n = str(mode).strip().lower()
    if mode_n == "rate":
        if exp is None:
            return math.nan
        try:
            exp_v = float(exp)
        except Exception:
            return math.nan
        if not math.isfinite(exp_v) or exp_v <= 0:
            return math.nan
        return exp_v * mon_v * trans_v

    if mode_n == "integrated":
        return mon_v * trans_v

    raise ValueError(f"Unknown I0 normalization mode: {mode}")
