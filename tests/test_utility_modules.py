"""Unit tests for small migrated utility modules."""

from __future__ import annotations

import pytest

from codexd import _constants, aio, constants


def test_default_turn_timeout_is_positive_float() -> None:
    assert _constants.DEFAULT_TURN_TIMEOUT_SECONDS == 600.0


def test_system_constants_and_event_pattern() -> None:
    assert constants.SYSTEM_USER_PREFIX == "system-"
    assert constants.SYSTEM_CHANNEL == "#system"
    assert constants.SYSTEM_USER_REALNAME == "Culture system messages"
    assert constants.EVENT_TAG_TYPE == "event"
    assert constants.EVENT_TAG_DATA == "event-data"
    assert constants.EVENT_TYPE_RE.fullmatch("user.join")
    assert constants.EVENT_TYPE_RE.fullmatch("agent.task-done")
    assert constants.EVENT_TYPE_RE.fullmatch("agent.task_done")
    assert not constants.EVENT_TYPE_RE.fullmatch("join")
    assert not constants.EVENT_TYPE_RE.fullmatch("User.Join")


@pytest.mark.asyncio
async def test_maybe_await_returns_plain_values() -> None:
    assert await aio.maybe_await("ready") == "ready"


@pytest.mark.asyncio
async def test_maybe_await_awaits_coroutines() -> None:
    async def _value() -> str:
        return "done"

    assert await aio.maybe_await(_value()) == "done"
