# Repository Guidelines

## Project State

`codexd` is a Codex-only Culture agent for delegated repository tasks and
reviewable pull requests in the AgentCulture ecosystem. It includes a runnable
Codex Culture daemon, repo-local skills, tests, lint, CI, and app-server based
remote-repository work commands.

## Project Structure

- `codexd/`: top-level Python package. No `src/` wrapper.
- `tests/`: pytest suite for the implemented package surface.
- `.agents/skills/`: repo-local Codex skills vendored from Culture siblings.
- `.agents/skills.local.yaml.example`: portable example for per-machine skill paths.
- `.github/workflows/`: CI and publish workflows.
- `culture.yaml`: AgentCulture mesh registration for the resident Codex agent.

## Commands

Use these commands from the repository root:

- `uv sync`: create/update the local uv environment.
- `uv build`: verify package metadata and build artifacts.
- `uv run python -m codexd --version`: check the package version entry point.
- `uv run pytest -n auto --cov=codexd`: run the test suite with coverage.
- `uv run black --check codexd tests`: check formatting.
- `uv run isort --check-only codexd tests`: check import ordering.
- `uv run flake8 codexd tests`: run style linting.
- `uv run bandit -c pyproject.toml -r codexd`: run security linting.
- `markdownlint-cli2 "**/*.md"`: lint Markdown using the repo config.

## Coding Conventions

- Python requires 3.12 or newer.
- Keep the daemon surface minimal and tested; no untested verb should merge.
- Prefer small modules with explicit CLI dispatch over hidden side effects.
- Use `importlib.metadata` as the version source; do not maintain a separate
  version literal in package code.
- Keep commands, paths, and config examples portable; avoid user-specific
  absolute paths in committed files.

## Skills

Codex skills belong in `.agents/skills` for repository-local use. If a Culture
skill is vendored from a legacy source, adapt visible paths and signatures to
Codex before committing.

When Codex starts inside this repository, repo-local skills should be
auto-discovered from `.agents/skills`. Use `/skills` or `$` completion to find
them, and invoke the PR/CI and coordination workflows as `$cicd` and
`$communicate`. Do not document or expect `/cicd` or `/communicate` as skill
invocations; slash commands and skill mentions are separate interfaces.

The local `$HOME/.codex/skills` directory is an environment-specific installed
bundle location, not the canonical repository layout.

## PR Expectations

- Work on feature branches, not directly on `main`.
- Keep PRs reviewable: explain what changed, why, validation performed, and
  follow-up work.
- Version and changelog updates are required after the initial scaffold lands;
  the CI version-check job enforces this once `main` has `pyproject.toml`.
