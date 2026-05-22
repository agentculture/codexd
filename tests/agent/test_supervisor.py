"""Codex supervisor behavior."""

from __future__ import annotations

import pytest

from codexd.agent.supervisor import CodexSupervisor
from codexd.harness.supervisor import SupervisorVerdict


@pytest.mark.asyncio
async def test_supervisor_dispatches_correction_whisper() -> None:
    whispers: list[tuple[str, str]] = []

    async def on_whisper(message: str, kind: str) -> None:
        whispers.append((message, kind))

    supervisor = CodexSupervisor(eval_interval=1, on_whisper=on_whisper)

    await supervisor._process_verdict(SupervisorVerdict(action="CORRECTION", message="focus"))

    assert whispers == [("focus", "CORRECTION")]
