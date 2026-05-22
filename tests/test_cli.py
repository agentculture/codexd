"""Smoke tests for the codexd CLI."""

from __future__ import annotations

import pytest

from codexd import __version__
from codexd.cli import main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    out = capsys.readouterr().out
    assert "codexd" in out
    assert "daemon" in out
    assert "repo" in out
