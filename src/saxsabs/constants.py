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


def _coerce_reference_array(name: str, values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a 1-D array")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains non-finite values")
    return arr


# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
HC_KEV_A: float = 12.398419843320025
"""Planck constant × speed of light product  E(keV) × λ(Å)."""


# ---------------------------------------------------------------------------
# NIST SRM 3600 — Glassy Carbon primary standard
# ---------------------------------------------------------------------------
_NIST_SRM3600_CERTIFICATE_TABLE = np.array(
    [
        [0.00827568, 34.933380, 0.901092, 2.183336],
        [0.00888450, 34.427156, 0.888034, 2.151697],
        [0.00954735, 34.042170, 0.878103, 2.127636],
        [0.01026900, 33.698553, 0.869240, 2.106160],
        [0.01105780, 33.352529, 0.860314, 2.084533],
        [0.01191830, 33.027533, 0.851931, 2.064221],
        [0.01286110, 32.665045, 0.842581, 2.041565],
        [0.01389340, 32.306665, 0.833337, 2.019167],
        [0.01502510, 31.970485, 0.824665, 1.998155],
        [0.01626850, 31.559099, 0.814053, 1.972444],
        [0.01763650, 31.183763, 0.804372, 1.948985],
        [0.01914320, 30.861805, 0.796067, 1.928863],
        [0.02080510, 30.514300, 0.787103, 1.907144],
        [0.02264220, 30.084982, 0.776029, 1.880311],
        [0.02467500, 29.690414, 0.765852, 1.855651],
        [0.02692890, 29.249965, 0.754490, 1.828123],
        [0.02943170, 28.889970, 0.745204, 1.805623],
        [0.03221560, 28.449341, 0.733839, 1.778084],
        [0.03531810, 28.065980, 0.723950, 1.754124],
        [0.03878270, 27.704965, 0.714638, 1.731560],
        [0.04265880, 27.331304, 0.704999, 1.708207],
        [0.04700390, 26.974065, 0.695784, 1.685879],
        [0.05188580, 26.676952, 0.688121, 1.667309],
        [0.05738140, 26.401158, 0.681007, 1.650072],
        [0.06358290, 26.177427, 0.675236, 1.636089],
        [0.07059620, 25.904683, 0.668200, 1.619043],
        [0.07854840, 25.528734, 0.658503, 1.595546],
        [0.08758630, 24.917743, 0.642743, 1.557359],
        [0.09788540, 23.946472, 0.617689, 1.496655],
        [0.10965500, 22.472101, 0.579658, 1.404506],
        [0.11431200, 21.777228, 0.561734, 1.361077],
        [0.11839500, 21.112938, 0.544599, 1.319559],
        [0.12262400, 20.401110, 0.526238, 1.275069],
        [0.12314200, 20.287060, 0.523296, 1.267941],
        [0.12700400, 19.685107, 0.507769, 1.230319],
        [0.13154000, 18.909809, 0.487770, 1.181863],
        [0.13623900, 18.089242, 0.466604, 1.130578],
        [0.13864300, 17.679572, 0.456037, 1.104973],
        [0.14110500, 17.264117, 0.445321, 1.079007],
        [0.14614500, 16.372848, 0.422331, 1.023303],
        [0.15136500, 15.458350, 0.398742, 0.966147],
        [0.15651300, 14.587700, 0.376284, 0.911731],
        [0.15677100, 14.563071, 0.375648, 0.910192],
        [0.16237100, 13.616671, 0.351236, 0.851042],
        [0.16817000, 12.668549, 0.326780, 0.791784],
        [0.17417700, 11.752287, 0.303145, 0.734518],
        [0.17718100, 11.311460, 0.291774, 0.706966],
        [0.18039800, 10.862157, 0.280185, 0.678885],
        [0.18684100, 9.961979, 0.256965, 0.622624],
        [0.19351500, 9.116906, 0.235167, 0.569807],
        [0.20042700, 8.325578, 0.214755, 0.520349],
        [0.20116500, 8.224897, 0.212158, 0.514056],
        [0.20758600, 7.541931, 0.194541, 0.471371],
        [0.21500000, 6.854391, 0.176806, 0.428399],
        [0.22267900, 6.216070, 0.160341, 0.388504],
        [0.22909500, 5.715911, 0.147439, 0.357244],
        [0.23063300, 5.582366, 0.143995, 0.348898],
        [0.23887100, 4.999113, 0.128950, 0.312445],
        [0.24740200, 4.463604, 0.115137, 0.278975],
    ],
    dtype=np.float64,
)

NIST_SRM3600_DATA = _NIST_SRM3600_CERTIFICATE_TABLE[:, :2].copy()
"""Certified ``[q, dΣ/dΩ]`` values from NIST SRM 3600 Certificate Table 1."""

NIST_SRM3600_UNCERTAINTY = _NIST_SRM3600_CERTIFICATE_TABLE[:, 2:].copy()
"""Certificate ``[u_c, U]`` values corresponding to :data:`NIST_SRM3600_DATA`."""

NIST_SRM3600_COVERAGE_FACTOR: float = 2.4231
"""Coverage factor used by NIST for the SRM 3600 expanded uncertainty."""


# ---------------------------------------------------------------------------
# Water isothermal compressibility look-up table (IAPWS-95 at 0.101325 MPa)
# κ_T in 10⁻¹⁰ Pa⁻¹  ;  T in °C
# ---------------------------------------------------------------------------
_WATER_KAPPA_T: dict[int, float] = {
    4: 4.948056712,
    5: 4.916853822,
    10: 4.780829642,
    15: 4.673284441,
    20: 4.589128995,
    25: 4.524617174,
    30: 4.476921593,
    35: 4.443866799,
    40: 4.423755184,
}
"""IAPWS-95 isothermal compressibility of H₂O (×10⁻¹⁰ Pa⁻¹)."""

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
    try:
        temperature_C = float(temperature_C)
    except (TypeError, ValueError) as exc:
        raise ValueError("Water temperature must be a finite number") from exc
    if not np.isfinite(temperature_C):
        raise ValueError("Water temperature must be a finite number")
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
    standard_uncertainty_data : np.ndarray | None
        Point-wise combined standard uncertainties for a reference curve.
    expanded_uncertainty_data : np.ndarray | None
        Point-wise expanded uncertainties for a reference curve.
    coverage_factor : float | None
        Coverage factor associated with expanded uncertainties.
    """

    name: str
    standard_type: str  # "primary" | "secondary" | "user_provided"
    q_data: np.ndarray | None = field(default=None, repr=False)
    i_data: np.ndarray | None = field(default=None, repr=False)
    is_q_independent: bool = False
    flat_value_cm_inv: float | None = None
    reference: str = ""
    notes: str = ""
    standard_uncertainty_data: np.ndarray | None = field(default=None, repr=False)
    expanded_uncertainty_data: np.ndarray | None = field(default=None, repr=False)
    coverage_factor: float | None = None


# ---------------------------------------------------------------------------
# Built-in standard registry
# ---------------------------------------------------------------------------
STANDARD_REGISTRY: dict[str, StandardReference] = {
    "SRM3600": StandardReference(
        name="NIST SRM 3600 (Glassy Carbon)",
        standard_type="primary",
        q_data=NIST_SRM3600_DATA[:, 0].copy(),
        i_data=NIST_SRM3600_DATA[:, 1].copy(),
        standard_uncertainty_data=NIST_SRM3600_UNCERTAINTY[:, 0].copy(),
        expanded_uncertainty_data=NIST_SRM3600_UNCERTAINTY[:, 1].copy(),
        coverage_factor=NIST_SRM3600_COVERAGE_FACTOR,
        is_q_independent=False,
        reference=(
            "NIST SRM 3600 Certificate of Analysis (2016); "
            "Allen et al. (2017) J. Appl. Cryst. 50, 462–474"
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
        q_min, q_max = float(q_range[0]), float(q_range[1])
        if not (np.isfinite(q_min) and np.isfinite(q_max) and q_min < q_max):
            raise ValueError("q_range must contain finite values with q_min < q_max")
        n_points = int(n_points)
        if n_points < 2:
            raise ValueError("n_points must be >= 2")
        T = temperature_C if temperature_C is not None else _WATER_REF_TEMP_C
        dsdw = water_dsdw(T)
        q_arr = np.linspace(q_min, q_max, n_points)
        i_arr = np.full_like(q_arr, dsdw)
        return q_arr, i_arr

    # --- user-provided (Lupolen / Custom) -----------------------------------
    if q_user is not None and i_user is not None:
        q_arr = _coerce_reference_array("q_user", q_user)
        i_arr = _coerce_reference_array("i_user", i_user)
        if q_arr.shape != i_arr.shape:
            raise ValueError("q_user and i_user must have the same shape")
        if q_arr.size < 3:
            raise ValueError("user-supplied reference curve must contain at least 3 points")
        return q_arr, i_arr

    raise ValueError(
        f"Standard '{std.name}' requires a user-supplied reference curve "
        f"(q_user / i_user), but none was provided."
    )
