"""Public daemon surface for codexd's Codex-only runtime."""

from __future__ import annotations

import inspect

import pytest

from codexd.agent.config import AgentConfig, DaemonConfig
from codexd.agent.daemon import CodexDaemon


def test_daemon_constructor_documented_kwargs(tmp_path) -> None:
    cfg = DaemonConfig()
    agent = AgentConfig(nick="surface-test", directory=str(tmp_path), channels=["#general"])

    daemon = CodexDaemon(cfg, agent, socket_dir=str(tmp_path), skip_codex=True)

    assert daemon.config is cfg
    assert daemon.agent is agent
    assert daemon.skip_codex is True


def test_daemon_backend_name_class_attribute() -> None:
    assert CodexDaemon.BACKEND_NAME == "codex"


def test_daemon_start_stop_are_coroutines() -> None:
    assert inspect.iscoroutinefunction(CodexDaemon.start)
    assert inspect.iscoroutinefunction(CodexDaemon.stop)


def test_daemon_constructor_rejects_unknown_kwargs(tmp_path) -> None:
    cfg = DaemonConfig()
    agent = AgentConfig(nick="surface-test", directory=str(tmp_path), channels=["#general"])

    with pytest.raises(TypeError):
        CodexDaemon(cfg, agent, totally_made_up_kwarg=True)
