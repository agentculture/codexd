"""Repo command workflows for codexd."""

from __future__ import annotations

import asyncio
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from codexd.agent.agent_runner import CodexAgentRunner
from codexd.repo import git
from codexd.repo.workspace import (
    derive_checkout_name,
    managed_workspace_root,
    validate_branch_name,
    validate_remote,
)


@dataclass(frozen=True)
class RepoRunResult:
    workspace: Path
    branch: str
    commit_sha: str | None
    pushed: bool


def _hint(message: str) -> None:
    print(f"hint: {message}", file=sys.stderr)


def _clean_root(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


async def run_app_server_turn(runner: CodexAgentRunner, task: str) -> None:
    await runner.start()
    try:
        await runner.send_prompt(task)
        await runner.wait_until_idle()
    finally:
        await runner.stop()


def run_repo_task(
    remote: str,
    *,
    branch: str,
    task: str,
    base: str | None = None,
    workspace: str | None = None,
) -> int:
    try:
        remote = validate_remote(remote)
        branch = validate_branch_name(branch)
        workspace_root = managed_workspace_root(workspace)
        _clean_root(workspace_root)
        checkout = workspace_root / derive_checkout_name(remote)
        git.clone(remote, checkout)
        git.run_git(checkout, "config", "user.email", "codexd@example.invalid")
        git.run_git(checkout, "config", "user.name", "codexd")
        git.checkout_branch(checkout, branch, base=base)
        runner = CodexAgentRunner(model="gpt-5.4", directory=str(checkout))
        asyncio.run(run_app_server_turn(runner, task))
        if not git.has_changes(checkout):
            print(f"no changes: workspace={checkout} branch={branch}")
            return 0
        commit_sha = git.commit_all(checkout, f"codexd: {task[:64]}")
        git.push_branch(checkout, branch)
        print(f"pushed: workspace={checkout} branch={branch} commit={commit_sha} target=origin/{branch}")
        return 0
    except ValueError as exc:
        _hint(str(exc))
        return 1
    except (git.GitError, OSError, RuntimeError) as exc:
        _hint(str(exc))
        return 2


def push_workspace(*, workspace: str | None = None, branch: str | None = None) -> int:
    try:
        workspace_root = managed_workspace_root(workspace)
        if branch is None:
            raise ValueError("--branch is required for repo push")
        branch = validate_branch_name(branch)
        git.push_branch(workspace_root, branch)
        print(f"pushed: workspace={workspace_root} target=origin/{branch}")
        return 0
    except ValueError as exc:
        _hint(str(exc))
        return 1
    except (git.GitError, OSError) as exc:
        _hint(str(exc))
        return 2


def clean_workspace(*, workspace: str | None = None) -> int:
    try:
        workspace_root = managed_workspace_root(workspace)
        _clean_root(workspace_root)
        print(f"cleaned: workspace={workspace_root}")
        return 0
    except ValueError as exc:
        _hint(str(exc))
        return 1
    except OSError as exc:
        _hint(str(exc))
        return 2
