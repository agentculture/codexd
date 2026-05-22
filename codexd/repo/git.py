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
        run_git(repo, "fetch", "origin")
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
