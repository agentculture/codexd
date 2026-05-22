# codexd Culture Agent Migration Design

Date: 2026-05-22

## Purpose

`codexd` will become the self-contained Codex agent package for Culture. The
project will migrate the Codex backend from `../cultureagent`, including the
shared harness pieces that backend depends on, and add commands for delegated
remote-repository work.

The result should not depend on `cultureagent` at runtime. This migration is
Codex-only: Claude, Copilot, ACP, and any general multi-backend framework are
outside this design.

## Scope

Included:

- A runnable Culture Codex daemon exposed as:

  ```text
  codexd daemon start [<nick>|--all] [--config PATH]
  ```

- Codex app-server based agent execution adapted from
  `cultureagent.clients.codex`.
- Codex supervisor behavior adapted from the existing Codex backend.
- Internal harness support copied and adapted from `cultureagent` only where it
  is needed by the Codex daemon.
- Repo-work commands that clone a remote repository into a managed gitignored
  workspace, clean that workspace before cloning, run a Codex app-server turn,
  commit any resulting changes, and push the requested branch automatically.
- Tests for config, daemon construction, runner behavior, repo workspace
  lifecycle, CLI parsing, and error handling.
- Documentation updates after implementation so `codexd` no longer describes
  implemented behavior as a scaffold.

Excluded:

- Claude, Copilot, ACP, or other backend migration.
- A generic replacement for `cultureagent`.
- A web UI.
- New daemon behaviors beyond the existing Codex path and the repo-work
  commands described here.

## Architecture

The top-level package remains `codexd/`. The implementation will use three
internal layers.

### `codexd.harness`

`codexd.harness` contains the migrated shared pieces needed by the Codex daemon:

- config loading and saving
- attention tracking
- message buffering
- IPC framing
- IRC transport
- Unix socket server
- telemetry helpers
- room parsing
- webhook types and client
- queued daemon base behavior

These modules are internal to `codexd`. They are copied and adapted to support
the Codex runtime, not to expose a public multi-backend framework.

### `codexd.agent`

`codexd.agent` contains Codex-specific runtime code:

- `CodexAgentRunner`
- `CodexSupervisor`
- `CodexDaemon`
- Codex config dataclasses
- constants
- the in-skill IRC client

Imports from `cultureagent.clients.*` will be rewritten to `codexd.*`. Defaults
should remain Codex-specific, including `agent="codex"`, the current Codex model
defaults, and `culture.harness.codex` telemetry naming unless implementation
evidence requires a focused change.

### `codexd.repo`

`codexd.repo` owns remote-repository task execution:

- validating remotes, branch names, and managed workspace paths
- cleaning the managed workspace
- cloning the remote repository
- preparing the requested branch
- launching a Codex app-server session in the cloned checkout
- submitting one task prompt
- committing changes if Codex modifies files
- pushing `HEAD` to the requested remote branch

The repo workflow reuses the app-server runner shape rather than introducing a
separate `codex exec` path.

## CLI Shape

The public CLI surface will be:

```text
codexd --version
codexd daemon start [<nick>|--all] [--config PATH]
codexd repo run <remote> --branch <branch> --task <prompt> [--base <ref>] [--workspace <path>]
codexd repo push [--workspace <path>] [--branch <branch>]
codexd repo clean [--workspace <path>]
```

`codexd repo run` is the primary workflow. `repo push` exists for retrying a
failed push from an intact workspace. `repo clean` exists for explicit cleanup
of the managed workspace.

The default workspace root is `.codexd/work`, and `.codexd/` must be ignored by
Git.

## Daemon Flow

`codexd daemon start` mirrors the Codex backend from `cultureagent`:

1. Load YAML config.
2. Select one configured Codex agent or all configured agents.
3. Connect to IRC.
4. Start the Unix socket server.
5. Launch `codex app-server` with the configured model and working directory.
6. Route IRC mentions and socket commands through the queued daemon behavior.
7. Stop the runner, socket, and transport cleanly on shutdown.

The runner isolates Codex data and state per session while preserving the local
environment needed for Codex authentication.

## Repo Run Flow

`codexd repo run` performs:

1. Validate the remote URL, branch name, and workspace path.
2. Delete the managed workspace directory if it already exists.
3. Clone the remote into `.codexd/work/<safe-repo-name>`.
4. Check out `--base` if supplied, otherwise use the remote default branch.
5. Create or reset the requested local branch.
6. Start `codex app-server` in the cloned checkout.
7. Send the task prompt as a single app-server turn.
8. Stop the app-server session.
9. If files changed, commit them with a generated message.
10. Push `HEAD:<branch>` to `origin`.
11. Print a concise result that includes workspace path, branch, commit SHA when
    a commit was created, and push target.

If Codex makes no changes, the command exits successfully without committing or
pushing.

## Safety Rules

- Cleanup is restricted to `.codexd/work` or an explicitly passed workspace path
  inside the current repository.
- The command refuses to delete any path outside the current repository.
- The command refuses to delete the repository root, the user's home directory,
  or any path that does not match the managed workspace intent.
- Branch names must be non-empty and must not contain path traversal or other
  unsafe ref syntax.
- Remotes must parse as SSH or HTTPS Git remotes.
- If clone, app-server launch, commit, or push fails, the command exits
  non-zero with a `hint:` line.
- If push fails, the local clone remains intact for inspection and retry.

## Error Handling

The CLI uses these exit codes:

- `0`: success
- `1`: user-input error, such as invalid arguments or unsafe paths
- `2`: environment or setup error, such as missing `codex`, failed clone, failed
  app-server startup, no configured agent, or push rejection
- `3+`: reserved

Every non-success path should include a `hint:` line. Success output should keep
stdout usable by humans and future automation.

## Testing

Tests should be focused and network-free by default:

- Config tests cover Codex defaults and YAML round trips.
- Daemon tests cover constructor shape, skip mode, meta-response cleanup, queue
  behavior, and system prompt construction.
- Runner tests patch app-server JSON-RPC calls so CI does not need a live Codex
  binary.
- Repo workflow tests use temporary local bare Git repositories so clone,
  commit, and push behavior is real without network access.
- CLI tests cover argument parsing, exit codes, and `hint:` output.

Verification for the implementation should include:

```bash
uv build
uv run python -m codexd --version
uv run pytest -n auto --cov=codexd
uv run black --check codexd tests
uv run isort --check-only codexd tests
uv run flake8 codexd tests
uv run bandit -c pyproject.toml -r codexd
markdownlint-cli2 "**/*.md"
```

Coverage configuration may omit true subprocess shims and live Codex process
paths, but the repo workflow itself should be covered by patching the app-server
runner rather than invoking a real Codex process.
