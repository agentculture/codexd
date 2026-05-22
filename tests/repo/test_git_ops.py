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
