---
name: version-bump
description: Bump the semver version in pyproject.toml and prepend a Keep-a-Changelog entry to CHANGELOG.md. Use when preparing a release or a PR after the initial scaffold.
---

# Version Bump

Bump the semver version in `pyproject.toml` and prepend a new entry to
`CHANGELOG.md`. This repo uses package metadata as the version source; package
code reads it through `importlib.metadata`.

## Usage

Run from the repo root.

```bash
# With changelog content
echo '{"added":["New X"],"changed":["Refactored Y"],"fixed":["Bug in Z"]}' \
  | python3 .agents/skills/version-bump/scripts/bump.py minor

# Without changelog content
python3 .agents/skills/version-bump/scripts/bump.py patch

# Check current version without bumping
python3 .agents/skills/version-bump/scripts/bump.py show
```

The script edits `pyproject.toml` and `CHANGELOG.md`. Commit those files with
the code change so the CI `version-check` job sees a consistent bump.
