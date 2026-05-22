"""README describes implemented codexd behavior."""

from __future__ import annotations

from pathlib import Path


def test_readme_documents_daemon_and_repo_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "codexd daemon start" in readme
    assert "codexd repo run" in readme
    assert "initial scaffold" not in readme.lower()
