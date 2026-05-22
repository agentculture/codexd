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
    assert (
        validate_remote("https://github.com/agentculture/example.git")
        == "https://github.com/agentculture/example.git"
    )
    assert (
        validate_remote("git@github.com:agentculture/example.git")
        == "git@github.com:agentculture/example.git"
    )


def test_remote_validation_rejects_local_paths() -> None:
    with pytest.raises(ValueError, match="remote"):
        validate_remote("../other")


def test_checkout_name_is_sanitized() -> None:
    assert derive_checkout_name("https://github.com/AgentCulture/codexd.git") == "codexd"
    assert derive_checkout_name("git@github.com:AgentCulture/codex-guide.git") == "codex-guide"


def test_workspace_refuses_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with pytest.raises(ValueError, match="home"):
        validate_workspace_path(tmp_path, repo_root=tmp_path / "repo")


def test_branch_validation_rejects_empty_and_untrimmed() -> None:
    with pytest.raises(ValueError, match="trimmed"):
        validate_branch_name(" main")
    with pytest.raises(ValueError, match="trimmed"):
        validate_branch_name("")


def test_branch_validation_rejects_invalid_characters() -> None:
    with pytest.raises(ValueError, match="branch"):
        validate_branch_name("feature name")


def test_checkout_name_rejects_empty_remote_name() -> None:
    with pytest.raises(ValueError, match="usable"):
        derive_checkout_name("https://github.com/AgentCulture/.git")
