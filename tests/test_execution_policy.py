from saxsabs.core.execution_policy import RunPolicy, parse_run_policy, should_skip_all_existing


def test_run_policy_mode_resolution():
    assert RunPolicy(resume_enabled=True, overwrite_existing=False).mode == "resume-skip"
    assert RunPolicy(resume_enabled=True, overwrite_existing=True).mode == "overwrite"
    assert RunPolicy(resume_enabled=False, overwrite_existing=False).mode == "always-run"


def test_should_skip_existing_behavior():
    policy = RunPolicy(resume_enabled=True, overwrite_existing=False)
    assert policy.should_skip_existing(True) is True
    assert policy.should_skip_existing(False) is False

    policy_overwrite = RunPolicy(resume_enabled=True, overwrite_existing=True)
    assert policy_overwrite.should_skip_existing(True) is False


def test_should_skip_all_existing():
    policy = RunPolicy(resume_enabled=True, overwrite_existing=False)
    assert should_skip_all_existing([True, True, True], policy) is True
    assert should_skip_all_existing([True, False], policy) is False
    assert should_skip_all_existing([], policy) is False



def test_parse_run_policy_casts_flags():
    policy = parse_run_policy(resume_enabled=1, overwrite_existing=0)
    assert policy.resume_enabled is True
    assert policy.overwrite_existing is False
    assert policy.mode == "resume-skip"
