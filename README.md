# codexd

Codex daemon for delegated repo tasks and reviewable PRs.

`codexd` is an AgentCulture sibling project. It is currently in initial
scaffold state: package metadata, Culture registration, Codex repo guidance,
repo-local skills, CI, lint, and tests exist; daemon task orchestration is not
implemented yet.

## Quick Start

```bash
uv sync
uv run python -m codexd --version
uv run pytest -n auto --cov=codexd
```

## Codex Conventions

- Repository instructions live in `AGENTS.md`.
- Repo-local skills live in `.agents/skills`.
- Per-machine skill config should be copied from
  `.agents/skills.local.yaml.example` to `.agents/skills.local.yaml`, which is
  ignored by Git.

The local `$HOME/.codex/skills` path is treated as an environment-specific
install location, not a committed repository layout.
