"""Traceable composition-model attenuation and fixed-thickness derivation.

The built-in data are the explicit NIST 30 keV values used for the 2025A1750
and 2026A1756 BL19B2 reprocessing.  This module is deliberately independent of
both campaign runners.  It supports only an explicit ``wt_fraction`` basis and
labels ideal-mixture density results as a partial-uncertainty model, not a
measured or certified alloy density.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import hmac
import json
import math
import re
from typing import Any, Iterable, Mapping

import numpy as np


WT_FRACTION_BASIS = "wt_fraction"
PARTIAL_UNCERTAINTY_STATUS = "partial"
COMPOSITION_SUM_ABS_TOLERANCE = 1.0e-12
DEFAULT_TRANSMISSION_DRIFT_WARNING_RELATIVE_SPAN = 0.05
MATERIAL_ATTENUATION_SCHEMA = "saxsabs.material_attenuation.v1"
FIXED_THICKNESS_DERIVATION_SCHEMA = "saxsabs.fixed_thickness_derivation.v1"

_ELEMENT_SYMBOL = re.compile(r"[A-Z][a-z]?")
_COMPOSITION_TOKEN = re.compile(
    r"([A-Z][a-z]?)\s*:\s*([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
)
_COMPOSITION_FRACTION_SUM_TOLERANCE = 0.02
_COMPOSITION_PERCENT_SUM_TOLERANCE = 2.0
_IDEAL_DENSITY_WARNING = "ideal_mixture_density_is_not_measured_bulk_density"
_POROSITY_WARNING = (
    "porosity_can_reduce_bulk_density_and_bias_linear_mu_and_derived_thickness"
)


def _nonempty_text(name: str, value: object) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a finite real number, not bool")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite real number, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


def _positive_number(name: str, value: object) -> float:
    number = _finite_number(name, value)
    if number <= 0:
        raise ValueError(f"{name} must be > 0, got {value!r}")
    return number


def _canonical_json(payload: Mapping[str, Any], *, indent: int | None = None) -> str:
    """Serialize with round-trip float precision and reject non-standard NaN tokens."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if indent is None else None,
        indent=indent,
        allow_nan=False,
    )


def parse_weight_composition_string(text: str) -> dict[str, float]:
    """Parse an explicit element:amount list into canonical weight fractions.

    The accepted input scale is deliberately fail-closed: values must sum to
    approximately 1 (fractions) or 100 (wt%).  Incomplete or ambiguous totals
    are rejected instead of silently renormalized.  This parser has no xraydb
    dependency so the fixed 30 keV NIST snapshot remains independently usable.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Cannot parse composition string: {text!r}")

    composition: dict[str, float] = {}
    for raw_token in text.split(","):
        token = raw_token.strip()
        match = _COMPOSITION_TOKEN.fullmatch(token)
        if match is None:
            raise ValueError(f"Cannot parse composition string: {text!r}")
        element, raw_value = match.groups()
        if element in composition:
            raise ValueError(f"Duplicate element in composition string: {element}")
        value = _finite_number(f"weight amount for {element}", raw_value)
        if value < 0:
            raise ValueError(f"weight amount for {element} cannot be negative")
        composition[element] = value

    total = math.fsum(composition.values())
    fraction_scale = math.isclose(
        total,
        1.0,
        rel_tol=0.0,
        abs_tol=_COMPOSITION_FRACTION_SUM_TOLERANCE,
    )
    percent_scale = math.isclose(
        total,
        100.0,
        rel_tol=0.0,
        abs_tol=_COMPOSITION_PERCENT_SUM_TOLERANCE,
    )
    if not (fraction_scale or percent_scale):
        raise ValueError(
            "Composition values must sum to approximately 1 (weight fractions) "
            f"or 100 (weight percent); got {total:.6g}"
        )
    if total <= 0:
        raise ValueError("composition total must be positive")

    items = list(composition.items())
    normalized = {element: value / total for element, value in items[:-1]}
    normalized[items[-1][0]] = 1.0 - math.fsum(normalized.values())
    return normalized


def provenance_sha256(payload: Mapping[str, Any]) -> str:
    """Hash a provenance mapping, excluding its top-level integrity field."""
    canonical = dict(payload)
    canonical.pop("provenance_sha256", None)
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def verify_provenance_fingerprint(payload: Mapping[str, Any]) -> None:
    """Fail closed if a provenance mapping has no valid matching fingerprint."""
    expected = payload.get("provenance_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("provenance_sha256 must be a 64-character SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in expected):
        raise ValueError("provenance_sha256 must contain lowercase hexadecimal characters")
    if not hmac.compare_digest(expected, provenance_sha256(payload)):
        raise ValueError("provenance fingerprint integrity check failed")


@dataclass(frozen=True)
class ElementAttenuationDatum:
    """One element row from a fixed-energy attenuation-table snapshot."""

    element: str
    mass_attenuation_cm2_g: float
    density_g_cm3: float

    def __post_init__(self) -> None:
        if not isinstance(self.element, str) or _ELEMENT_SYMBOL.fullmatch(self.element) is None:
            raise ValueError(f"invalid element symbol: {self.element!r}")
        object.__setattr__(
            self,
            "mass_attenuation_cm2_g",
            _positive_number("mass_attenuation_cm2_g", self.mass_attenuation_cm2_g),
        )
        object.__setattr__(
            self,
            "density_g_cm3",
            _positive_number("density_g_cm3", self.density_g_cm3),
        )


@dataclass(frozen=True)
class AttenuationTable:
    """Identity, sources, energy, and numerical rows of a table snapshot."""

    identity: str
    snapshot_id: str
    energy_kev: float
    retrieved_on: str
    mass_attenuation_source_id: str
    mass_attenuation_source_url: str
    density_source_id: str
    density_source_url: str
    elements: tuple[ElementAttenuationDatum, ...]
    note: str

    def __post_init__(self) -> None:
        for field_name in (
            "identity",
            "snapshot_id",
            "retrieved_on",
            "mass_attenuation_source_id",
            "mass_attenuation_source_url",
            "density_source_id",
            "density_source_url",
            "note",
        ):
            object.__setattr__(self, field_name, _nonempty_text(field_name, getattr(self, field_name)))
        object.__setattr__(self, "energy_kev", _positive_number("energy_kev", self.energy_kev))
        rows = tuple(self.elements)
        if not rows:
            raise ValueError("attenuation table must contain at least one element")
        if any(not isinstance(row, ElementAttenuationDatum) for row in rows):
            raise ValueError("attenuation table elements must be ElementAttenuationDatum rows")
        object.__setattr__(self, "elements", rows)
        symbols = [row.element for row in rows]
        if len(symbols) != len(set(symbols)):
            raise ValueError("attenuation table contains duplicate element rows")

    @property
    def element_map(self) -> dict[str, ElementAttenuationDatum]:
        return {row.element: row for row in self.elements}

    def element(self, symbol: str) -> ElementAttenuationDatum:
        try:
            return self.element_map[symbol]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"unknown element {symbol!r} for attenuation table {self.snapshot_id!r}"
            ) from exc

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "identity": self.identity,
            "snapshot_id": self.snapshot_id,
            "energy_kev": self.energy_kev,
            "retrieved_on": self.retrieved_on,
            "mass_attenuation_source": {
                "id": self.mass_attenuation_source_id,
                "url": self.mass_attenuation_source_url,
            },
            "density_source": {
                "id": self.density_source_id,
                "url": self.density_source_url,
            },
            "composition_basis": WT_FRACTION_BASIS,
            "elements": {
                row.element: {
                    "mass_attenuation_cm2_g": row.mass_attenuation_cm2_g,
                    "density_g_cm3": row.density_g_cm3,
                }
                for row in sorted(self.elements, key=lambda item: item.element)
            },
            "note": self.note,
        }
        if include_fingerprint:
            payload["provenance_sha256"] = provenance_sha256(payload)
        return payload

    def fingerprint(self) -> str:
        return provenance_sha256(self.to_dict(include_fingerprint=False))


NIST_30_KEV_TABLE = AttenuationTable(
    identity="NIST_PML_XRAY_MASS_ATTENUATION_COEFFICIENTS_TABLES_1_AND_3",
    snapshot_id="saxsabs.nist_xraymasscoef.30kev.20260713.v1",
    energy_kev=30.0,
    retrieved_on="2026-07-13",
    mass_attenuation_source_id=(
        "NIST PML X-Ray Mass Attenuation Coefficients, Table 3 elemental tables"
    ),
    mass_attenuation_source_url="https://physics.nist.gov/PhysRefData/XrayMassCoef/tab3.html",
    density_source_id="NIST PML X-Ray Mass Attenuation Coefficients, Table 1",
    density_source_url="https://physics.nist.gov/PhysRefData/XrayMassCoef/tab1.html",
    elements=(
        ElementAttenuationDatum("Al", 1.128, 2.699),
        ElementAttenuationDatum("Ti", 4.972, 4.54),
        ElementAttenuationDatum("V", 5.564, 6.11),
        ElementAttenuationDatum("Zr", 24.85, 6.506),
        ElementAttenuationDatum("Nb", 26.66, 8.57),
        ElementAttenuationDatum("Sn", 41.21, 7.31),
    ),
    note=(
        "Total mass-attenuation coefficients are direct 30 keV table nodes. "
        "Element densities feed an ideal specific-volume mixture model and are "
        "not NIST-certified alloy densities."
    ),
)


def _validate_wt_fraction_composition(
    composition: Mapping[str, object],
    table: AttenuationTable,
) -> tuple[tuple[str, float], ...]:
    if not isinstance(composition, Mapping) or not composition:
        raise ValueError("composition must be a non-empty element-to-weight-fraction mapping")
    validated: list[tuple[str, float]] = []
    for element, raw_fraction in composition.items():
        if not isinstance(element, str) or _ELEMENT_SYMBOL.fullmatch(element) is None:
            raise ValueError(f"invalid element symbol in composition: {element!r}")
        table.element(element)
        fraction = _finite_number(f"weight fraction for {element}", raw_fraction)
        if fraction < 0:
            raise ValueError(f"weight fraction for {element} cannot be negative")
        validated.append((element, fraction))
    total = math.fsum(fraction for _, fraction in validated)
    if not math.isclose(
        total,
        1.0,
        rel_tol=0.0,
        abs_tol=COMPOSITION_SUM_ABS_TOLERANCE,
    ):
        raise ValueError(
            "wt_fraction composition must sum to 1 within "
            f"{COMPOSITION_SUM_ABS_TOLERANCE:g}; got {total:.17g}"
        )
    return tuple(sorted(validated))


@dataclass(frozen=True)
class NominalMaterialSpec:
    """A locked nominal wt-fraction composition used by regression tests."""

    key: str
    display_name: str
    composition_wt_fraction: tuple[tuple[str, float], ...]
    golden_mu_cm_inv: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _nonempty_text("key", self.key))
        object.__setattr__(self, "display_name", _nonempty_text("display_name", self.display_name))
        raw_composition = tuple(self.composition_wt_fraction)
        if len(raw_composition) != len(dict(raw_composition)):
            raise ValueError("nominal composition contains duplicate element rows")
        validated = _validate_wt_fraction_composition(
            dict(raw_composition),
            NIST_30_KEV_TABLE,
        )
        object.__setattr__(self, "composition_wt_fraction", validated)
        object.__setattr__(
            self,
            "golden_mu_cm_inv",
            _positive_number("golden_mu_cm_inv", self.golden_mu_cm_inv),
        )

    def composition_dict(self) -> dict[str, float]:
        return dict(self.composition_wt_fraction)


NOMINAL_MATERIALS: dict[str, NominalMaterialSpec] = {
    "ti2448": NominalMaterialSpec(
        "ti2448",
        "Ti-24Nb-4Zr-8Sn",
        (("Ti", 0.64), ("Nb", 0.24), ("Zr", 0.04), ("Sn", 0.08)),
        74.550355,
    ),
    "ti6al4v": NominalMaterialSpec(
        "ti6al4v",
        "Ti-6Al-4V",
        (("Ti", 0.90), ("Al", 0.06), ("V", 0.04)),
        20.989980,
    ),
    "zr2p5nb": NominalMaterialSpec(
        "zr2p5nb",
        "Zr-2.5Nb",
        (("Zr", 0.975), ("Nb", 0.025)),
        162.949617,
    ),
}


def identify_nominal_material(
    composition: Mapping[str, object],
    *,
    absolute_tolerance: float = COMPOSITION_SUM_ABS_TOLERANCE,
) -> NominalMaterialSpec | None:
    """Return the matching locked nominal material, or ``None`` for a custom alloy."""
    tolerance = _finite_number("absolute_tolerance", absolute_tolerance)
    if tolerance < 0:
        raise ValueError("absolute_tolerance must be >= 0")
    validated = dict(_validate_wt_fraction_composition(composition, NIST_30_KEV_TABLE))
    for spec in NOMINAL_MATERIALS.values():
        nominal = spec.composition_dict()
        if set(validated) != set(nominal):
            continue
        if all(
            math.isclose(
                validated[element],
                nominal[element],
                rel_tol=0.0,
                abs_tol=tolerance,
            )
            for element in validated
        ):
            return spec
    return None


@dataclass(frozen=True)
class MaterialAttenuationResult:
    """Composition-model attenuation with every numerical input attached."""

    material_key: str | None
    material_name: str | None
    composition_wt_fraction: tuple[tuple[str, float], ...]
    table: AttenuationTable
    element_contributions_cm2_g: tuple[tuple[str, float], ...]
    mixture_mass_attenuation_cm2_g: float
    ideal_mixture_density_g_cm3: float
    linear_attenuation_cm_inv: float
    regression_golden_mu_cm_inv: float | None
    porosity_warning: str | None
    uncertainty_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.table, AttenuationTable):
            raise ValueError("table must be an AttenuationTable")
        if self.material_key is not None:
            object.__setattr__(
                self,
                "material_key",
                _nonempty_text("material_key", self.material_key),
            )
        if self.material_name is not None:
            object.__setattr__(
                self,
                "material_name",
                _nonempty_text("material_name", self.material_name),
            )

        raw_composition = tuple(self.composition_wt_fraction)
        if len(raw_composition) != len(dict(raw_composition)):
            raise ValueError("composition contains duplicate element rows")
        composition = _validate_wt_fraction_composition(
            dict(raw_composition),
            self.table,
        )
        object.__setattr__(self, "composition_wt_fraction", composition)

        raw_contributions = tuple(self.element_contributions_cm2_g)
        contribution_map = dict(raw_contributions)
        if len(raw_contributions) != len(contribution_map):
            raise ValueError("element contributions contain duplicate element rows")
        if set(contribution_map) != {element for element, _ in composition}:
            raise ValueError("element contribution keys must match composition keys")
        contributions: list[tuple[str, float]] = []
        for element, fraction in composition:
            value = _finite_number(
                f"mass attenuation contribution for {element}",
                contribution_map[element],
            )
            if value < 0:
                raise ValueError("mass attenuation contributions cannot be negative")
            expected = fraction * self.table.element(element).mass_attenuation_cm2_g
            if not math.isclose(value, expected, rel_tol=1.0e-15, abs_tol=1.0e-15):
                raise ValueError(f"mass attenuation contribution mismatch for {element}")
            contributions.append((element, value))
        object.__setattr__(self, "element_contributions_cm2_g", tuple(contributions))

        mixture_mu_rho = _positive_number(
            "mixture_mass_attenuation_cm2_g",
            self.mixture_mass_attenuation_cm2_g,
        )
        expected_mu_rho = math.fsum(value for _, value in contributions)
        if not math.isclose(mixture_mu_rho, expected_mu_rho, rel_tol=1.0e-15):
            raise ValueError("mixture mass attenuation does not match element contributions")
        object.__setattr__(self, "mixture_mass_attenuation_cm2_g", mixture_mu_rho)

        ideal_density = _positive_number(
            "ideal_mixture_density_g_cm3",
            self.ideal_mixture_density_g_cm3,
        )
        expected_density = 1.0 / math.fsum(
            fraction / self.table.element(element).density_g_cm3
            for element, fraction in composition
        )
        if not math.isclose(ideal_density, expected_density, rel_tol=1.0e-15):
            raise ValueError("ideal mixture density does not match composition and element densities")
        object.__setattr__(self, "ideal_mixture_density_g_cm3", ideal_density)

        linear_mu = _positive_number(
            "linear_attenuation_cm_inv",
            self.linear_attenuation_cm_inv,
        )
        if not math.isclose(
            linear_mu,
            mixture_mu_rho * ideal_density,
            rel_tol=1.0e-15,
        ):
            raise ValueError("linear attenuation does not match mixture mu/rho times density")
        object.__setattr__(self, "linear_attenuation_cm_inv", linear_mu)

        if self.regression_golden_mu_cm_inv is not None:
            golden = _positive_number(
                "regression_golden_mu_cm_inv",
                self.regression_golden_mu_cm_inv,
            )
            if not math.isclose(linear_mu, golden, rel_tol=0.0, abs_tol=0.5e-6):
                raise ValueError("regression golden mu does not match the calculated value")
            object.__setattr__(self, "regression_golden_mu_cm_inv", golden)
        if self.porosity_warning is not None:
            object.__setattr__(
                self,
                "porosity_warning",
                _nonempty_text("porosity_warning", self.porosity_warning),
            )
        limitations = tuple(
            _nonempty_text("uncertainty limitation", value)
            for value in self.uncertainty_limitations
        )
        if not limitations:
            raise ValueError("uncertainty_limitations must not be empty")
        object.__setattr__(self, "uncertainty_limitations", limitations)

    @property
    def composition_basis(self) -> str:
        return WT_FRACTION_BASIS

    @property
    def uncertainty_status(self) -> str:
        return PARTIAL_UNCERTAINTY_STATUS

    @property
    def parameter_source(self) -> str:
        return "composition_model_derived"

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        contributions = dict(self.element_contributions_cm2_g)
        payload: dict[str, Any] = {
            "schema": MATERIAL_ATTENUATION_SCHEMA,
            "material_key": self.material_key,
            "material": self.material_name,
            "composition_basis": self.composition_basis,
            "composition_wt_fraction": dict(self.composition_wt_fraction),
            "attenuation_table": self.table.to_dict(include_fingerprint=True),
            "element_inputs": {
                element: {
                    "wt_fraction": fraction,
                    "mass_attenuation_cm2_g": self.table.element(
                        element
                    ).mass_attenuation_cm2_g,
                    "density_g_cm3": self.table.element(element).density_g_cm3,
                    "mass_attenuation_contribution_cm2_g": contributions[element],
                }
                for element, fraction in self.composition_wt_fraction
            },
            "mass_attenuation_model": "nist_weight_fraction_mixture_rule",
            "mass_attenuation_model_formula": "(mu/rho)_mix = sum_i(w_i * (mu/rho)_i)",
            "mixture_mass_attenuation_cm2_g": self.mixture_mass_attenuation_cm2_g,
            "density_model": "ideal_specific_volume_additivity",
            "density_model_formula": "rho_ideal = 1 / sum_i(w_i / rho_i)",
            "ideal_mixture_density_g_cm3": self.ideal_mixture_density_g_cm3,
            "mu_model": "mass_attenuation_times_ideal_mixture_density",
            "mu_model_formula": "mu = (mu/rho)_mix * rho_ideal",
            "linear_attenuation_cm_inv": self.linear_attenuation_cm_inv,
            "regression_golden_mu_cm_inv": self.regression_golden_mu_cm_inv,
            "parameter_source": self.parameter_source,
            "uncertainty_status": self.uncertainty_status,
            "uncertainty_limitations": list(self.uncertainty_limitations),
            "porosity_warning": self.porosity_warning,
        }
        if include_fingerprint:
            payload["provenance_sha256"] = provenance_sha256(payload)
        return payload

    def fingerprint(self) -> str:
        return provenance_sha256(self.to_dict(include_fingerprint=False))

    def to_json(self, *, indent: int = 2) -> str:
        return _canonical_json(self.to_dict(), indent=indent) + "\n"


def calculate_material_attenuation(
    composition: Mapping[str, object],
    *,
    composition_basis: str,
    table: AttenuationTable = NIST_30_KEV_TABLE,
    material_key: str | None = None,
    material_name: str | None = None,
    porosity_risk: bool = False,
) -> MaterialAttenuationResult:
    """Calculate mixture ``mu/rho``, ideal density, and linear ``mu``.

    The mandatory basis must be exactly ``wt_fraction``.  Callers must convert
    wt% or at% themselves so a scale can never be guessed silently.
    """
    if composition_basis != WT_FRACTION_BASIS:
        raise ValueError(
            "composition_basis must be exactly 'wt_fraction'; convert wt_percent "
            "or atomic fractions explicitly before calculation"
        )
    if not isinstance(table, AttenuationTable):
        raise ValueError("table must be an AttenuationTable")
    if not isinstance(porosity_risk, bool):
        raise ValueError("porosity_risk must be bool")
    if material_key is not None:
        material_key = _nonempty_text("material_key", material_key)
    if material_name is not None:
        material_name = _nonempty_text("material_name", material_name)

    validated = _validate_wt_fraction_composition(composition, table)
    contributions = tuple(
        (element, fraction * table.element(element).mass_attenuation_cm2_g)
        for element, fraction in validated
    )
    mixture_mu_rho = math.fsum(value for _, value in contributions)
    specific_volume = math.fsum(
        fraction / table.element(element).density_g_cm3
        for element, fraction in validated
    )
    ideal_density = 1.0 / specific_volume
    linear_mu = mixture_mu_rho * ideal_density
    return MaterialAttenuationResult(
        material_key=material_key,
        material_name=material_name,
        composition_wt_fraction=validated,
        table=table,
        element_contributions_cm2_g=contributions,
        mixture_mass_attenuation_cm2_g=mixture_mu_rho,
        ideal_mixture_density_g_cm3=ideal_density,
        linear_attenuation_cm_inv=linear_mu,
        regression_golden_mu_cm_inv=None,
        porosity_warning=_POROSITY_WARNING if porosity_risk else None,
        uncertainty_limitations=(
            "actual_bulk_density_and_porosity_are_not_measured_by_this_model",
            "database_and_energy_bandwidth_uncertainty_are_not_a_total_uncertainty_budget",
        ),
    )


def calculate_nominal_material_attenuation(
    material_key: str,
    *,
    porosity_risk: bool = False,
) -> MaterialAttenuationResult:
    """Calculate one of the three campaign-locked nominal materials."""
    key = _nonempty_text("material_key", material_key).casefold()
    try:
        spec = NOMINAL_MATERIALS[key]
    except KeyError as exc:
        raise ValueError(f"unknown nominal material key: {material_key!r}") from exc
    result = calculate_material_attenuation(
        spec.composition_dict(),
        composition_basis=WT_FRACTION_BASIS,
        material_key=spec.key,
        material_name=spec.display_name,
        porosity_risk=porosity_risk,
    )
    if not math.isclose(
        result.linear_attenuation_cm_inv,
        spec.golden_mu_cm_inv,
        rel_tol=0.0,
        abs_tol=0.5e-6,
    ):
        raise RuntimeError(
            f"locked NIST 30 keV mu drift for {key}: "
            f"{result.linear_attenuation_cm_inv:.17g} != {spec.golden_mu_cm_inv:.6f}"
        )
    return replace(result, regression_golden_mu_cm_inv=spec.golden_mu_cm_inv)


@dataclass(frozen=True)
class TransmissionStatistics:
    """Median/MAD/P5/P95 summary used to select representative transmission."""

    anchor_scope: str
    count: int
    median: float
    mad: float
    p5: float
    p95: float
    minimum: float
    maximum: float
    relative_p5_p95_span: float
    drift_warning_threshold: float
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_scope": self.anchor_scope,
            "count": self.count,
            "median": self.median,
            "mad": self.mad,
            "p5": self.p5,
            "p95": self.p95,
            "min": self.minimum,
            "max": self.maximum,
            "relative_p5_p95_span": self.relative_p5_p95_span,
            "drift_warning_threshold": self.drift_warning_threshold,
            "percentile_method": "linear",
            "warnings": list(self.warnings),
        }


def robust_transmission_statistics(
    transmissions: Iterable[object],
    *,
    anchor_scope: str = "provided_transmissions",
    drift_warning_relative_span: float = DEFAULT_TRANSMISSION_DRIFT_WARNING_RELATIVE_SPAN,
) -> TransmissionStatistics:
    """Summarize transmissions after strict finite ``0 < T <= 1`` validation."""
    scope = _nonempty_text("anchor_scope", anchor_scope)
    threshold = _finite_number(
        "drift_warning_relative_span",
        drift_warning_relative_span,
    )
    if threshold < 0:
        raise ValueError("drift_warning_relative_span must be >= 0")
    if isinstance(transmissions, (str, bytes)):
        raise ValueError("transmissions must be a non-empty iterable of numeric values")
    try:
        raw_values = tuple(transmissions)
    except TypeError as exc:
        raise ValueError("transmissions must be a non-empty iterable") from exc
    if not raw_values:
        raise ValueError("transmissions must not be empty")

    values: list[float] = []
    for index, raw_value in enumerate(raw_values):
        value = _finite_number(f"transmission[{index}]", raw_value)
        if value <= 0 or value > 1:
            raise ValueError(
                f"transmission[{index}] must be in the interval (0, 1], got {raw_value!r}"
            )
        values.append(value)
    array = np.asarray(values, dtype=np.float64)
    median = float(np.median(array))
    mad = float(np.median(np.abs(array - median)))
    p5, p95 = (
        float(value) for value in np.percentile(array, [5.0, 95.0], method="linear")
    )
    relative_span = (p95 - p5) / median
    warnings: list[str] = []
    if relative_span > threshold:
        warnings.append("transmission_p5_p95_relative_span_exceeds_threshold")
    if median == 1.0:
        warnings.append("representative_transmission_is_one_zero_effective_thickness")
    return TransmissionStatistics(
        anchor_scope=scope,
        count=int(array.size),
        median=median,
        mad=mad,
        p5=p5,
        p95=p95,
        minimum=float(np.min(array)),
        maximum=float(np.max(array)),
        relative_p5_p95_span=relative_span,
        drift_warning_threshold=threshold,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class FixedThicknessDerivation:
    """One fixed Beer-Lambert thickness with complete derivation provenance."""

    material: MaterialAttenuationResult
    transmission_statistics: TransmissionStatistics
    fixed_thickness_cm: float
    warnings: tuple[str, ...]

    @property
    def representative_transmission(self) -> float:
        return self.transmission_statistics.median

    @property
    def uncertainty_status(self) -> str:
        return self.material.uncertainty_status

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": FIXED_THICKNESS_DERIVATION_SCHEMA,
            "material_attenuation": self.material.to_dict(include_fingerprint=True),
            "representative_transmission": self.representative_transmission,
            "transmission_statistics": self.transmission_statistics.to_dict(),
            "fixed_thickness_cm": self.fixed_thickness_cm,
            "method": "composition_model_mu_and_robust_median_transmission_fixed_thickness",
            "formula": "d_fixed = -ln(T_rep) / mu",
            "mu_cm_inv_used": self.material.linear_attenuation_cm_inv,
            "parameter_source": self.material.parameter_source,
            "uncertainty_status": self.uncertainty_status,
            "porosity_warning": self.material.porosity_warning,
            "warnings": list(self.warnings),
        }
        if include_fingerprint:
            payload["provenance_sha256"] = provenance_sha256(payload)
        return payload

    def fingerprint(self) -> str:
        return provenance_sha256(self.to_dict(include_fingerprint=False))

    def to_json(self, *, indent: int = 2) -> str:
        return _canonical_json(self.to_dict(), indent=indent) + "\n"


def derive_fixed_thickness(
    material: MaterialAttenuationResult,
    transmissions: Iterable[object],
    *,
    anchor_scope: str = "provided_transmissions",
    drift_warning_relative_span: float = DEFAULT_TRANSMISSION_DRIFT_WARNING_RELATIVE_SPAN,
) -> FixedThicknessDerivation:
    """Derive ``d_fixed = -ln(T_rep) / mu`` from the robust median transmission."""
    if not isinstance(material, MaterialAttenuationResult):
        raise ValueError("material must be a MaterialAttenuationResult")
    statistics = robust_transmission_statistics(
        transmissions,
        anchor_scope=anchor_scope,
        drift_warning_relative_span=drift_warning_relative_span,
    )
    thickness = -math.log(statistics.median) / material.linear_attenuation_cm_inv
    if thickness == 0:
        thickness = 0.0
    if not math.isfinite(thickness) or thickness < 0:
        raise ValueError("derived fixed thickness must be finite and >= 0")
    warnings = [_IDEAL_DENSITY_WARNING, *statistics.warnings]
    if material.porosity_warning is not None:
        warnings.append(material.porosity_warning)
    return FixedThicknessDerivation(
        material=material,
        transmission_statistics=statistics,
        fixed_thickness_cm=thickness,
        warnings=tuple(dict.fromkeys(warnings)),
    )


__all__ = [
    "AttenuationTable",
    "DEFAULT_TRANSMISSION_DRIFT_WARNING_RELATIVE_SPAN",
    "ElementAttenuationDatum",
    "FIXED_THICKNESS_DERIVATION_SCHEMA",
    "FixedThicknessDerivation",
    "MATERIAL_ATTENUATION_SCHEMA",
    "MaterialAttenuationResult",
    "NIST_30_KEV_TABLE",
    "NOMINAL_MATERIALS",
    "NominalMaterialSpec",
    "PARTIAL_UNCERTAINTY_STATUS",
    "TransmissionStatistics",
    "WT_FRACTION_BASIS",
    "calculate_material_attenuation",
    "calculate_nominal_material_attenuation",
    "derive_fixed_thickness",
    "identify_nominal_material",
    "provenance_sha256",
    "parse_weight_composition_string",
    "robust_transmission_statistics",
    "verify_provenance_fingerprint",
]
