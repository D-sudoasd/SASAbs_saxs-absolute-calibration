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
