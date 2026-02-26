import pytest

from saxsabs import __version__
from saxsabs.workbench_launcher import main


def test_workbench_launcher_version(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert __version__ in out
