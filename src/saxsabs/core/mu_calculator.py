"""Universal X-ray mass-attenuation / linear-attenuation calculator.

Provides μ/ρ (cm²/g) and μ_linear (cm⁻¹) for any element or multi-element
composition at any photon energy, backed by the Elam database via **xraydb**.

Reference
---------
Elam, W.T., Ravel, B.D. & Sieber, J.R. (2002).
*Radiation Physics and Chemistry* **63**, 121–128.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

try:
    import xraydb
except ImportError as _exc:  # pragma: no cover
    raise ImportError(
        "The 'xraydb' package is required for the universal μ calculator.  "
        "Install it with:  pip install xraydb>=4.5"
    ) from _exc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MuResult:
    """Result of a linear-attenuation coefficient calculation.

    Attributes
    ----------
    mu_rho_cm2_g : float
        Mass attenuation coefficient of the mixture (cm²/g).
    mu_linear_cm_inv : float
        Linear attenuation coefficient  μ = (μ/ρ)_mix × ρ  (cm⁻¹).
    composition : dict[str, float]
        Element symbol → weight-fraction (0–1 scale, sums to ~1).
    density_g_cm3 : float
        Bulk density used (g/cm³).
    energy_keV : float
        Photon energy used (keV).
    element_contributions : dict[str, float]
        Element → its μ/ρ contribution (w_i × (μ/ρ)_i) in cm²/g.
    """

    mu_rho_cm2_g: float
    mu_linear_cm_inv: float
    composition: dict[str, float] = field(repr=False)
    density_g_cm3: float = 0.0
    energy_keV: float = 0.0
    element_contributions: dict[str, float] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Common material presets  { key: (display_name, composition_wt_frac, ρ) }
# Compositions are weight fractions (0–1).
# ---------------------------------------------------------------------------
MATERIAL_PRESETS: dict[str, tuple[str, dict[str, float], float]] = {
    "Ti-6Al-4V": (
        "Ti-6Al-4V (Grade 5)",
        {"Ti": 0.90, "Al": 0.06, "V": 0.04},
        4.43,
    ),
    "SS304": (
        "Stainless Steel 304",
        {"Fe": 0.69, "Cr": 0.19, "Ni": 0.10, "Mn": 0.02},
        7.93,
    ),
    "SS316L": (
        "Stainless Steel 316L",
        {"Fe": 0.65, "Cr": 0.17, "Ni": 0.12, "Mo": 0.025, "Mn": 0.02, "Si": 0.0075},
        7.99,
    ),
    "Al-7075": (
        "Al 7075",
        {"Al": 0.895, "Zn": 0.058, "Mg": 0.025, "Cu": 0.016, "Cr": 0.002},
        2.81,
    ),
    "Pure-Fe": ("Pure Fe", {"Fe": 1.0}, 7.874),
    "Pure-Cu": ("Pure Cu", {"Cu": 1.0}, 8.96),
    "Pure-Ti": ("Pure Ti", {"Ti": 1.0}, 4.506),
    "Pure-Al": ("Pure Al", {"Al": 1.0}, 2.70),
    "H2O": ("Water (H₂O)", {"H": 0.1119, "O": 0.8881}, 1.00),
    "SiO2": ("SiO₂ (quartz capillary)", {"Si": 0.4674, "O": 0.5326}, 2.20),
    "Kapton": (
        "Kapton (polyimide)",
        {"C": 0.6911, "H": 0.0265, "N": 0.0733, "O": 0.2091},
        1.42,
    ),
}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------
def mu_rho_single(element: str, energy_keV: float) -> float:
    """Return mass attenuation coefficient μ/ρ (cm²/g) for one element.

    Parameters
    ----------
    element : str
        Chemical symbol, e.g. ``"Fe"``, ``"Cu"``.
    energy_keV : float
        Photon energy in **keV**.

    Returns
    -------
    float
        μ/ρ in cm²/g.
    """
    energy_eV = energy_keV * 1000.0
    return float(xraydb.mu_elam(element, energy_eV))


def calculate_mu(
    composition: dict[str, float],
    density_g_cm3: float,
    energy_keV: float,
) -> MuResult:
    """Calculate linear attenuation coefficient for a multi-element material.

    Formula:  ``μ_linear = ρ × Σ(w_i × (μ/ρ)_i)``

    Parameters
    ----------
    composition : dict[str, float]
        Element symbol → weight fraction (0–1 scale).  The sum should be
        close to 1.0 (a warning is issued if the deviation exceeds 2 %).
    density_g_cm3 : float
        Bulk density (g/cm³).  Must be > 0.
    energy_keV : float
        Photon energy (keV).  Must be > 0.

    Returns
    -------
    MuResult

    Raises
    ------
    ValueError
        On invalid energy, density, or empty composition.
    """
    if energy_keV <= 0:
        raise ValueError(f"Energy must be > 0 keV, got {energy_keV}")
    if density_g_cm3 <= 0:
        raise ValueError(f"Density must be > 0 g/cm³, got {density_g_cm3}")
    if not composition:
        raise ValueError("Composition dict is empty")

    wt_sum = sum(composition.values())
    if abs(wt_sum - 1.0) > 0.02:
        logger.warning(
            "Weight fractions sum to %.4f (expected ~1.0); results may be inaccurate",
            wt_sum,
        )

    energy_eV = energy_keV * 1000.0
    contributions: dict[str, float] = {}
    mu_rho_mix = 0.0

    for elem, w_i in composition.items():
        mu_rho_i = float(xraydb.mu_elam(elem, energy_eV))
        contrib = w_i * mu_rho_i
        contributions[elem] = contrib
        mu_rho_mix += contrib

    mu_linear = mu_rho_mix * density_g_cm3

    return MuResult(
        mu_rho_cm2_g=mu_rho_mix,
        mu_linear_cm_inv=mu_linear,
        composition=dict(composition),
        density_g_cm3=density_g_cm3,
        energy_keV=energy_keV,
        element_contributions=contributions,
    )


# ---------------------------------------------------------------------------
# Composition parsing
# ---------------------------------------------------------------------------
_COMP_RE = re.compile(r"([A-Z][a-z]?)\s*:\s*([\d.]+)")


def parse_composition_string(text: str) -> dict[str, float]:
    """Parse ``"Fe:0.69, Cr:0.19, Ni:0.10"`` or ``"Fe:69, Cr:19, Ni:10"`` notation.

    If all values > 1 (and sum ≈ 100), they are treated as **weight percent**
    and divided by 100.  Otherwise they are taken as weight fractions.

    Returns
    -------
    dict[str, float]
        Element → weight fraction (0–1 scale).
    """
    pairs = _COMP_RE.findall(text)
    if not pairs:
        raise ValueError(f"Cannot parse composition string: {text!r}")

    comp = {elem: float(val) for elem, val in pairs}

    # Auto-detect percent vs fraction
    vals = list(comp.values())
    if all(v > 1 for v in vals) and abs(sum(vals) - 100.0) < 5.0:
        comp = {k: v / 100.0 for k, v in comp.items()}

    return comp
