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
