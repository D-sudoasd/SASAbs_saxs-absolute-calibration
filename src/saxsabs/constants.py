"""Reference standard data and physical constants for SAXS absolute calibration.

This module provides a registry of calibration standards with authoritative
reference data.  All scattering cross-section values are in cm⁻¹ sr⁻¹.

Standards
---------
NIST SRM 3600 (Glassy Carbon)
    Allen, A.J. *et al.* (2017) *J. Appl. Cryst.* **50**, 462–474.
    NIST Certificate SP260-185.

Water (H₂O)
    Orthaber, D., Bergmann, A. & Glatter, O. (2000) *J. Appl. Cryst.* **33**,
    218–225.  Flat differential cross-section: 0.01632 cm⁻¹ at 20 °C.

Lupolen (LDPE)
    Russell, T.P. *et al.* (1988) *J. Appl. Cryst.* **21**, 629–638.
    Secondary standard — user must supply beamline-specific calibration curve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
HC_KEV_A: float = 12.398419843320025
"""Planck constant × speed of light product  E(keV) × λ(Å)."""


# ---------------------------------------------------------------------------
# NIST SRM 3600 — Glassy Carbon primary standard
# ---------------------------------------------------------------------------
NIST_SRM3600_DATA = np.array(
    [
        [0.008, 35.0],
        [0.010, 34.2],
        [0.020, 30.8],
        [0.030, 28.8],
        [0.040, 27.5],
        [0.050, 26.8],
        [0.060, 26.3],
        [0.080, 25.4],
        [0.100, 23.6],
        [0.120, 20.8],
        [0.150, 15.8],
        [0.180, 10.9],
        [0.200, 8.4],
        [0.220, 6.5],
        [0.250, 4.2],
    ],
    dtype=np.float64,
)
"""15-point dΣ/dΩ (cm⁻¹ sr⁻¹) vs *q* (Å⁻¹) from NIST SRM 3600 certificate."""


# ---------------------------------------------------------------------------
# Water isothermal compressibility look-up table (CRC Handbook, 97th ed.)
# κ_T in 10⁻¹⁰ Pa⁻¹  ;  T in °C
# ---------------------------------------------------------------------------
_WATER_KAPPA_T: dict[int, float] = {
    4: 5.068,
    5: 4.920,
    10: 4.788,
    15: 4.524,
    20: 4.591,
    25: 4.524,
    30: 4.475,
    35: 4.422,
    40: 4.399,
}
"""Isothermal compressibility of H₂O (×10⁻¹⁰ Pa⁻¹) at selected temperatures."""

_WATER_REF_TEMP_C: float = 20.0
_WATER_REF_DSDW: float = 0.01632  # cm⁻¹ at 20 °C


def water_dsdw(temperature_C: float = 20.0) -> float:
    """Return the absolute differential scattering cross-section of water.

    The reference value at 20 °C is **0.01632 cm⁻¹** (Orthaber *et al.* 2000).
    Temperature correction uses the ratio of (κ_T × T) at the requested
    temperature to the reference condition.

    Parameters
    ----------
    temperature_C : float
        Sample temperature in degrees Celsius.  Valid range: 4–40 °C.

    Returns
    -------
    float
        dΣ/dΩ in cm⁻¹.
    """
    if temperature_C < 4 or temperature_C > 40:
        raise ValueError(
            f"Water temperature {temperature_C} °C is outside the valid range 4–40 °C"
        )
    temps = sorted(_WATER_KAPPA_T.keys())
    kappas = [_WATER_KAPPA_T[t] for t in temps]
    kappa = float(np.interp(temperature_C, temps, kappas))
    kappa_ref = _WATER_KAPPA_T[int(_WATER_REF_TEMP_C)]

    T_K = temperature_C + 273.15
    T_ref_K = _WATER_REF_TEMP_C + 273.15

    return _WATER_REF_DSDW * (kappa * T_K) / (kappa_ref * T_ref_K)


# ---------------------------------------------------------------------------
# StandardReference dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StandardReference:
    """Metadata and data for a SAXS calibration standard.

    Attributes
    ----------
    name : str
        Human-readable display name.
    standard_type : str
        ``"primary"`` | ``"secondary"`` | ``"user_provided"``.
    q_data : np.ndarray | None
        Reference *q* values (Å⁻¹), or *None* for flat / user-provided.
    i_data : np.ndarray | None
        Reference dΣ/dΩ (cm⁻¹), or *None*.
    is_q_independent : bool
        *True* if scattering is flat across the SAXS regime (e.g. water).
    flat_value_cm_inv : float | None
        Flat scattering cross-section (cm⁻¹) when *is_q_independent*.
    reference : str
        Bibliographic citation.
    notes : str
        Implementation notes or warnings for the user.
    """

    name: str
    standard_type: str  # "primary" | "secondary" | "user_provided"
    q_data: np.ndarray | None = field(default=None, repr=False)
    i_data: np.ndarray | None = field(default=None, repr=False)
    is_q_independent: bool = False
    flat_value_cm_inv: float | None = None
    reference: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Built-in standard registry
# ---------------------------------------------------------------------------
STANDARD_REGISTRY: dict[str, StandardReference] = {
    "SRM3600": StandardReference(
        name="NIST SRM 3600 (Glassy Carbon)",
        standard_type="primary",
        q_data=NIST_SRM3600_DATA[:, 0].copy(),
        i_data=NIST_SRM3600_DATA[:, 1].copy(),
        is_q_independent=False,
        reference=(
            "Allen et al. (2017) J. Appl. Cryst. 50, 462–474; NIST SP260-185"
        ),
        notes="Recommended q window: 0.01–0.20 Å⁻¹.",
    ),
    "Water_20C": StandardReference(
        name="Water (H₂O) 20 °C",
        standard_type="primary",
        q_data=None,
        i_data=None,
        is_q_independent=True,
        flat_value_cm_inv=_WATER_REF_DSDW,
        reference=(
            "Orthaber, Bergmann & Glatter (2000) J. Appl. Cryst. 33, 218–225"
        ),
        notes="Flat signal; ensure careful parasitic-scattering subtraction.",
    ),
    "Lupolen": StandardReference(
        name="Lupolen (LDPE)",
        standard_type="user_provided",
        q_data=None,
        i_data=None,
        is_q_independent=False,
        reference="Russell et al. (1988) J. Appl. Cryst. 21, 629–638",
        notes="Batch-dependent; user must supply beamline calibration curve.",
    ),
    "Custom": StandardReference(
        name="Custom (user file)",
        standard_type="user_provided",
        q_data=None,
        i_data=None,
        is_q_independent=False,
        notes="Load a q–I reference curve from a data file.",
    ),
}


def get_reference_data(
    standard_key: str,
    temperature_C: float | None = None,
    q_user: np.ndarray | None = None,
    i_user: np.ndarray | None = None,
    q_range: tuple[float, float] = (0.005, 0.50),
    n_points: int = 100,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(q_ref, i_ref)`` arrays for the chosen calibration standard.

    Parameters
    ----------
    standard_key : str
        Key into :data:`STANDARD_REGISTRY`.
    temperature_C : float | None
        Water temperature (°C).  Ignored for non-water standards.
    q_user, i_user : ndarray | None
        User-supplied reference curve (required for ``"Lupolen"`` / ``"Custom"``).
    q_range : tuple[float, float]
        Range for synthesising a flat water curve.
    n_points : int
        Number of points for the synthetic water curve.

    Returns
    -------
    tuple[ndarray, ndarray]
        ``(q_ref, i_ref)`` both 1-D float64.

    Raises
    ------
    ValueError
        If a user-provided standard is selected but no data are supplied.
    """
    if standard_key not in STANDARD_REGISTRY:
        raise ValueError(f"Unknown standard key: {standard_key!r}")

    std = STANDARD_REGISTRY[standard_key]

    # --- built-in q-I curve (e.g. SRM 3600) --------------------------------
    if std.q_data is not None and std.i_data is not None:
        return std.q_data.copy(), std.i_data.copy()

    # --- flat / q-independent (e.g. water) ----------------------------------
    if std.is_q_independent:
        T = temperature_C if temperature_C is not None else _WATER_REF_TEMP_C
        dsdw = water_dsdw(T)
        q_arr = np.linspace(q_range[0], q_range[1], n_points)
        i_arr = np.full_like(q_arr, dsdw)
        return q_arr, i_arr

    # --- user-provided (Lupolen / Custom) -----------------------------------
    if q_user is not None and i_user is not None:
        return (
            np.asarray(q_user, dtype=np.float64),
            np.asarray(i_user, dtype=np.float64),
        )

    raise ValueError(
        f"Standard '{std.name}' requires a user-supplied reference curve "
        f"(q_user / i_user), but none was provided."
    )
