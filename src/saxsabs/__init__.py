"""saxsabs: SAXS absolute intensity calibration utilities."""

from .core.normalization import compute_norm_factor, monitor_norm_formula
from .core.calibration import KFactorEstimationResult, estimate_k_factor_robust
from .core.mu_calculator import MuResult, calculate_mu, mu_rho_single, parse_composition_string
from .core.buffer_subtraction import BufferSubtractionResult, subtract_buffer
from .core.preflight import evaluate_preflight_gate, PreflightGateSummary
from .core.execution_policy import (
    RunPolicy,
    parse_run_policy,
    should_skip_all_existing,
)
from .core.reference_matching import (
    build_reference_library,
    reference_score,
    select_best_reference,
    ReferenceEntry,
)
from .core.session_grouper import (
    AcquisitionGroup,
    cluster_by_acquisition_time,
)
from .io.parsers import (
    parse_header_values,
    parse_header_values_with_meta,
    read_external_1d_profile,
    extract_acquisition_timestamp,
)
from .io.writers import write_cansas1d_xml, write_nxcansas_h5
from .constants import (
    NIST_SRM3600_DATA,
    STANDARD_REGISTRY,
    StandardReference,
    get_reference_data,
    water_dsdw,
)

__version__ = "1.1.1"

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
    "parse_header_values_with_meta",
    "read_external_1d_profile",
    "extract_acquisition_timestamp",
    "write_cansas1d_xml",
    "write_nxcansas_h5",
    # preflight & execution policy (batch support)
    "evaluate_preflight_gate",
    "PreflightGateSummary",
    "RunPolicy",
    "parse_run_policy",
    "should_skip_all_existing",
    # reference matching (BG/Dark auto-match)
    "build_reference_library",
    "reference_score",
    "select_best_reference",
    "ReferenceEntry",
    # 机时 / session grouping
    "AcquisitionGroup",
    "cluster_by_acquisition_time",
]
