"""Codex-specific config defaults."""

from __future__ import annotations

from codexd.agent.config import AgentConfig, DaemonConfig, SupervisorConfig, TelemetryConfig


def test_codex_config_defaults_are_codex_only() -> None:
    agent = AgentConfig()
    supervisor = SupervisorConfig()
    telemetry = TelemetryConfig()

    assert agent.agent == "codex"
    assert agent.model == "gpt-5.4"
    assert supervisor.model == "gpt-5.4"
    assert telemetry.service_name == "culture.harness.codex"
    assert isinstance(DaemonConfig().agents, list)
