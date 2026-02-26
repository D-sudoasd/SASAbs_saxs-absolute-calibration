"""saxsabs: SAXS absolute intensity calibration utilities."""

from .core.normalization import compute_norm_factor, monitor_norm_formula
from .core.calibration import KFactorEstimationResult, estimate_k_factor_robust
from .core.mu_calculator import MuResult, calculate_mu, mu_rho_single, parse_composition_string
from .core.buffer_subtraction import BufferSubtractionResult, subtract_buffer
from .io.parsers import parse_header_values, read_external_1d_profile
from .io.writers import write_cansas1d_xml, write_nxcansas_h5
from .constants import (
    NIST_SRM3600_DATA,
    STANDARD_REGISTRY,
    StandardReference,
    get_reference_data,
    water_dsdw,
)

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # normalization
    "compute_norm_factor",
    "monitor_norm_formula",
    # calibration
    "KFactorEstimationResult",
    "estimate_k_factor_robust",
    # standards
    "NIST_SRM3600_DATA",
    "STANDARD_REGISTRY",
    "StandardReference",
    "get_reference_data",
    "water_dsdw",
    # mu calculator
    "MuResult",
    "calculate_mu",
    "mu_rho_single",
    "parse_composition_string",
    # buffer subtraction
    "BufferSubtractionResult",
    "subtract_buffer",
    # I/O
    "parse_header_values",
    "read_external_1d_profile",
    "write_cansas1d_xml",
    "write_nxcansas_h5",
]
