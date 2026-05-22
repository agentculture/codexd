"""CLI dispatch for codexd daemon commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

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


def test_daemon_start_reports_missing_config(capsys) -> None:
    with patch("codexd.cli.load_config", side_effect=OSError("missing")):
        rc = main(["daemon", "start", "spark-codex", "--config", "missing.yaml"])

    assert rc == 2
    assert "failed to load config" in capsys.readouterr().err


def test_daemon_start_reports_unknown_agent(capsys) -> None:
    config = Mock()
    config.get_agent.return_value = None

    with patch("codexd.cli.load_config", Mock(return_value=config)):
        rc = main(["daemon", "start", "spark-codex", "--config", "agents.yaml"])

    assert rc == 1
    assert "was not found" in capsys.readouterr().err


def test_daemon_start_reports_empty_all_config(capsys) -> None:
    config = Mock()
    config.agents = []

    with patch("codexd.cli.load_config", Mock(return_value=config)):
        rc = main(["daemon", "start", "--all", "--config", "agents.yaml"])

    assert rc == 1
    assert "no Codex agents" in capsys.readouterr().err


def test_daemon_start_runs_selected_agent() -> None:
    agent = Mock()
    config = Mock()
    config.get_agent.return_value = agent

    with patch("codexd.cli.load_config", Mock(return_value=config)):
        with patch("codexd.cli._run_daemons", new_callable=AsyncMock) as run:
            rc = main(["daemon", "start", "spark-codex", "--config", "agents.yaml"])

    assert rc == 0
    run.assert_awaited_once_with(config, [agent])


def test_repo_commands_dispatch_to_workflow() -> None:
    with patch("codexd.repo.workflow.run_repo_task", Mock(return_value=0)) as run:
        assert (
            main(
                [
                    "repo",
                    "run",
                    "git@github.com:agentculture/example.git",
                    "--branch",
                    "codex/x",
                    "--task",
                    "do it",
                ]
            )
            == 0
        )
    run.assert_called_once()

    with patch("codexd.repo.workflow.push_workspace", Mock(return_value=0)) as push:
        assert main(["repo", "push", "--workspace", ".codexd/work", "--branch", "codex/x"]) == 0
    push.assert_called_once_with(workspace=".codexd/work", branch="codex/x")

    with patch("codexd.repo.workflow.clean_workspace", Mock(return_value=0)) as clean:
        assert main(["repo", "clean", "--workspace", ".codexd/work"]) == 0
    clean.assert_called_once_with(workspace=".codexd/work")


def test_run_daemons_starts_and_stops_in_order() -> None:
    import asyncio
    import signal

    from codexd import cli

    calls: list[str] = []

    class FakeDaemon:
        def __init__(self, config, agent) -> None:
            self.agent = agent

        async def start(self) -> None:
            calls.append(f"start:{self.agent}")

        async def stop(self) -> None:
            calls.append(f"stop:{self.agent}")

    class FakeLoop:
        def add_signal_handler(self, sig, callback) -> None:
            if sig == signal.SIGINT:
                callback()

    with patch("codexd.cli.CodexDaemon", FakeDaemon):
        with patch("codexd.cli.asyncio.get_event_loop", Mock(return_value=FakeLoop())):
            asyncio.run(cli._run_daemons(Mock(), ["one", "two"]))

    assert calls == ["start:one", "start:two", "stop:two", "stop:one"]
