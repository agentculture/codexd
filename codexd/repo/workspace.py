"""Managed workspace validation for repo commands."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_WORKSPACE = Path(".codexd") / "work"
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SSH_REMOTE_RE = re.compile(r"^git@[A-Za-z0-9._-]+:[A-Za-z0-9._/-]+(?:\.git)?$")


def managed_workspace_root(workspace: str | None, *, repo_root: Path | None = None) -> Path:
    root = (repo_root or Path.cwd()).resolve()
    candidate = Path(workspace) if workspace else DEFAULT_WORKSPACE
    return validate_workspace_path(candidate, repo_root=root)


def validate_workspace_path(path: Path, *, repo_root: Path) -> Path:
    candidate = path if path.is_absolute() else repo_root / path
    candidate = candidate.resolve()
    repo_root = repo_root.resolve()

    if candidate == repo_root:
        raise ValueError("workspace must not be the repository root")
    if candidate == Path.home().resolve():
        raise ValueError("workspace must not be the user's home directory")
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("workspace must be inside the current repository") from exc
    return candidate


def validate_branch_name(branch: str) -> str:
    if not branch or branch.strip() != branch:
        raise ValueError("branch name must be non-empty and trimmed")
    if ".." in branch or branch.startswith("/") or branch.endswith("/"):
        raise ValueError(f"unsafe branch name: {branch!r}")
    if not _BRANCH_RE.match(branch):
        raise ValueError(f"unsafe branch name: {branch!r}")
    return branch


def validate_remote(remote: str) -> str:
    parsed = urlparse(remote)
    if parsed.scheme == "https" and parsed.netloc and parsed.path:
        return remote
    if _SSH_REMOTE_RE.match(remote):
        return remote
    local = Path(remote)
    if local.is_absolute() and local.exists():
        return remote
    raise ValueError("remote must be an HTTPS or SSH Git remote")


def derive_checkout_name(remote: str) -> str:
    raw = remote.rstrip("/").split("/")[-1]
    if ":" in raw:
        raw = raw.split(":")[-1]
    if raw.endswith(".git"):
        raw = raw[:-4]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-_").lower()
    if not safe:
        raise ValueError("remote did not contain a usable repository name")
    return safe
