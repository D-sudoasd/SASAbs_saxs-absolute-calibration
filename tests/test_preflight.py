from saxsabs.core.preflight import evaluate_preflight_gate


def test_preflight_ready_when_clean():
    out = evaluate_preflight_gate(total_files=10, failed_files=0, warning_count=0, risky_files=0)
    assert out.level == "READY"
    assert out.score == 0
    assert out.is_blocked is False


def test_preflight_blocked_when_failed_exists():
    out = evaluate_preflight_gate(total_files=10, failed_files=1, warning_count=0, risky_files=0)
    assert out.level == "BLOCKED"
    assert out.is_blocked is True


def test_preflight_caution_when_warnings_or_risky_exist():
    out_warn = evaluate_preflight_gate(total_files=10, failed_files=0, warning_count=2, risky_files=0)
    assert out_warn.level == "CAUTION"

    out_risky = evaluate_preflight_gate(total_files=10, failed_files=0, warning_count=0, risky_files=2)
    assert out_risky.level == "CAUTION"
