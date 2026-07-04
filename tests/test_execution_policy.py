import pytest

from saxsabs.core.execution_policy import (
    RunPolicy,
    parse_run_policy,
    resolve_output_path_for_write,
    should_skip_all_existing,
)


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


def test_resolve_output_path_for_write_adds_rerun_suffix_for_always_run(tmp_path):
    target = tmp_path / "sample.dat"
    target.write_text("old", encoding="utf-8")

    resolved = resolve_output_path_for_write(
        target,
        RunPolicy(resume_enabled=False, overwrite_existing=False),
    )

    assert resolved == tmp_path / "sample_rerun1.dat"
    assert target.read_text(encoding="utf-8") == "old"


def test_resolve_output_path_for_write_increments_rerun_suffix(tmp_path):
    (tmp_path / "sample.dat").write_text("old", encoding="utf-8")
    (tmp_path / "sample_rerun1.dat").write_text("rerun1", encoding="utf-8")

    resolved = resolve_output_path_for_write(
        tmp_path / "sample.dat",
        RunPolicy(resume_enabled=False, overwrite_existing=False),
    )

    assert resolved == tmp_path / "sample_rerun2.dat"


def test_resolve_output_path_for_write_resume_policy_blocks_direct_write(tmp_path):
    target = tmp_path / "sample.dat"
    target.write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError, match="resume-skip"):
        resolve_output_path_for_write(
            target,
            RunPolicy(resume_enabled=True, overwrite_existing=False),
        )


def test_resolve_output_path_for_write_overwrite_policy_keeps_existing_path(tmp_path):
    target = tmp_path / "sample.dat"
    target.write_text("old", encoding="utf-8")

    resolved = resolve_output_path_for_write(
        target,
        RunPolicy(resume_enabled=False, overwrite_existing=True),
    )

    assert resolved == target
