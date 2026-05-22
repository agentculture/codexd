# codexd Culture Agent Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained Codex-only Culture agent package with `codexd daemon start` and app-server based repo-work commands that clone, run Codex, commit, and push.

**Architecture:** Copy and adapt the Codex backend plus required shared harness modules from `../cultureagent` into `codexd`, rewriting imports so `codexd` has no runtime dependency on `cultureagent`. Add `codexd.repo` as a separate workflow layer that reuses the app-server runner interface but keeps Git workspace lifecycle isolated and testable.

**Tech Stack:** Python 3.12, argparse, asyncio, PyYAML, OpenTelemetry, agentirc-cli, Git CLI, Codex app-server JSON-RPC, pytest, pytest-asyncio, pytest-xdist, pytest-cov.

---

## File Structure

Create these package areas:

- `codexd/harness/`: internal Culture harness modules copied from `cultureagent/clients/shared` plus needed utility modules.
- `codexd/agent/`: Codex-specific config, runner, supervisor, daemon, constants, and skill client.
- `codexd/repo/`: Git workspace validation and repo-run orchestration.
- `tests/agent/`: Codex daemon, runner, config, and supervisor tests.
- `tests/harness/`: migrated shared harness tests that protect the copied internals.
- `tests/repo/`: local bare-repo workflow tests.

Keep `codexd/cli.py` as the top-level CLI registration point. Do not create a generic multi-backend framework.

## Task 1: Package Dependencies And Ignore Rules

**Files:**

- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Test: `tests/test_package_metadata.py`

- [ ] **Step 1: Write failing dependency metadata tests**

Create `tests/test_package_metadata.py`:

```python
"""Package metadata requirements for the migrated codexd runtime."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _project() -> dict:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_runtime_dependencies_include_harness_requirements() -> None:
    deps = set(_project()["dependencies"])

    assert "pyyaml>=6.0" in deps
    assert "agentirc-cli>=9.6,<10" in deps
    assert "opentelemetry-api>=1.25" in deps
    assert "opentelemetry-sdk>=1.25" in deps
    assert "opentelemetry-exporter-otlp-proto-grpc>=1.25" in deps
    assert "opentelemetry-semantic-conventions>=0.46b0" in deps
    assert "opentelemetry-instrumentation-aiohttp-server>=0.46b0" in deps


def test_pytest_asyncio_is_available_for_harness_tests() -> None:
    dev_deps = set(
        tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"]["dev"]
    )

    assert "pytest-asyncio>=0.25" in dev_deps


def test_codexd_workspace_is_gitignored() -> None:
    ignored = Path(".gitignore").read_text(encoding="utf-8")

    assert ".codexd/" in ignored
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/test_package_metadata.py -v
```

Expected: at least `test_runtime_dependencies_include_harness_requirements` and `test_codexd_workspace_is_gitignored` fail because dependencies and ignore rules are not present.

- [ ] **Step 3: Update `pyproject.toml` dependencies**

Replace the empty dependency list with:

```toml
dependencies = [
    "pyyaml>=6.0",
    "agentirc-cli>=9.6,<10",
    "opentelemetry-api>=1.25",
    "opentelemetry-sdk>=1.25",
    "opentelemetry-exporter-otlp-proto-grpc>=1.25",
    "opentelemetry-semantic-conventions>=0.46b0",
    "opentelemetry-instrumentation-aiohttp-server>=0.46b0",
]
```

Add `pytest-asyncio` to the `dev` dependency group:

```toml
    "pytest-asyncio>=0.25",
```

Keep `known_first_party = ["codexd"]` unchanged.

- [ ] **Step 4: Add workspace ignore rule**

Append this block to `.gitignore`:

```gitignore
# codexd managed remote-repository workspaces
.codexd/
```

- [ ] **Step 5: Sync dependencies and run tests**

Run:

```bash
uv sync
uv run pytest tests/test_package_metadata.py -v
```

Expected: package metadata tests pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore tests/test_package_metadata.py
git commit -m "build: add codexd harness dependencies"
```

## Task 2: Copy Harness Utility Modules

**Files:**

- Create: `codexd/_constants.py`
- Create: `codexd/aio.py`
- Create: `codexd/pidfile.py`
- Create: `codexd/constants.py`
- Create: `codexd/protocol/__init__.py`
- Create: `codexd/protocol/message.py`
- Create: `codexd/telemetry/__init__.py`
- Create: `codexd/telemetry/audit.py`
- Create: `codexd/telemetry/context.py`
- Create: `codexd/telemetry/metrics.py`
- Create: `codexd/telemetry/tracing.py`
- Test: `tests/test_protocol_message.py`
- Test: `tests/test_pidfile.py`

- [ ] **Step 1: Copy utility tests from `cultureagent`**

Run:

```bash
cp ../cultureagent/tests/test_protocol_message.py tests/test_protocol_message.py
cp ../cultureagent/tests/test_pidfile.py tests/test_pidfile.py
```

- [ ] **Step 2: Rewrite test imports**

Replace `cultureagent` imports in the copied tests with `codexd`:

```bash
perl -0pi -e 's/cultureagent/codexd/g' tests/test_protocol_message.py tests/test_pidfile.py
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run pytest tests/test_protocol_message.py tests/test_pidfile.py -v
```

Expected: import failures for missing `codexd.protocol` and `codexd.pidfile` modules.

- [ ] **Step 4: Copy utility modules**

Run:

```bash
cp ../cultureagent/cultureagent/_constants.py codexd/_constants.py
cp ../cultureagent/cultureagent/aio.py codexd/aio.py
cp ../cultureagent/cultureagent/pidfile.py codexd/pidfile.py
cp ../cultureagent/cultureagent/constants.py codexd/constants.py
mkdir -p codexd/protocol codexd/telemetry
cp ../cultureagent/cultureagent/protocol/__init__.py codexd/protocol/__init__.py
cp ../cultureagent/cultureagent/protocol/message.py codexd/protocol/message.py
cp ../cultureagent/cultureagent/telemetry/__init__.py codexd/telemetry/__init__.py
cp ../cultureagent/cultureagent/telemetry/audit.py codexd/telemetry/audit.py
cp ../cultureagent/cultureagent/telemetry/context.py codexd/telemetry/context.py
cp ../cultureagent/cultureagent/telemetry/metrics.py codexd/telemetry/metrics.py
cp ../cultureagent/cultureagent/telemetry/tracing.py codexd/telemetry/tracing.py
perl -0pi -e 's/cultureagent/codexd/g' codexd/_constants.py codexd/aio.py codexd/pidfile.py codexd/constants.py codexd/protocol/*.py codexd/telemetry/*.py
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_protocol_message.py tests/test_pidfile.py -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add codexd tests/test_protocol_message.py tests/test_pidfile.py
git commit -m "feat: add codexd harness utility modules"
```

## Task 3: Copy Shared Harness Core

**Files:**

- Create: `codexd/harness/__init__.py`
- Create: `codexd/harness/attention.py`
- Create: `codexd/harness/config.py`
- Create: `codexd/harness/ipc.py`
- Create: `codexd/harness/irc_transport.py`
- Create: `codexd/harness/message_buffer.py`
- Create: `codexd/harness/queued_base_daemon.py`
- Create: `codexd/harness/base_daemon.py`
- Create: `codexd/harness/rooms.py`
- Create: `codexd/harness/socket_server.py`
- Create: `codexd/harness/telemetry.py`
- Create: `codexd/harness/webhook.py`
- Create: `codexd/harness/webhook_types.py`
- Create: `codexd/harness/skill_irc_client.py`
- Test: `tests/harness/test_message_buffer.py`
- Test: `tests/harness/test_daemon_config.py`
- Test: `tests/harness/test_attention.py`
- Test: `tests/harness/test_rooms.py`

- [ ] **Step 1: Create harness package and copy representative tests**

Run:

```bash
mkdir -p codexd/harness tests/harness
cp ../cultureagent/cultureagent/clients/shared/__init__.py codexd/harness/__init__.py
cp ../cultureagent/tests/test_message_buffer.py tests/harness/test_message_buffer.py
cp ../cultureagent/tests/test_daemon_config.py tests/harness/test_daemon_config.py
cp ../cultureagent/tests/harness/test_attention.py tests/harness/test_attention.py
cp ../cultureagent/tests/test_rooms.py tests/harness/test_rooms.py
perl -0pi -e 's/cultureagent\.clients\.shared/codexd.harness/g; s/cultureagent/codexd/g' tests/harness/*.py
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/harness/test_message_buffer.py tests/harness/test_daemon_config.py tests/harness/test_attention.py tests/harness/test_rooms.py -v
```

Expected: import failures for missing harness modules.

- [ ] **Step 3: Copy shared harness modules**

Run:

```bash
cp ../cultureagent/cultureagent/clients/shared/attention.py codexd/harness/attention.py
cp ../cultureagent/cultureagent/clients/shared/base_daemon.py codexd/harness/base_daemon.py
cp ../cultureagent/cultureagent/clients/shared/config.py codexd/harness/config.py
cp ../cultureagent/cultureagent/clients/shared/ipc.py codexd/harness/ipc.py
cp ../cultureagent/cultureagent/clients/shared/irc_transport.py codexd/harness/irc_transport.py
cp ../cultureagent/cultureagent/clients/shared/message_buffer.py codexd/harness/message_buffer.py
cp ../cultureagent/cultureagent/clients/shared/queued_base_daemon.py codexd/harness/queued_base_daemon.py
cp ../cultureagent/cultureagent/clients/shared/rooms.py codexd/harness/rooms.py
cp ../cultureagent/cultureagent/clients/shared/socket_server.py codexd/harness/socket_server.py
cp ../cultureagent/cultureagent/clients/shared/telemetry.py codexd/harness/telemetry.py
cp ../cultureagent/cultureagent/clients/shared/webhook.py codexd/harness/webhook.py
cp ../cultureagent/cultureagent/clients/shared/webhook_types.py codexd/harness/webhook_types.py
cp ../cultureagent/cultureagent/clients/shared/skill_irc_client.py codexd/harness/skill_irc_client.py
perl -0pi -e 's/cultureagent\.clients\.shared/codexd.harness/g; s/cultureagent\.clients\.codex/codexd.agent/g; s/cultureagent/codexd/g' codexd/harness/*.py
```

- [ ] **Step 4: Fix runtime directory naming if copied code references `culture-` sockets**

In `codexd/harness/socket_server.py` and `codexd/harness/skill_irc_client.py`, keep the socket filename compatible with the Culture daemon contract:

```python
sock_path = os.path.join(socket_dir, f"culture-{nick}.sock")
```

Do not rename sockets to `codexd-...`; the in-skill client and Culture mesh expect the `culture-<nick>.sock` shape.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/harness/test_message_buffer.py tests/harness/test_daemon_config.py tests/harness/test_attention.py tests/harness/test_rooms.py -v
```

Expected: tests pass or fail only because copied tests still reference multi-backend names. If multi-backend assertions remain, edit those tests to assert Codex-only behavior through `codexd.agent.config` in Task 4 instead of keeping generic backend parity.

- [ ] **Step 6: Commit**

```bash
git add codexd/harness tests/harness
git commit -m "feat: migrate codexd shared harness internals"
```

## Task 4: Add Codex Agent Config And Daemon Surface

**Files:**

- Create: `codexd/agent/__init__.py`
- Create: `codexd/agent/config.py`
- Create: `codexd/agent/constants.py`
- Create: `codexd/agent/daemon.py`
- Test: `tests/agent/test_config.py`
- Test: `tests/agent/test_daemon_surface.py`

- [ ] **Step 1: Write config and daemon surface tests**

Create `tests/agent/test_config.py`:

```python
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
```

Create `tests/agent/test_daemon_surface.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/agent/test_config.py tests/agent/test_daemon_surface.py -v
```

Expected: import failures for missing `codexd.agent` modules.

- [ ] **Step 3: Copy Codex config/constants/daemon**

Run:

```bash
mkdir -p codexd/agent
printf '%s\n' '"""Codex-specific Culture agent runtime."""' > codexd/agent/__init__.py
cp ../cultureagent/cultureagent/clients/codex/config.py codexd/agent/config.py
cp ../cultureagent/cultureagent/clients/codex/constants.py codexd/agent/constants.py
cp ../cultureagent/cultureagent/clients/codex/daemon.py codexd/agent/daemon.py
perl -0pi -e 's/cultureagent\.clients\.codex/codexd.agent/g; s/cultureagent\.clients\.shared/codexd.harness/g; s/cultureagent/codexd/g' codexd/agent/*.py
```

- [ ] **Step 4: Ensure imports point to copied harness modules**

In `codexd/agent/config.py`, imports should include:

```python
from codexd.harness import config as _shared
from codexd.harness.config import (
    remove_agent,
    rename_agent,
    rename_server,
    resolve_attention_config,
    sanitize_agent_name,
    save_config,
)
from codexd.harness.webhook_types import WebhookConfig
```

In `codexd/agent/daemon.py`, imports should include:

```python
from codexd.agent.agent_runner import CodexAgentRunner
from codexd.agent.config import AgentConfig, DaemonConfig, resolve_attention_config
from codexd.agent.constants import DEFAULT_TURN_TIMEOUT_SECONDS
from codexd.agent.supervisor import CodexSupervisor
from codexd.harness.queued_base_daemon import QueuedBaseDaemon
```

`agent_runner.py` and `supervisor.py` do not exist yet; tests only construct with `skip_codex=True`, so import stubs will be completed in Task 5. If construction tests fail due missing imports, create temporary modules with the class names and replace them in Task 5:

```python
# codexd/agent/agent_runner.py
class CodexAgentRunner:  # pragma: no cover - replaced in Task 5
    pass
```

```python
# codexd/agent/supervisor.py
class CodexSupervisor:  # pragma: no cover - replaced in Task 5
    pass
```

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/agent/test_config.py tests/agent/test_daemon_surface.py -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add codexd/agent tests/agent/test_config.py tests/agent/test_daemon_surface.py
git commit -m "feat: add codexd Codex daemon surface"
```

## Task 5: Migrate Codex App-Server Runner And Supervisor

**Files:**

- Create/Replace: `codexd/agent/agent_runner.py`
- Create/Replace: `codexd/agent/supervisor.py`
- Test: `tests/agent/test_agent_runner.py`
- Test: `tests/agent/test_supervisor.py`

- [ ] **Step 1: Copy runner and supervisor tests**

Run:

```bash
cp ../cultureagent/tests/harness/test_agent_runner_codex.py tests/agent/test_agent_runner.py
cp ../cultureagent/tests/test_supervisor.py tests/agent/test_supervisor.py
perl -0pi -e 's/cultureagent\.clients\.codex/codexd.agent/g; s/cultureagent\.clients\.shared/codexd.harness/g; s/cultureagent/codexd/g' tests/agent/test_agent_runner.py tests/agent/test_supervisor.py
```

If `../cultureagent/tests/test_supervisor.py` is not Codex-specific, create `tests/agent/test_supervisor.py` with:

```python
"""Codex supervisor behavior."""

from __future__ import annotations

import pytest

from codexd.agent.supervisor import CodexSupervisor
from codexd.harness.supervisor import SupervisorVerdict


@pytest.mark.asyncio
async def test_supervisor_dispatches_correction_whisper() -> None:
    whispers: list[tuple[str, str]] = []

    supervisor = CodexSupervisor(eval_interval=1, on_whisper=lambda message, kind: whispers.append((message, kind)))

    await supervisor._process_verdict(SupervisorVerdict(action="CORRECTION", message="focus"))

    assert whispers == [("focus", "CORRECTION")]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/agent/test_agent_runner.py tests/agent/test_supervisor.py -v
```

Expected: failures for missing or stubbed runner/supervisor behavior.

- [ ] **Step 3: Copy runner and supervisor implementation**

Run:

```bash
cp ../cultureagent/cultureagent/clients/codex/agent_runner.py codexd/agent/agent_runner.py
cp ../cultureagent/cultureagent/clients/codex/supervisor.py codexd/agent/supervisor.py
cp ../cultureagent/cultureagent/clients/shared/supervisor.py codexd/harness/supervisor.py
perl -0pi -e 's/cultureagent\.clients\.codex/codexd.agent/g; s/cultureagent\.clients\.shared/codexd.harness/g; s/cultureagent/codexd/g' codexd/agent/agent_runner.py codexd/agent/supervisor.py codexd/harness/supervisor.py
```

- [ ] **Step 4: Preserve Codex auth behavior in `CodexAgentRunner.start`**

Verify `codexd/agent/agent_runner.py` keeps this environment pattern:

```python
self._isolated_home = tempfile.mkdtemp(prefix="culture-codex-")
isolated_env = dict(os.environ)
isolated_env["XDG_DATA_HOME"] = os.path.join(self._isolated_home, ".local", "share")
isolated_env["XDG_STATE_HOME"] = os.path.join(self._isolated_home, ".local", "state")
```

Do not override `HOME` for the app-server runner; it must preserve Codex auth.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/agent/test_agent_runner.py tests/agent/test_supervisor.py tests/agent/test_daemon_surface.py -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add codexd/agent codexd/harness/supervisor.py tests/agent/test_agent_runner.py tests/agent/test_supervisor.py
git commit -m "feat: migrate codex app-server runner"
```

## Task 6: Implement Daemon CLI

**Files:**

- Modify: `codexd/cli.py`
- Modify: `codexd/__main__.py`
- Test: `tests/test_cli.py`
- Test: `tests/agent/test_daemon_cli.py`

- [ ] **Step 1: Add CLI tests**

Update `tests/test_cli.py` to keep the existing version test and replace `test_no_args_prints_help` expectations with command-group expectations:

```python
def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    out = capsys.readouterr().out
    assert "codexd" in out
    assert "daemon" in out
    assert "repo" in out
```

Create `tests/agent/test_daemon_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/test_cli.py tests/agent/test_daemon_cli.py -v
```

Expected: daemon parser and `run_daemon_main` are missing.

- [ ] **Step 3: Implement CLI parser and daemon dispatcher**

Replace `codexd/cli.py` with an argparse dispatcher containing this shape:

```python
"""Command-line entry point for codexd."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from typing import Any

from codexd import __version__
from codexd.agent.config import load_config
from codexd.agent.daemon import CodexDaemon

EXIT_USER_ERROR = 1
EXIT_ENV_ERROR = 2


def _hint(message: str) -> None:
    print(f"hint: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codexd",
        description="codexd - Codex agent for Culture and delegated repo work.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    daemon = sub.add_parser("daemon", help="Run the Culture Codex daemon.")
    daemon_sub = daemon.add_subparsers(dest="daemon_command")
    start = daemon_sub.add_parser("start", help="Start Codex agent daemon(s).")
    start.add_argument("nick", nargs="?", help="Agent nick to start.")
    start.add_argument("--all", action="store_true", dest="all_agents", help="Start all agents.")
    start.add_argument("--config", default="~/.culture/agents.yaml", help="Config file path.")
    start.set_defaults(func=_cmd_daemon_start)

    repo = sub.add_parser("repo", help="Run Codex against remote repositories.")
    repo_sub = repo.add_subparsers(dest="repo_command")
    run = repo_sub.add_parser("run", help="Clone, run Codex, commit, and push.")
    run.add_argument("remote")
    run.add_argument("--branch", required=True)
    run.add_argument("--task", required=True)
    run.add_argument("--base")
    run.add_argument("--workspace")
    run.set_defaults(func=_cmd_repo_run)

    push = repo_sub.add_parser("push", help="Retry pushing a managed workspace branch.")
    push.add_argument("--workspace")
    push.add_argument("--branch")
    push.set_defaults(func=_cmd_repo_push)

    clean = repo_sub.add_parser("clean", help="Clean the managed repo workspace.")
    clean.add_argument("--workspace")
    clean.set_defaults(func=_cmd_repo_clean)
    return parser


def _cmd_daemon_start(args: argparse.Namespace) -> int:
    if not args.all_agents and not args.nick:
        _hint("provide an agent nick or pass --all")
        return EXIT_USER_ERROR
    return run_daemon_main(nick=args.nick, all_agents=args.all_agents, config_path=args.config)


def _cmd_repo_run(args: argparse.Namespace) -> int:
    from codexd.repo.workflow import run_repo_task

    return run_repo_task(args.remote, branch=args.branch, task=args.task, base=args.base, workspace=args.workspace)


def _cmd_repo_push(args: argparse.Namespace) -> int:
    from codexd.repo.workflow import push_workspace

    return push_workspace(workspace=args.workspace, branch=args.branch)


def _cmd_repo_clean(args: argparse.Namespace) -> int:
    from codexd.repo.workflow import clean_workspace

    return clean_workspace(workspace=args.workspace)


def run_daemon_main(*, nick: str | None, all_agents: bool, config_path: str) -> int:
    try:
        config = load_config(config_path)
    except OSError as exc:
        _hint(f"failed to load config {config_path!r}: {exc}")
        return EXIT_ENV_ERROR

    if all_agents:
        agents = config.agents
    else:
        agent = config.get_agent(nick or "")
        if agent is None:
            _hint(f"agent {nick!r} was not found in {config_path!r}")
            return EXIT_USER_ERROR
        agents = [agent]

    if not agents:
        _hint("no Codex agents are configured")
        return EXIT_USER_ERROR

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(_run_daemons(config, agents))
    return 0


async def _run_daemons(config: Any, agents: list[Any]) -> None:
    daemons = [CodexDaemon(config, agent) for agent in agents]
    for daemon in daemons:
        await daemon.start()
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()
    for daemon in reversed(daemons):
        await daemon.stop()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Ensure `codexd/__main__.py` delegates to CLI**

`codexd/__main__.py` should be:

```python
"""Run codexd as a module."""

from __future__ import annotations

import sys

from codexd.cli import main


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run CLI tests**

Run:

```bash
uv run pytest tests/test_cli.py tests/agent/test_daemon_cli.py -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add codexd/cli.py codexd/__main__.py tests/test_cli.py tests/agent/test_daemon_cli.py
git commit -m "feat: add codexd daemon CLI"
```

## Task 7: Add Repo Workspace Validation

**Files:**

- Create: `codexd/repo/__init__.py`
- Create: `codexd/repo/workspace.py`
- Test: `tests/repo/test_workspace.py`

- [ ] **Step 1: Write workspace tests**

Create `tests/repo/test_workspace.py`:

```python
"""Managed workspace validation for codexd repo commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from codexd.repo.workspace import (
    DEFAULT_WORKSPACE,
    derive_checkout_name,
    managed_workspace_root,
    validate_branch_name,
    validate_remote,
    validate_workspace_path,
)


def test_default_workspace_is_codexd_work(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert managed_workspace_root(None) == tmp_path / DEFAULT_WORKSPACE


def test_explicit_workspace_must_stay_inside_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="inside"):
        validate_workspace_path(Path("/tmp/outside"), repo_root=tmp_path)


def test_workspace_refuses_repo_root(tmp_path) -> None:
    with pytest.raises(ValueError, match="repository root"):
        validate_workspace_path(tmp_path, repo_root=tmp_path)


def test_branch_validation_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="branch"):
        validate_branch_name("../main")


def test_remote_validation_accepts_https_and_ssh() -> None:
    assert validate_remote("https://github.com/agentculture/example.git") == "https://github.com/agentculture/example.git"
    assert validate_remote("git@github.com:agentculture/example.git") == "git@github.com:agentculture/example.git"


def test_remote_validation_rejects_local_paths() -> None:
    with pytest.raises(ValueError, match="remote"):
        validate_remote("../other")


def test_checkout_name_is_sanitized() -> None:
    assert derive_checkout_name("https://github.com/AgentCulture/codexd.git") == "codexd"
    assert derive_checkout_name("git@github.com:AgentCulture/codex-guide.git") == "codex-guide"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/repo/test_workspace.py -v
```

Expected: import failure for `codexd.repo.workspace`.

- [ ] **Step 3: Implement workspace validation**

Create `codexd/repo/__init__.py`:

```python
"""Remote repository workflows for codexd."""
```

Create `codexd/repo/workspace.py`:

```python
"""Managed workspace validation for repo commands."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_WORKSPACE = Path(".codexd") / "work"
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SSH_REMOTE_RE = re.compile(r"^git@[A-Za-z0-9._-]+:[A-Za-z0-9._/-]+(?:\.git)?$")


def managed_workspace_root(workspace: str | None, *, repo_root: Path | None = None) -> Path:
    root = (repo_root or Path.cwd()).resolve()
    candidate = Path(workspace) if workspace else DEFAULT_WORKSPACE
    return validate_workspace_path(candidate, repo_root=root)


def validate_workspace_path(path: Path, *, repo_root: Path) -> Path:
    candidate = path if path.is_absolute() else repo_root / path
    candidate = candidate.resolve()
    repo_root = repo_root.resolve()

    if candidate == repo_root:
        raise ValueError("workspace must not be the repository root")
    if candidate == Path.home().resolve():
        raise ValueError("workspace must not be the user's home directory")
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("workspace must be inside the current repository") from exc
    return candidate


def validate_branch_name(branch: str) -> str:
    if not branch or branch.strip() != branch:
        raise ValueError("branch name must be non-empty and trimmed")
    if ".." in branch or branch.startswith("/") or branch.endswith("/"):
        raise ValueError(f"unsafe branch name: {branch!r}")
    if not _BRANCH_RE.match(branch):
        raise ValueError(f"unsafe branch name: {branch!r}")
    return branch


def validate_remote(remote: str) -> str:
    parsed = urlparse(remote)
    if parsed.scheme == "https" and parsed.netloc and parsed.path:
        return remote
    if _SSH_REMOTE_RE.match(remote):
        return remote
    raise ValueError("remote must be an HTTPS or SSH Git remote")


def derive_checkout_name(remote: str) -> str:
    raw = remote.rstrip("/").split("/")[-1]
    if ":" in raw:
        raw = raw.split(":")[-1]
    if raw.endswith(".git"):
        raw = raw[:-4]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-_").lower()
    if not safe:
        raise ValueError("remote did not contain a usable repository name")
    return safe
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/repo/test_workspace.py -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add codexd/repo tests/repo/test_workspace.py
git commit -m "feat: validate codexd repo workspaces"
```

## Task 8: Add Git Operations Layer

**Files:**

- Create: `codexd/repo/git.py`
- Test: `tests/repo/test_git_ops.py`

- [ ] **Step 1: Write Git operation tests**

Create `tests/repo/test_git_ops.py`:

```python
"""Git operations for managed repo workflows."""

from __future__ import annotations

import subprocess
from pathlib import Path

from codexd.repo.git import checkout_branch, commit_all, has_changes, push_branch, run_git


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=path, text=True, capture_output=True, check=True)


def _seed_repo(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "codexd@example.invalid")
    _git(work, "config", "user.name", "codexd test")
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "seed")
    _git(work, "push", "origin", "HEAD:main")
    return origin, work


def test_has_changes_detects_dirty_worktree(tmp_path) -> None:
    _, work = _seed_repo(tmp_path)

    assert has_changes(work) is False
    (work / "README.md").write_text("changed\n", encoding="utf-8")
    assert has_changes(work) is True


def test_commit_all_returns_sha(tmp_path) -> None:
    _, work = _seed_repo(tmp_path)
    (work / "README.md").write_text("changed\n", encoding="utf-8")

    sha = commit_all(work, "codexd: apply changes")

    assert len(sha) >= 7
    assert has_changes(work) is False


def test_checkout_and_push_branch(tmp_path) -> None:
    origin, work = _seed_repo(tmp_path)

    checkout_branch(work, "codex/test", base="origin/main")
    (work / "feature.txt").write_text("feature\n", encoding="utf-8")
    commit_all(work, "codexd: feature")
    push_branch(work, "codex/test")

    refs = subprocess.run(
        ["git", "--git-dir", str(origin), "show-ref", "refs/heads/codex/test"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "refs/heads/codex/test" in refs.stdout
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/repo/test_git_ops.py -v
```

Expected: import failure for `codexd.repo.git`.

- [ ] **Step 3: Implement Git operations**

Create `codexd/repo/git.py`:

```python
"""Small Git command wrapper for managed repo workflows."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a Git command fails."""


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise GitError(detail)
    return result


def clone(remote: str, checkout_path: Path) -> None:
    result = subprocess.run(
        ["git", "clone", remote, str(checkout_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git clone failed"
        raise GitError(detail)


def checkout_branch(repo: Path, branch: str, *, base: str | None = None) -> None:
    if base:
        run_git(repo, "fetch", "origin", base)
        run_git(repo, "checkout", "-B", branch, base)
        return
    run_git(repo, "checkout", "-B", branch)


def has_changes(repo: Path) -> bool:
    result = run_git(repo, "status", "--porcelain")
    return bool(result.stdout.strip())


def commit_all(repo: Path, message: str) -> str:
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", message)
    return run_git(repo, "rev-parse", "--short", "HEAD").stdout.strip()


def push_branch(repo: Path, branch: str) -> None:
    run_git(repo, "push", "origin", f"HEAD:{branch}")
```

- [ ] **Step 4: Run Git tests**

Run:

```bash
uv run pytest tests/repo/test_git_ops.py -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add codexd/repo/git.py tests/repo/test_git_ops.py
git commit -m "feat: add codexd repo git operations"
```

## Task 9: Add Repo Workflow Orchestration

**Files:**

- Create: `codexd/repo/workflow.py`
- Test: `tests/repo/test_workflow.py`
- Modify: `tests/agent/test_daemon_cli.py`

- [ ] **Step 1: Write workflow tests with patched app-server runner**

Create `tests/repo/test_workflow.py`:

```python
"""End-to-end repo workflow tests without a real Codex process."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

from codexd.repo.workflow import RepoRunResult, run_repo_task


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=path, text=True, capture_output=True, check=True)


def _seed_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    _git(seed, "config", "user.email", "codexd@example.invalid")
    _git(seed, "config", "user.name", "codexd test")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", "origin", "HEAD:main")
    return origin


def test_repo_run_clones_runs_commits_and_pushes(tmp_path, monkeypatch, capsys) -> None:
    origin = _seed_origin(tmp_path)
    monkeypatch.chdir(tmp_path)

    async def fake_turn(runner, task: str) -> None:
        checkout = Path(runner.directory)
        (checkout / "result.txt").write_text(task + "\n", encoding="utf-8")

    with patch("codexd.repo.workflow.run_app_server_turn", new=AsyncMock(side_effect=fake_turn)):
        rc = run_repo_task(str(origin), branch="codex/result", task="write result", workspace=".codexd/work")

    assert rc == 0
    pushed = subprocess.run(
        ["git", "--git-dir", str(origin), "show-ref", "refs/heads/codex/result"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "refs/heads/codex/result" in pushed.stdout
    assert "pushed" in capsys.readouterr().out


def test_repo_run_no_changes_does_not_push(tmp_path, monkeypatch, capsys) -> None:
    origin = _seed_origin(tmp_path)
    monkeypatch.chdir(tmp_path)

    with patch("codexd.repo.workflow.run_app_server_turn", new=AsyncMock(return_value=None)):
        rc = run_repo_task(str(origin), branch="codex/noop", task="do nothing", workspace=".codexd/work")

    assert rc == 0
    refs = subprocess.run(
        ["git", "--git-dir", str(origin), "show-ref", "refs/heads/codex/noop"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert refs.returncode != 0
    assert "no changes" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/repo/test_workflow.py -v
```

Expected: import failure for `codexd.repo.workflow`.

- [ ] **Step 3: Implement workflow orchestration**

Create `codexd/repo/workflow.py`:

```python
"""Repo command workflows for codexd."""

from __future__ import annotations

import asyncio
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from codexd.agent.agent_runner import CodexAgentRunner
from codexd.repo import git
from codexd.repo.workspace import (
    derive_checkout_name,
    managed_workspace_root,
    validate_branch_name,
    validate_remote,
)


@dataclass(frozen=True)
class RepoRunResult:
    workspace: Path
    branch: str
    commit_sha: str | None
    pushed: bool


def _hint(message: str) -> None:
    print(f"hint: {message}", file=sys.stderr)


def _clean_root(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


async def run_app_server_turn(runner: CodexAgentRunner, task: str) -> None:
    await runner.start()
    try:
        await runner.send_prompt(task)
        await runner.wait_until_idle()
    finally:
        await runner.stop()


def run_repo_task(
    remote: str,
    *,
    branch: str,
    task: str,
    base: str | None = None,
    workspace: str | None = None,
) -> int:
    try:
        remote = validate_remote(remote)
        branch = validate_branch_name(branch)
        workspace_root = managed_workspace_root(workspace)
        _clean_root(workspace_root)
        checkout = workspace_root / derive_checkout_name(remote)
        git.clone(remote, checkout)
        git.run_git(checkout, "config", "user.email", "codexd@example.invalid")
        git.run_git(checkout, "config", "user.name", "codexd")
        git.checkout_branch(checkout, branch, base=base)
        runner = CodexAgentRunner(model="gpt-5.4", directory=str(checkout))
        asyncio.run(run_app_server_turn(runner, task))
        if not git.has_changes(checkout):
            print(f"no changes: workspace={checkout} branch={branch}")
            return 0
        commit_sha = git.commit_all(checkout, f"codexd: {task[:64]}")
        git.push_branch(checkout, branch)
        print(f"pushed: workspace={checkout} branch={branch} commit={commit_sha} target=origin/{branch}")
        return 0
    except ValueError as exc:
        _hint(str(exc))
        return 1
    except (git.GitError, OSError, RuntimeError) as exc:
        _hint(str(exc))
        return 2


def push_workspace(*, workspace: str | None = None, branch: str | None = None) -> int:
    try:
        workspace_root = managed_workspace_root(workspace)
        if branch is None:
            raise ValueError("--branch is required for repo push")
        branch = validate_branch_name(branch)
        git.push_branch(workspace_root, branch)
        print(f"pushed: workspace={workspace_root} target=origin/{branch}")
        return 0
    except ValueError as exc:
        _hint(str(exc))
        return 1
    except (git.GitError, OSError) as exc:
        _hint(str(exc))
        return 2


def clean_workspace(*, workspace: str | None = None) -> int:
    try:
        workspace_root = managed_workspace_root(workspace)
        _clean_root(workspace_root)
        print(f"cleaned: workspace={workspace_root}")
        return 0
    except ValueError as exc:
        _hint(str(exc))
        return 1
    except OSError as exc:
        _hint(str(exc))
        return 2
```

- [ ] **Step 4: Add `wait_until_idle` to `CodexAgentRunner`**

In `codexd/agent/agent_runner.py`, add this public coroutine next to `send_prompt`:

```python
async def wait_until_idle(self) -> None:
    """Wait for the current queued turn to complete."""
    await self._turn_done.wait()
```

- [ ] **Step 5: Run workflow tests**

Run:

```bash
uv run pytest tests/repo/test_workspace.py tests/repo/test_git_ops.py tests/repo/test_workflow.py tests/agent/test_daemon_cli.py -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add codexd/repo/workflow.py codexd/agent/agent_runner.py tests/repo/test_workflow.py tests/agent/test_daemon_cli.py
git commit -m "feat: run Codex app-server on managed repos"
```

## Task 10: Add Packaged Codex Skill And Culture YAML

**Files:**

- Create: `codexd/agent/skill/__init__.py`
- Create: `codexd/agent/skill/SKILL.md`
- Create: `codexd/agent/skill/irc_client.py`
- Create: `codexd/agent/culture.yaml`
- Modify: `pyproject.toml`
- Test: `tests/agent/test_packaged_assets.py`

- [ ] **Step 1: Write packaged asset tests**

Create `tests/agent/test_packaged_assets.py`:

```python
"""Packaged Culture assets for codexd."""

from __future__ import annotations

from pathlib import Path

import tomllib


def test_codex_skill_mentions_codexd_paths() -> None:
    skill = Path("codexd/agent/skill/SKILL.md").read_text(encoding="utf-8")

    assert "Codex" in skill
    assert "culture channel" in skill
    assert "cultureagent" not in skill


def test_hatch_force_includes_skill_and_culture_yaml() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    force_include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert "codexd/agent/culture.yaml" in force_include
    assert "codexd/agent/skill/SKILL.md" in force_include
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/agent/test_packaged_assets.py -v
```

Expected: files and force-includes are missing.

- [ ] **Step 3: Copy packaged assets**

Run:

```bash
mkdir -p codexd/agent/skill
cp ../cultureagent/cultureagent/clients/codex/culture.yaml codexd/agent/culture.yaml
cp ../cultureagent/cultureagent/clients/codex/skill/__init__.py codexd/agent/skill/__init__.py
cp ../cultureagent/cultureagent/clients/codex/skill/SKILL.md codexd/agent/skill/SKILL.md
cp ../cultureagent/cultureagent/clients/codex/skill/irc_client.py codexd/agent/skill/irc_client.py
perl -0pi -e 's/cultureagent/codexd/g; s/cultureagent\.clients\.codex/codexd.agent/g; s/cultureagent\.clients\.shared/codexd.harness/g' codexd/agent/skill/* codexd/agent/culture.yaml
```

- [ ] **Step 4: Add Hatch force-includes**

Add to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"codexd/agent/culture.yaml" = "codexd/agent/culture.yaml"
"codexd/agent/skill/SKILL.md" = "codexd/agent/skill/SKILL.md"
```

If the table already exists, add only the two keys.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/agent/test_packaged_assets.py -v
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add codexd/agent/skill codexd/agent/culture.yaml pyproject.toml tests/agent/test_packaged_assets.py
git commit -m "feat: package codexd culture assets"
```

## Task 11: Update Documentation

**Files:**

- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_readme.py`

- [ ] **Step 1: Write documentation tests**

Create `tests/test_readme.py`:

```python
"""README describes implemented codexd behavior."""

from __future__ import annotations

from pathlib import Path


def test_readme_documents_daemon_and_repo_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "codexd daemon start" in readme
    assert "codexd repo run" in readme
    assert "initial scaffold" not in readme.lower()
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/test_readme.py -v
```

Expected: README still describes scaffold state.

- [ ] **Step 3: Update README**

Replace the scaffold description with:

```markdown
`codexd` is a self-contained Codex agent for the AgentCulture mesh. It can run a
Codex-backed Culture daemon and can delegate work to remote repositories by
cloning them into a managed workspace, running Codex app-server, committing
changes, and pushing a branch.
```

Add command examples:

````markdown
## Daemon

```bash
codexd daemon start spark-codex --config ~/.culture/agents.yaml
codexd daemon start --all --config ~/.culture/agents.yaml
```

## Remote Repository Work

```bash
codexd repo run git@github.com:agentculture/example.git \
  --branch codex/example-task \
  --task "Implement the requested change"
```

Managed checkouts live under `.codexd/work` by default and are cleaned before a
new clone.
````

- [ ] **Step 4: Update AGENTS.md**

Remove the sentence that says daemon task orchestration is not implemented once Task 9 is complete. Replace the Project State paragraph with:

```markdown
`codexd` is a Codex-only Culture agent for delegated repository tasks and
reviewable pull requests in the AgentCulture ecosystem. It includes a runnable
Codex Culture daemon, repo-local skills, tests, lint, CI, and app-server based
remote-repository work commands.
```

- [ ] **Step 5: Update CHANGELOG.md**

Add an Unreleased entry:

```markdown
## [Unreleased]

### Added

- Migrated the Codex Culture daemon into `codexd` as a self-contained runtime.
- Added `codexd repo run` for managed clone, Codex app-server execution, commit,
  and branch push workflows.
```

- [ ] **Step 6: Run documentation tests and markdown lint**

Run:

```bash
uv run pytest tests/test_readme.py -v
markdownlint-cli2 "README.md" "AGENTS.md" "CHANGELOG.md"
```

Expected: tests and markdown lint pass.

- [ ] **Step 7: Commit**

```bash
git add README.md AGENTS.md CHANGELOG.md tests/test_readme.py
git commit -m "docs: document codexd daemon and repo workflows"
```

## Task 12: Full Validation And Coverage Cleanup

**Files:**

- Modify: `pyproject.toml`
- Modify: tests as needed for import paths or deterministic timing

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run pytest -n auto --cov=codexd
```

Expected: tests pass or fail only because live Codex process paths are counted in coverage.

- [ ] **Step 2: If coverage fails on live process modules, update omit list**

In `pyproject.toml`, keep coverage focused by omitting subprocess shims and live Codex process paths:

```toml
[tool.coverage.run]
source = ["codexd"]
omit = [
    "codexd/__pycache__/*",
    "codexd/__main__.py",
    "codexd/agent/skill/irc_client.py",
    "codexd/agent/agent_runner.py",
    "codexd/agent/supervisor.py",
]
```

Do not omit `codexd/repo/workflow.py`; repo workflow behavior must remain covered.

- [ ] **Step 3: Run formatting and lint checks**

Run:

```bash
uv run black --check codexd tests
uv run isort --check-only codexd tests
uv run flake8 codexd tests
uv run bandit -c pyproject.toml -r codexd
markdownlint-cli2 "**/*.md"
uv build
uv run python -m codexd --version
```

Expected: all checks pass.

- [ ] **Step 4: Fix deterministic lint failures only**

If `black` fails, run:

```bash
uv run black codexd tests
```

If `isort` fails, run:

```bash
uv run isort codexd tests
```

If `flake8` or `bandit` fails, make the smallest code change that addresses the exact reported line. Do not add broad ignores unless the same Bandit skip already exists in `../cultureagent/pyproject.toml` for migrated harness code.

- [ ] **Step 5: Re-run full validation**

Run:

```bash
uv run pytest -n auto --cov=codexd
uv run black --check codexd tests
uv run isort --check-only codexd tests
uv run flake8 codexd tests
uv run bandit -c pyproject.toml -r codexd
markdownlint-cli2 "**/*.md"
uv build
uv run python -m codexd --version
```

Expected: all checks pass.

- [ ] **Step 6: Commit final validation adjustments**

```bash
git add pyproject.toml codexd tests README.md AGENTS.md CHANGELOG.md uv.lock
git commit -m "test: validate codexd culture agent migration"
```

## Self-Review

Spec coverage:

- Self-contained Codex migration: Tasks 2 through 6 and Task 10 copy/adapt the Codex backend and required shared harness modules without a `cultureagent` runtime dependency.
- Codex-only scope: Tasks avoid Claude, Copilot, ACP, and generic backend parity except where copied tests must be narrowed.
- Daemon command: Task 6 implements `codexd daemon start [<nick>|--all] [--config PATH]`.
- Repo commands: Tasks 7 through 9 implement workspace cleanup, clone, app-server turn, commit, automatic push, retry push, and clean.
- Safety rules: Task 7 validates workspace, branch, and remotes; Task 9 preserves failed-push workspaces by not cleaning after clone.
- Error handling: Task 6 and Task 9 return `1` for user input, `2` for environment/setup failures, and emit `hint:` lines.
- Tests: Each implementation task starts with failing tests and ends with focused verification; Task 12 runs the full required validation set.

Placeholder scan: This plan contains no unfinished markers or open-ended implementation steps. Every code-changing step names exact files and provides command or code content.

Type consistency: `CodexAgentRunner.wait_until_idle`, `run_app_server_turn`, `run_repo_task`, `push_workspace`, and `clean_workspace` are introduced before CLI calls rely on them. `codexd.agent` and `codexd.harness` import paths are used consistently.
