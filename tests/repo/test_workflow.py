"""End-to-end repo workflow tests without a real Codex process."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

from codexd.repo.workflow import RepoRunResult, run_repo_task


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=path, text=True, capture_output=True, check=True)


def _seed_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    _git(seed, "config", "user.email", "codexd@example.invalid")
    _git(seed, "config", "user.name", "codexd test")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", "origin", "HEAD:main")
    return origin


def test_repo_run_clones_runs_commits_and_pushes(tmp_path, monkeypatch, capsys) -> None:
    origin = _seed_origin(tmp_path)
    monkeypatch.chdir(tmp_path)

    async def fake_turn(runner, task: str) -> None:
        checkout = Path(runner.directory)
        (checkout / "result.txt").write_text(task + "\n", encoding="utf-8")

    with patch("codexd.repo.workflow.run_app_server_turn", new=AsyncMock(side_effect=fake_turn)):
        rc = run_repo_task(str(origin), branch="codex/result", task="write result", workspace=".codexd/work")

    assert rc == 0
    pushed = subprocess.run(
        ["git", "--git-dir", str(origin), "show-ref", "refs/heads/codex/result"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "refs/heads/codex/result" in pushed.stdout
    assert "pushed" in capsys.readouterr().out


def test_repo_run_no_changes_does_not_push(tmp_path, monkeypatch, capsys) -> None:
    origin = _seed_origin(tmp_path)
    monkeypatch.chdir(tmp_path)

    with patch("codexd.repo.workflow.run_app_server_turn", new=AsyncMock(return_value=None)):
        rc = run_repo_task(str(origin), branch="codex/noop", task="do nothing", workspace=".codexd/work")

    assert rc == 0
    refs = subprocess.run(
        ["git", "--git-dir", str(origin), "show-ref", "refs/heads/codex/noop"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert refs.returncode != 0
    assert "no changes" in capsys.readouterr().out
