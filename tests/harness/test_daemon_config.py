from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Type

import pytest
import yaml

from codexd.harness.attention import Band
from codexd.harness.config import (
    BaseAgentConfig,
    BaseDaemonConfig,
    BaseServerConnConfig,
    BaseSupervisorConfig,
    BaseTelemetryConfig,
    add_agent_to_config,
    archive_agent,
    archive_server,
    load_config,
    load_config_or_default,
    remove_agent,
    rename_agent,
    rename_server,
    resolve_attention_config,
    sanitize_agent_name,
    save_config,
    unarchive_agent,
    unarchive_server,
)


@dataclass
class HarnessServerConnConfig(BaseServerConnConfig):
    pass


@dataclass
class HarnessSupervisorConfig(BaseSupervisorConfig):
    model: str = "codex-test-supervisor"


@dataclass
class HarnessAgentConfig(BaseAgentConfig):
    model: str = "codex-test-agent"


@dataclass
class HarnessTelemetryConfig(BaseTelemetryConfig):
    service_name: str = "codexd-test"


@dataclass
class HarnessDaemonConfig(BaseDaemonConfig):
    server: HarnessServerConnConfig = field(default_factory=HarnessServerConnConfig)
    supervisor: HarnessSupervisorConfig = field(default_factory=HarnessSupervisorConfig)
    telemetry: HarnessTelemetryConfig = field(default_factory=HarnessTelemetryConfig)
    agents: list[HarnessAgentConfig] = field(default_factory=list)

    _SERVER_CLS: ClassVar[Type[BaseServerConnConfig]] = HarnessServerConnConfig
    _SUPERVISOR_CLS: ClassVar[Type[BaseSupervisorConfig]] = HarnessSupervisorConfig
    _AGENT_CLS: ClassVar[Type[BaseAgentConfig]] = HarnessAgentConfig
    _TELEMETRY_CLS: ClassVar[Type[BaseTelemetryConfig]] = HarnessTelemetryConfig


def write_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_load_config_from_yaml_strips_unknown_backend_fields(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    write_yaml(
        path,
        """\
server:
  name: codex
  host: 127.0.0.1
  port: 6668
  archived: true
supervisor:
  model: gpt-5
  thinking: high
telemetry:
  enabled: true
  service_name: codexd
  backend_only: ignored
webhooks:
  url: https://example.test/hook
  irc_channel: "#alerts"
  events:
    - agent_error
buffer_size: 300
poll_interval: 45
agents:
  - nick: codex-main
    directory: /tmp/codex-main
    channels: ["#general", "#dev"]
    model: gpt-5-codex
    acp_command: ignored
    attention:
      enabled: false
""",
    )

    config = load_config(path, HarnessDaemonConfig)

    assert config.server == HarnessServerConnConfig(name="codex", host="127.0.0.1", port=6668)
    assert config.supervisor.model == "gpt-5"
    assert config.telemetry.enabled is True
    assert config.telemetry.service_name == "codexd"
    assert config.webhooks.url == "https://example.test/hook"
    assert config.webhooks.events == ["agent_error"]
    assert config.buffer_size == 300
    assert config.poll_interval == 45
    assert config.agents[0].nick == "codex-main"
    assert config.agents[0].channels == ["#general", "#dev"]
    assert config.agents[0].attention_overrides == {"enabled": False}


def test_load_config_defaults_and_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    write_yaml(path, "agents:\n  - nick: codex-main\n    directory: /tmp/codex-main\n")

    config = load_config(path, HarnessDaemonConfig)

    assert config.server.name == "culture"
    assert config.supervisor.model == "codex-test-supervisor"
    assert config.telemetry.service_name == "codexd-test"
    assert config.buffer_size == 500
    assert config.agents[0].model == "codex-test-agent"
    assert (
        load_config_or_default(tmp_path / "missing.yaml", HarnessDaemonConfig)
        == HarnessDaemonConfig()
    )


def test_get_agent_by_nick(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    write_yaml(
        path,
        """\
agents:
  - nick: codex-main
    directory: /tmp/a
  - nick: codex-review
    directory: /tmp/b
""",
    )

    config = load_config(path, HarnessDaemonConfig)

    assert config.get_agent("codex-review").directory == "/tmp/b"
    assert config.get_agent("missing") is None


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    original = HarnessDaemonConfig(
        server=HarnessServerConnConfig(name="codex", host="10.0.0.1", port=6669),
        supervisor=HarnessSupervisorConfig(model="gpt-5"),
        buffer_size=200,
        agents=[
            HarnessAgentConfig(
                nick="codex-main",
                directory="/tmp/codex-main",
                channels=["#general", "#dev"],
                model="gpt-5-codex",
            )
        ],
    )

    save_config(path, original)
    loaded = load_config(path, HarnessDaemonConfig)

    assert loaded.server == original.server
    assert loaded.supervisor.model == "gpt-5"
    assert loaded.buffer_size == 200
    assert loaded.agents[0].channels == ["#general", "#dev"]


def test_add_agent_to_config_creates_appends_and_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"

    config = add_agent_to_config(
        path,
        HarnessAgentConfig(nick="codex-main", directory="/tmp/codex-main"),
        HarnessDaemonConfig,
        server_name="codex",
    )
    assert config.server.name == "codex"
    assert [agent.nick for agent in config.agents] == ["codex-main"]

    config = add_agent_to_config(path, HarnessAgentConfig(nick="codex-review"), HarnessDaemonConfig)
    assert [agent.nick for agent in config.agents] == ["codex-main", "codex-review"]

    with pytest.raises(ValueError, match="already exists"):
        add_agent_to_config(path, HarnessAgentConfig(nick="codex-main"), HarnessDaemonConfig)


def test_rename_server_updates_prefixed_agent_nicks_and_rejects_collisions(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    save_config(
        path,
        HarnessDaemonConfig(
            server=HarnessServerConnConfig(name="old"),
            agents=[HarnessAgentConfig(nick="old-main"), HarnessAgentConfig(nick="other-main")],
        ),
    )

    old_name, renamed = rename_server(path, "new")
    config = load_config(path, HarnessDaemonConfig)

    assert old_name == "old"
    assert renamed == [("old-main", "new-main")]
    assert config.server.name == "new"
    assert [agent.nick for agent in config.agents] == ["new-main", "other-main"]

    save_config(
        path,
        HarnessDaemonConfig(
            server=HarnessServerConnConfig(name="old"),
            agents=[HarnessAgentConfig(nick="old-main"), HarnessAgentConfig(nick="new-main")],
        ),
    )
    with pytest.raises(ValueError, match="duplicate"):
        rename_server(path, "new")


def test_rename_and_remove_agent_validate_nicks(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    save_config(
        path,
        HarnessDaemonConfig(
            agents=[HarnessAgentConfig(nick="codex-main"), HarnessAgentConfig(nick="codex-review")]
        ),
    )

    rename_agent(path, "codex-main", "codex-worker")
    assert [agent.nick for agent in load_config(path, HarnessDaemonConfig).agents] == [
        "codex-worker",
        "codex-review",
    ]

    with pytest.raises(ValueError, match="already exists"):
        rename_agent(path, "codex-worker", "codex-review")
    with pytest.raises(ValueError, match="not found"):
        rename_agent(path, "codex-missing", "codex-new")

    remove_agent(path, "codex-worker")
    assert [agent.nick for agent in load_config(path, HarnessDaemonConfig).agents] == [
        "codex-review"
    ]

    with pytest.raises(ValueError, match="not found"):
        remove_agent(path, "codex-missing")


def test_archive_and_unarchive_agent_preserve_raw_fields(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    save_config(path, HarnessDaemonConfig(agents=[HarnessAgentConfig(nick="codex-main")]))

    archive_agent(path, "codex-main", reason="quiet")
    archived = read_yaml(path)["agents"][0]
    assert archived["archived"] is True
    assert archived["archived_reason"] == "quiet"
    assert archived["archived_at"]

    unarchive_agent(path, "codex-main")
    unarchived = read_yaml(path)["agents"][0]
    assert unarchived["archived"] is False
    assert unarchived["archived_reason"] == ""
    assert unarchived["archived_at"] == ""

    with pytest.raises(ValueError, match="not found"):
        archive_agent(path, "codex-missing")
    with pytest.raises(ValueError, match="not archived"):
        unarchive_agent(path, "codex-main")


def test_archive_and_unarchive_server_update_all_agents(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    save_config(
        path,
        HarnessDaemonConfig(
            server=HarnessServerConnConfig(name="codex"),
            agents=[HarnessAgentConfig(nick="codex-main"), HarnessAgentConfig(nick="codex-review")],
        ),
    )

    assert archive_server(path, reason="maintenance") == ["codex-main", "codex-review"]
    archived = read_yaml(path)
    assert archived["server"]["archived"] is True
    assert all(agent["archived"] for agent in archived["agents"])

    assert unarchive_server(path) == ["codex-main", "codex-review"]
    unarchived = read_yaml(path)
    assert unarchived["server"]["archived"] is False
    assert all(agent["archived"] is False for agent in unarchived["agents"])


def test_resolve_attention_config_merges_agent_overrides(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    write_yaml(
        path,
        """\
attention:
  tick_s: 10
  bands:
    idle:
      interval_s: 600
agents:
  - nick: codex-main
    attention:
      enabled: false
      bands:
        hot:
          interval_s: 15
          hold_s: 60
""",
    )

    config = load_config(path, HarnessDaemonConfig)
    resolved = resolve_attention_config(config, config.agents[0])

    assert resolved.enabled is False
    assert resolved.tick_s == 10
    assert resolved.bands[Band.HOT].interval_s == 15
    assert resolved.bands[Band.HOT].hold_s == 60
    assert resolved.bands[Band.IDLE].interval_s == 600


def test_sanitize_agent_name() -> None:
    assert sanitize_agent_name("My Project") == "my-project"
    assert sanitize_agent_name("culture") == "culture"
    assert sanitize_agent_name(".hidden") == "hidden"
    assert sanitize_agent_name("UPPER_case") == "upper-case"

    with pytest.raises(ValueError):
        sanitize_agent_name("")
    with pytest.raises(ValueError):
        sanitize_agent_name("...")
