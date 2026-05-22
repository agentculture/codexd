"""CLI dispatch for codexd daemon commands."""

from __future__ import annotations

from unittest.mock import Mock, patch

from codexd.cli import main


def test_daemon_start_requires_nick_or_all(capsys) -> None:
    rc = main(["daemon", "start"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "hint:" in captured.err
    assert "nick" in captured.err


def test_daemon_start_dispatches_runner() -> None:
    with patch("codexd.cli.run_daemon_main", Mock(return_value=0)) as run:
        rc = main(["daemon", "start", "spark-codex", "--config", "agents.yaml"])

    assert rc == 0
    run.assert_called_once_with(nick="spark-codex", all_agents=False, config_path="agents.yaml")
