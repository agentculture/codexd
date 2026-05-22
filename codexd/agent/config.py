"""codex backend config — thin shim over ``codexd.harness.config``.

Backend-specific defaults: ``agent="codex"``, ``model="gpt-5.4"``,
``supervisor.model="gpt-5.4"``, ``telemetry.service_name="culture.harness.codex"``.

The shape and re-exports below match the stable surface declared in
``docs/api-stability.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Type

from codexd.harness import config as _shared
from codexd.harness.config import (  # noqa: F401  (re-export — public surface)
    remove_agent,
    rename_agent,
    rename_server,
    resolve_attention_config,
    sanitize_agent_name,
    save_config,
)
from codexd.harness.webhook_types import WebhookConfig  # noqa: F401


@dataclass
class ServerConnConfig(_shared.BaseServerConnConfig):
    pass


@dataclass
class SupervisorConfig(_shared.BaseSupervisorConfig):
    model: str = "gpt-5.4"


@dataclass
class AgentConfig(_shared.BaseAgentConfig):
    agent: str = "codex"
    model: str = "gpt-5.4"


@dataclass
class TelemetryConfig(_shared.BaseTelemetryConfig):
    service_name: str = "culture.harness.codex"


@dataclass
class DaemonConfig(_shared.BaseDaemonConfig):
    server: ServerConnConfig = field(default_factory=ServerConnConfig)
    supervisor: SupervisorConfig = field(default_factory=SupervisorConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    agents: list[AgentConfig] = field(default_factory=list)

    _SERVER_CLS: ClassVar[Type[ServerConnConfig]] = ServerConnConfig
    _SUPERVISOR_CLS: ClassVar[Type[SupervisorConfig]] = SupervisorConfig
    _AGENT_CLS: ClassVar[Type[AgentConfig]] = AgentConfig
    _TELEMETRY_CLS: ClassVar[Type[TelemetryConfig]] = TelemetryConfig


def load_config(path: str | Path) -> DaemonConfig:
    """Load daemon config from a YAML file."""
    return _shared.load_config(path, DaemonConfig)  # type: ignore[return-value]


def load_config_or_default(path: str | Path) -> DaemonConfig:
    """Load config from path, returning a default DaemonConfig if file is missing."""
    return _shared.load_config_or_default(path, DaemonConfig)  # type: ignore[return-value]


def add_agent_to_config(
    path: str | Path,
    agent: AgentConfig,
    server_name: str | None = None,
) -> DaemonConfig:
    """Add an agent to a config file, creating it if needed."""
    return _shared.add_agent_to_config(  # type: ignore[return-value]
        path, agent, DaemonConfig, server_name=server_name
    )
