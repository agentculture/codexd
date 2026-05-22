"""Unit tests for ``codexd.telemetry.audit``.

Covers the public AuditSink lifecycle, init_audit caching, the record
builder, the rotation logic, and the queue-overflow / submit-before-start
error branches. Uses real asyncio (no SDK mocks; the sink writes to a
``tmp_path`` audit_dir).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agentirc.config import ServerConfig, TelemetryConfig
from agentirc.protocol import Event, EventType

from codexd.telemetry import audit


def _stub_metrics() -> SimpleNamespace:
    """Return a MetricsRegistry-shaped namespace with MagicMock instruments."""
    return SimpleNamespace(
        audit_writes=MagicMock(),
        audit_queue_depth=MagicMock(),
    )


@pytest.fixture(autouse=True)
def _reset_audit_module() -> None:
    audit.reset_for_tests()
    yield
    audit.reset_for_tests()


# ── utc_iso_timestamp ────────────────────────────────────────────────


def test_utc_iso_timestamp_format() -> None:
    ts = audit.utc_iso_timestamp(0)
    assert ts == "1970-01-01T00:00:00.000000Z"


def test_utc_iso_timestamp_microsecond_precision() -> None:
    ts = audit.utc_iso_timestamp(1.123456)
    assert ts.endswith("123456Z")


def test_utc_iso_timestamp_backcompat_alias() -> None:
    """The private alias must point to the same function."""
    assert audit._utc_iso_timestamp is audit.utc_iso_timestamp


# ── _target_for ──────────────────────────────────────────────────────


def test_target_for_channel() -> None:
    e = Event(type=EventType.JOIN, channel="#general", nick="alice")
    assert audit._target_for(e) == {"kind": "channel", "name": "#general"}


def test_target_for_dm_nick() -> None:
    e = Event(type="user.privmsg", channel=None, nick="alice", data={"target": "bob"})
    assert audit._target_for(e) == {"kind": "nick", "name": "bob"}


def test_target_for_empty() -> None:
    e = Event(type=EventType.JOIN, channel=None, nick="alice")
    assert audit._target_for(e) == {"kind": "", "name": ""}


# ── build_audit_record ───────────────────────────────────────────────


def test_build_audit_record_local_origin() -> None:
    e = Event(
        type=EventType.JOIN,
        channel="#c",
        nick="alice",
        data={"role": "host"},
        timestamp=0.0,
    )
    rec = audit.build_audit_record(
        server_name="culture",
        event=e,
        origin_tag=None,
        trace_id="tid",
        span_id="sid",
    )
    assert rec["server"] == "culture"
    assert rec["event_type"] == "user.join"
    assert rec["origin"] == "local"
    assert rec["peer"] == ""
    assert rec["trace_id"] == "tid"
    assert rec["actor"] == {"nick": "alice", "kind": "human", "remote_addr": ""}
    assert rec["target"] == {"kind": "channel", "name": "#c"}
    # nick + channel auto-populated into payload defaults
    assert rec["payload"]["nick"] == "alice"
    assert rec["payload"]["channel"] == "#c"
    assert rec["payload"]["role"] == "host"
    assert rec["tags"] == {}


def test_build_audit_record_federated_origin_strips_underscored() -> None:
    e = Event(
        type="user.privmsg",
        channel="#c",
        nick="alice",
        data={"_internal": "drop", "msg": "keep"},
        timestamp=0.0,
    )
    rec = audit.build_audit_record(
        server_name="culture",
        event=e,
        origin_tag="peer-spark",
        trace_id="tid",
        span_id="sid",
        actor_kind="bot",
        actor_remote_addr="10.0.0.1",
        extra_tags={"src": "ircd"},
    )
    assert rec["origin"] == "federated"
    assert rec["peer"] == "peer-spark"
    assert rec["actor"]["kind"] == "bot"
    assert rec["actor"]["remote_addr"] == "10.0.0.1"
    assert "_internal" not in rec["payload"]
    assert rec["payload"]["msg"] == "keep"
    assert rec["tags"] == {"src": "ircd"}


def test_build_audit_record_event_type_as_string() -> None:
    """Raw string event types (federation peer) must serialize verbatim."""
    e = Event(type="custom.kind", channel=None, nick="", timestamp=0.0)
    rec = audit.build_audit_record(
        server_name="culture", event=e, origin_tag=None, trace_id="t", span_id="s"
    )
    assert rec["event_type"] == "custom.kind"


# ── AuditSink — disabled behaviour ───────────────────────────────────


def test_submit_when_disabled_is_no_op(tmp_path: Path) -> None:
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=False,
        metrics=_stub_metrics(),
    )
    sink.submit({"a": 1})  # must not raise
    # No queue object ever allocated.
    assert sink.queue is None


def test_submit_before_start_drops_and_counts(tmp_path: Path) -> None:
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )
    sink.submit({"a": 1})  # queue is None — should drop + count error
    metrics.audit_writes.add.assert_called_with(1, {"outcome": "error"})


# ── AuditSink — start / submit / shutdown happy path ─────────────────


def test_sink_lifecycle_writes_jsonl(tmp_path: Path) -> None:
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="culture",
        audit_dir=tmp_path,
        max_file_bytes=10_000,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )

    async def run() -> None:
        await sink.start()
        sink.submit({"hello": "world"})
        sink.submit({"second": True})
        await sink.shutdown(drain_timeout=2.0)

    asyncio.run(run())

    # Exactly one file was created; both records are present.
    files = list(tmp_path.glob("culture-*.jsonl"))
    assert len(files) == 1
    lines = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert lines == [{"hello": "world"}, {"second": True}]
    # File permissions are 0600.
    assert (files[0].stat().st_mode & 0o777) == 0o600


def test_sink_start_is_idempotent(tmp_path: Path) -> None:
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )

    async def run() -> None:
        await sink.start()
        first_task = sink._writer_task
        await sink.start()  # second call returns immediately
        assert sink._writer_task is first_task
        await sink.shutdown(drain_timeout=1.0)

    asyncio.run(run())


def test_sink_shutdown_disabled_is_no_op(tmp_path: Path) -> None:
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=False,
        metrics=_stub_metrics(),
    )
    asyncio.run(sink.shutdown())  # must not raise


# ── AuditSink — rotation paths ───────────────────────────────────────


def test_sink_rotates_when_size_cap_exceeded(tmp_path: Path) -> None:
    """A second record that would exceed max_file_bytes rolls to a .1 suffix.

    ``rotate_utc_midnight=False`` so a test that straddles UTC midnight
    can't get its suffix reset to 0 mid-flight (Qodo PR #21 review).
    """
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="culture",
        audit_dir=tmp_path,
        max_file_bytes=30,  # small cap so the second record rolls
        rotate_utc_midnight=False,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )

    async def run() -> None:
        await sink.start()
        sink.submit({"long_record": "abcdefghijklmnop"})  # > 30 bytes when JSONified
        sink.submit({"second": "xyz"})
        await sink.shutdown(drain_timeout=2.0)

    asyncio.run(run())

    files = sorted(tmp_path.glob("culture-*.jsonl"))
    # First file at default suffix; second at .1
    assert len(files) >= 2
    assert any(".1.jsonl" in f.name for f in files)


def test_sink_picks_next_slot_when_existing_file_already_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a sibling slot is already at the cap, _pick_rotation_path bumps.

    Monkeypatches ``audit.datetime`` so the test and the writer agree on
    "today" — without this, an execution that straddles UTC midnight
    between the pre-create step and the writer's first rotation decision
    would put the existing file under yesterday's slot (Qodo PR #21).
    """
    import datetime as real_datetime

    fixed_now = real_datetime.datetime(2026, 5, 12, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    class FrozenDatetime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed_now

    monkeypatch.setattr(audit, "datetime", FrozenDatetime)

    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="culture",
        audit_dir=tmp_path,
        max_file_bytes=10,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )

    today = fixed_now.strftime("%Y-%m-%d")
    existing = tmp_path / f"culture-{today}.jsonl"
    existing.write_bytes(b"X" * 100)  # well over the cap

    async def run() -> None:
        await sink.start()
        sink.submit({"a": 1})
        await sink.shutdown(drain_timeout=2.0)

    asyncio.run(run())

    files = sorted(tmp_path.glob("culture-*.jsonl"))
    # The pre-existing file is untouched; new write went to a higher-suffix slot.
    assert any(".1.jsonl" in f.name or ".2.jsonl" in f.name for f in files)


# ── init_audit ───────────────────────────────────────────────────────


def test_init_audit_constructs_sink(tmp_path: Path) -> None:
    cfg = ServerConfig(
        name="culture",
        telemetry=TelemetryConfig(audit_dir=str(tmp_path), audit_enabled=True),
    )
    sink = audit.init_audit(cfg, _stub_metrics())
    assert isinstance(sink, audit.AuditSink)
    assert sink.server_name == "culture"
    assert sink.enabled is True


def test_init_audit_is_idempotent(tmp_path: Path) -> None:
    cfg = ServerConfig(
        name="culture",
        telemetry=TelemetryConfig(audit_dir=str(tmp_path)),
    )
    a = audit.init_audit(cfg, _stub_metrics())
    b = audit.init_audit(cfg, _stub_metrics())
    assert a is b


def test_init_audit_reinit_warns_when_prev_running(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Reinit with mutated config + running writer task logs a warning."""
    cfg = ServerConfig(
        name="culture",
        telemetry=TelemetryConfig(audit_dir=str(tmp_path), audit_enabled=True),
    )
    sink = audit.init_audit(cfg, _stub_metrics())

    # Simulate that the previous sink has a running task.
    sink._writer_task = MagicMock()

    cfg.telemetry.audit_max_file_bytes = 9999  # mutate to force reinit
    with caplog.at_level("WARNING", logger="codexd.telemetry.audit"):
        audit.init_audit(cfg, _stub_metrics())

    assert any("previous sink is still running" in r.message for r in caplog.records)


# ── _write_all (private helper, exercised once for coverage) ─────────


def test_write_all_writes_full_buffer(tmp_path: Path) -> None:
    """`_write_all` must loop until every byte is written."""
    target = tmp_path / "out.bin"
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        written = audit._write_all(fd, b"hello world")
    finally:
        os.close(fd)
    assert written == 11
    assert target.read_bytes() == b"hello world"


def test_write_all_raises_on_zero_return(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pathological os.write returning 0 must surface as OSError, not spin."""

    def stub_write(fd: int, buf) -> int:
        return 0

    monkeypatch.setattr(os, "write", stub_write)
    with pytest.raises(OSError, match="refusing to spin"):
        audit._write_all(99, b"data")


def test_submit_queue_full_drops_and_counts(tmp_path: Path) -> None:
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=1,
        enabled=True,
        metrics=metrics,
    )
    sink.queue = asyncio.Queue(maxsize=1)
    sink.queue.put_nowait({"queued": True})

    sink.submit({"dropped": True})

    metrics.audit_writes.add.assert_called_with(1, {"outcome": "error"})


def test_sink_start_disabled_is_no_op(tmp_path: Path) -> None:
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=False,
        metrics=_stub_metrics(),
    )

    asyncio.run(sink.start())

    assert sink.queue is None
    assert sink._writer_task is None


def test_sink_shutdown_timeout_cancels_task_and_closes_fd(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )

    async def run() -> None:
        async def sleeper() -> None:
            await asyncio.Event().wait()

        sink.queue = asyncio.Queue()
        await sink.queue.put({"never": "task_done"})
        sink._writer_task = asyncio.create_task(sleeper())
        sink._current_fd = os.open(str(tmp_path / "held.jsonl"), os.O_WRONLY | os.O_CREAT, 0o600)
        with caplog.at_level("WARNING", logger="codexd.telemetry.audit"):
            await sink.shutdown(drain_timeout=0.001)

    asyncio.run(run())

    assert sink._writer_task is None
    assert sink._current_fd == -1
    assert any("audit drain timed out" in r.message for r in caplog.records)


def test_writer_loop_without_queue_logs_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=_stub_metrics(),
    )

    async def run() -> None:
        with caplog.at_level("ERROR", logger="codexd.telemetry.audit"):
            await sink._writer_loop()

    asyncio.run(run())

    assert any("writer task started without a queue" in r.message for r in caplog.records)


def test_writer_loop_counts_open_failure_as_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )

    def fail_open(path: Path) -> int:
        raise OSError("nope")

    monkeypatch.setattr(sink, "_open_audit_file", fail_open)

    async def run() -> None:
        sink.queue = asyncio.Queue()
        task = asyncio.create_task(sink._writer_loop())
        await sink.queue.put({"ok": True})
        await asyncio.wait_for(sink.queue.join(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    metrics.audit_writes.add.assert_called_with(1, {"outcome": "error"})


def test_writer_loop_counts_write_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )
    sink._current_fd = 99
    monkeypatch.setattr(sink, "_maybe_rotate", lambda next_record_bytes: None)

    def fail_write(fd: int, buf: bytes) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(audit, "_write_all", fail_write)

    async def run() -> None:
        sink.queue = asyncio.Queue()
        task = asyncio.create_task(sink._writer_loop())
        await sink.queue.put({"ok": True})
        await asyncio.wait_for(sink.queue.join(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    metrics.audit_writes.add.assert_called_with(1, {"outcome": "error"})


def test_writer_loop_counts_serialization_error(tmp_path: Path) -> None:
    metrics = _stub_metrics()
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=metrics,
    )

    async def run() -> None:
        sink.queue = asyncio.Queue()
        task = asyncio.create_task(sink._writer_loop())
        await sink.queue.put({"bad": object()})
        await asyncio.wait_for(sink.queue.join(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    metrics.audit_writes.add.assert_called_with(1, {"outcome": "error"})


def test_pick_rotation_path_handles_stat_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=_stub_metrics(),
    )
    calls = 0

    def fake_exists(self: Path) -> bool:
        return True

    def fake_stat(self: Path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(st_size=10)
        raise OSError("stat failed")

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "stat", fake_stat)

    path, suffix, existing_size = sink._pick_rotation_path("2026-05-22")

    assert path.name == "x-2026-05-22.1.jsonl"
    assert suffix == 1
    assert existing_size == 0


def test_maybe_rotate_open_failure_keeps_old_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=_stub_metrics(),
    )
    sink._current_fd = 99

    def fail_open(path: Path) -> int:
        raise OSError("cannot open")

    monkeypatch.setattr(sink, "_open_audit_file", fail_open)

    sink._maybe_rotate(10)

    assert sink._current_fd == 99


def test_maybe_rotate_ignores_old_fd_close_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=_stub_metrics(),
    )
    sink._current_fd = 99

    def fake_open(path: Path) -> int:
        return 100

    def fail_close(fd: int) -> None:
        raise OSError("close failed")

    monkeypatch.setattr(sink, "_open_audit_file", fake_open)
    monkeypatch.setattr(os, "close", fail_close)

    sink._maybe_rotate(10)

    assert sink._current_fd == 100


def test_reset_for_tests_warns_when_sink_running(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sink = audit.AuditSink(
        server_name="x",
        audit_dir=tmp_path,
        max_file_bytes=1024,
        rotate_utc_midnight=True,
        queue_depth=10,
        enabled=True,
        metrics=_stub_metrics(),
    )
    sink._writer_task = MagicMock()
    audit._sink = sink

    with caplog.at_level("WARNING", logger="codexd.telemetry.audit"):
        audit.reset_for_tests()

    assert any(
        "reset_for_tests called while sink writer task still running" in r.message
        for r in caplog.records
    )
