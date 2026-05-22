# codexd

Codex daemon for delegated repo tasks and reviewable PRs.

`codexd` is a self-contained Codex agent for the AgentCulture mesh. It can run a
Codex-backed Culture daemon and can delegate work to remote repositories by
cloning them into a managed workspace, running Codex app-server, committing
changes, and pushing a branch.

## Quick Start

```bash
uv sync
uv run python -m codexd --version
uv run pytest -n auto --cov=codexd
```

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

## Codex Conventions

- Repository instructions live in `AGENTS.md`.
- Repo-local skills live in `.agents/skills` and are auto-discovered when Codex
  starts inside this repository.
- Use `/skills` or `$` completion to find available skills. Invoke the repo
  workflow skills as `$cicd` and `$communicate`; `/cicd` and `/communicate` are
  not Codex skill invocations.
- `.agents/skills.local.yaml.example` documents optional per-machine values
  for local workflow tooling. A copied `.agents/skills.local.yaml` is ignored
  by Git and is not used for Codex skill discovery.

The local `$HOME/.codex/skills` path is treated as an environment-specific
install location, not a committed repository layout. Restart Codex if newly
changed repo-local skills do not appear in `/skills`.
