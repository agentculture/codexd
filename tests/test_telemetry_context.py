"""Unit tests for ``codexd.telemetry.context``."""

from __future__ import annotations

from opentelemetry.context import attach, detach
from opentelemetry.trace import get_current_span

import codexd.telemetry as telemetry
from codexd.protocol.message import Message
from codexd.telemetry import context

VALID_TP = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def _message_with_tags(tags: dict[str, str]) -> Message:
    return Message(command="PRIVMSG", params=["#c", "hello"], tags=tags)


def test_extract_traceparent_missing() -> None:
    result = context.extract_traceparent_from_tags(_message_with_tags({}), peer="peer-a")
    assert result == context.ExtractResult(
        status="missing", traceparent=None, tracestate=None, peer="peer-a"
    )


def test_extract_traceparent_valid_with_tracestate() -> None:
    result = context.extract_traceparent_from_tags(
        _message_with_tags(
            {
                context.TRACEPARENT_TAG: VALID_TP,
                context.TRACESTATE_TAG: "vendor=value",
            }
        ),
        peer="peer-a",
    )
    assert result.status == "valid"
    assert result.traceparent == VALID_TP
    assert result.tracestate == "vendor=value"
    assert result.peer == "peer-a"


def test_extract_traceparent_drops_oversized_tracestate() -> None:
    result = context.extract_traceparent_from_tags(
        _message_with_tags(
            {
                context.TRACEPARENT_TAG: VALID_TP,
                context.TRACESTATE_TAG: "x" * 513,
            }
        ),
        peer=None,
    )
    assert result.status == "valid"
    assert result.tracestate is None


def test_extract_traceparent_rejects_malformed_values() -> None:
    result = context.extract_traceparent_from_tags(
        _message_with_tags({context.TRACEPARENT_TAG: VALID_TP.upper()}),
        peer=None,
    )
    assert result.status == "malformed"
    assert result.traceparent is None


def test_extract_traceparent_rejects_too_long_values() -> None:
    result = context.extract_traceparent_from_tags(
        _message_with_tags({context.TRACEPARENT_TAG: f"{VALID_TP}00"}),
        peer="peer-a",
    )
    assert result.status == "too_long"
    assert result.peer == "peer-a"


def test_inject_traceparent_sets_and_removes_tracestate() -> None:
    msg = _message_with_tags({context.TRACESTATE_TAG: "stale"})
    context.inject_traceparent(msg, VALID_TP, "vendor=value")
    assert msg.tags[context.TRACEPARENT_TAG] == VALID_TP
    assert msg.tags[context.TRACESTATE_TAG] == "vendor=value"

    context.inject_traceparent(msg, VALID_TP, None)
    assert msg.tags[context.TRACEPARENT_TAG] == VALID_TP
    assert context.TRACESTATE_TAG not in msg.tags


def test_context_from_traceparent_builds_remote_span_context() -> None:
    ctx = context.context_from_traceparent(VALID_TP)
    span_context = get_current_span(ctx).get_span_context()
    assert span_context.trace_id == int("4bf92f3577b34da6a3ce929d0e0e4736", 16)
    assert span_context.span_id == int("00f067aa0ba902b7", 16)
    assert span_context.is_remote is True


def test_current_traceparent_uses_active_context() -> None:
    token = attach(context.context_from_traceparent(VALID_TP))
    try:
        assert context.current_traceparent() == VALID_TP
    finally:
        detach(token)


def test_public_telemetry_exports_context_helpers() -> None:
    assert telemetry.TRACEPARENT_TAG == context.TRACEPARENT_TAG
    assert telemetry.extract_traceparent_from_tags is context.extract_traceparent_from_tags


def test_current_traceparent_returns_none_without_active_span() -> None:
    assert context.current_traceparent() is None
