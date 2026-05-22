"""Unit tests for ``codexd.pidfile``.

All tests monkeypatch ``codexd.pidfile.PID_DIR`` to a per-test
``tmp_path`` so we never touch the real ``~/.culture/pids`` directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codexd import pidfile


@pytest.fixture
def tmp_pid_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect PID_DIR to a tmp directory for the duration of the test."""
    monkeypatch.setattr(pidfile, "PID_DIR", str(tmp_path))
    return tmp_path


# ── _safe_name ───────────────────────────────────────────────────────


def test_safe_name_keeps_valid_chars() -> None:
    assert pidfile._safe_name("spark-server.1_v2") == "spark-server.1_v2"


def test_safe_name_replaces_unsafe_chars() -> None:
    # Path(...).name strips the leading "evil name/" component first.
    assert pidfile._safe_name("evil name/with spaces") == "with_spaces"


def test_safe_name_replaces_special_chars_within_basename() -> None:
    assert pidfile._safe_name("weird@name!") == "weird_name_"


def test_safe_name_strips_path_traversal() -> None:
    # Path(...).name drops the directory components
    assert pidfile._safe_name("../../etc/passwd") == "passwd"


# ── write_pid / read_pid / remove_pid ────────────────────────────────


def test_write_pid_creates_file_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``write_pid`` must create PID_DIR if it doesn't exist yet."""
    nested = tmp_path / "nested-does-not-exist-yet"
    assert not nested.exists()
    monkeypatch.setattr(pidfile, "PID_DIR", str(nested))
    path = pidfile.write_pid("spark", 12345)
    assert path.exists()
    assert path.read_text() == "12345"


def test_read_pid_round_trip(tmp_pid_dir: Path) -> None:
    pidfile.write_pid("alpha", 4242)
    assert pidfile.read_pid("alpha") == 4242


def test_read_pid_missing_returns_none(tmp_pid_dir: Path) -> None:
    assert pidfile.read_pid("ghost") is None


def test_read_pid_corrupt_returns_none(tmp_pid_dir: Path) -> None:
    (tmp_pid_dir / "rotten.pid").write_text("not-a-number")
    assert pidfile.read_pid("rotten") is None


def test_remove_pid_deletes_existing(tmp_pid_dir: Path) -> None:
    pidfile.write_pid("alpha", 1)
    pidfile.remove_pid("alpha")
    assert not (tmp_pid_dir / "alpha.pid").exists()


def test_remove_pid_missing_is_no_op(tmp_pid_dir: Path) -> None:
    # Must not raise FileNotFoundError.
    pidfile.remove_pid("never-existed")


# ── write_port / read_port / remove_port ─────────────────────────────


def test_port_round_trip(tmp_pid_dir: Path) -> None:
    pidfile.write_port("alpha", 6667)
    assert pidfile.read_port("alpha") == 6667
    pidfile.remove_port("alpha")
    assert pidfile.read_port("alpha") is None


def test_read_port_corrupt_returns_none(tmp_pid_dir: Path) -> None:
    (tmp_pid_dir / "rotten.port").write_text("not-a-port")
    assert pidfile.read_port("rotten") is None


def test_remove_port_missing_is_no_op(tmp_pid_dir: Path) -> None:
    pidfile.remove_port("never-existed")


# ── is_process_alive ─────────────────────────────────────────────────


def test_is_process_alive_self() -> None:
    assert pidfile.is_process_alive(os.getpid())


def test_is_process_alive_unlikely_pid() -> None:
    # PID 2^31-1 is essentially never alive (Linux PID_MAX defaults to 4M).
    assert not pidfile.is_process_alive(2**31 - 1)


# ── is_culture_process ───────────────────────────────────────────────


def test_is_culture_process_no_proc(monkeypatch: pytest.MonkeyPatch) -> None:
    """On systems without /proc (e.g. macOS) the function assumes valid."""
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    assert pidfile.is_culture_process(1) is True


def test_is_culture_process_unreadable_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """If /proc/<pid>/cmdline can't be read, fail closed."""
    monkeypatch.setattr(os.path, "isdir", lambda p: True)

    def raise_oserror(_self) -> bytes:
        raise OSError("nope")

    monkeypatch.setattr(Path, "read_bytes", raise_oserror)
    assert pidfile.is_culture_process(1) is False


def test_is_culture_process_self_is_not_culture() -> None:
    """The test runner is `pytest`, not `culture`; should be False on Linux."""
    if not os.path.isdir("/proc"):
        pytest.skip("no /proc on this platform")
    assert pidfile.is_culture_process(os.getpid()) is False


# ── list_servers ─────────────────────────────────────────────────────


def test_list_servers_empty_when_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pidfile, "PID_DIR", str(tmp_path / "absent"))
    assert pidfile.list_servers() == []


def test_list_servers_skips_dead_pids(tmp_pid_dir: Path) -> None:
    """A server-*.pid file pointing at a dead PID is filtered out."""
    pidfile.write_pid("server-deadbeef", 2**31 - 1)
    pidfile.write_port("server-deadbeef", 6667)
    assert pidfile.list_servers() == []


def test_list_servers_skips_when_not_culture(
    tmp_pid_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live PID that is_culture_process flags as non-culture is filtered.

    Monkeypatch ``is_culture_process`` rather than relying on the runner's
    actual argv: on Linux ``is_culture_process(os.getpid())`` returns False
    because /proc/<pid>/cmdline contains "pytest", but on macOS/Windows the
    function returns True ("assume valid" when /proc is absent). The
    behavior under test is "list_servers filters non-culture PIDs",
    independent of OS.
    """
    pidfile.write_pid("server-self", os.getpid())
    pidfile.write_port("server-self", 6667)
    monkeypatch.setattr(pidfile, "is_culture_process", lambda pid: False)
    assert pidfile.list_servers() == []


def test_list_servers_returns_entry_when_culture(
    tmp_pid_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both liveness and is_culture_process pass, the entry is returned."""
    monkeypatch.setattr(pidfile, "is_process_alive", lambda pid: True)
    monkeypatch.setattr(pidfile, "is_culture_process", lambda pid: True)
    pidfile.write_pid("server-spark", 4242)
    pidfile.write_port("server-spark", 6700)
    entries = pidfile.list_servers()
    assert entries == [{"name": "spark", "pid": 4242, "port": 6700}]


def test_list_servers_default_port_when_port_file_missing(
    tmp_pid_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pidfile, "is_process_alive", lambda pid: True)
    monkeypatch.setattr(pidfile, "is_culture_process", lambda pid: True)
    pidfile.write_pid("server-spark", 4242)
    entries = pidfile.list_servers()
    assert entries == [{"name": "spark", "pid": 4242, "port": 6667}]


# ── default_server ───────────────────────────────────────────────────


def test_default_server_round_trip(tmp_pid_dir: Path) -> None:
    assert pidfile.read_default_server() is None
    pidfile.write_default_server("spark")
    assert pidfile.read_default_server() == "spark"


def test_default_server_empty_returns_none(tmp_pid_dir: Path) -> None:
    (tmp_pid_dir / "default_server").write_text("   ")
    assert pidfile.read_default_server() is None


# ── rename_pid ───────────────────────────────────────────────────────


def test_rename_pid_moves_both_files(tmp_pid_dir: Path) -> None:
    pidfile.write_pid("old", 1)
    pidfile.write_port("old", 2)
    assert pidfile.rename_pid("old", "new") is True
    assert pidfile.read_pid("new") == 1
    assert pidfile.read_port("new") == 2
    assert pidfile.read_pid("old") is None


def test_rename_pid_no_files_returns_false(tmp_pid_dir: Path) -> None:
    assert pidfile.rename_pid("ghost", "still-ghost") is False
