from saxsabs.core import (
    AcquisitionGroup,
    ReferenceEntry,
    build_reference_library,
    cluster_by_acquisition_time,
    reference_score,
    select_best_reference,
)


def test_core_reexports_recent_batch_helpers():
    assert AcquisitionGroup.__name__ == "AcquisitionGroup"
    assert ReferenceEntry.__name__ == "ReferenceEntry"
    assert callable(cluster_by_acquisition_time)
    assert callable(build_reference_library)
    assert callable(reference_score)
    assert callable(select_best_reference)


def test_io_reexports_header_meta_helpers():
    import saxsabs.io as io
    from saxsabs.io.parsers import extract_acquisition_timestamp, parse_header_values_with_meta

    assert io.parse_header_values_with_meta is parse_header_values_with_meta
    assert io.extract_acquisition_timestamp is extract_acquisition_timestamp
