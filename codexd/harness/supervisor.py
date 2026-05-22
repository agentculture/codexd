"""Shared supervisor primitives.

Hosts the SDK-shape pieces that claude/acp share byte-for-byte:

- ``SupervisorVerdict`` dataclass + parse() — used by all four backends.
  Codex/copilot's previous variant (which preserved a trailing message
  after overriding an unknown action to OK) is unified to the claude/acp
  behavior here, matching ``tests/test_supervisor.py:32``.
- ``Supervisor`` class — deque-windowed observer with injected
  ``EvaluateFn``. Used by claude/acp directly; codex/copilot use their
  own subprocess-based supervisor classes (no shared base because their
  ``__init__`` shape differs materially).
- ``_format_window`` helper — formats turns into a supervisor prompt.

This module imports no backend SDKs; every backend can import it without
adding optional-dependency drag.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class SupervisorVerdict:
    action: str  # OK, CORRECTION, THINK_DEEPER, ESCALATION
    message: str

    @classmethod
    def parse(cls, text: str) -> SupervisorVerdict:
        text = text.strip()
        if not text or text == "OK":
            return cls(action="OK", message="")
        # split(None, 1) splits on any run of whitespace (space, tab, newline)
        # so verdicts like "CORRECTION\tmessage" or "ESCALATION\nreason" still
        # parse correctly. Codex/copilot's pre-refactor parse used the same
        # splitter; matching that here preserves their robustness.
        parts = text.split(None, 1)
        action = parts[0]
        if action not in ("OK", "CORRECTION", "THINK_DEEPER", "ESCALATION"):
            logger.warning("Unknown supervisor verdict %r, defaulting to OK", action)
            return cls(action="OK", message="")
        message = parts[1] if len(parts) > 1 else ""
        return cls(action=action, message=message)


EvaluateFn = Callable[[list[dict[str, Any]], str], Awaitable[SupervisorVerdict]]


class Supervisor:
    def __init__(
        self,
        window_size: int,
        eval_interval: int,
        escalation_threshold: int,
        evaluate_fn: EvaluateFn,
        on_whisper: Callable[[str, str], Awaitable[None]] | None,
        on_escalation: Callable[[str], Awaitable[None]] | None,
        task_description: str = "",
    ):
        if eval_interval <= 0:
            raise ValueError(
                f"eval_interval must be > 0, got {eval_interval!r} "
                "(observe() modulos by this value every turn)"
            )
        if window_size <= 0:
            raise ValueError(f"window_size must be > 0, got {window_size!r}")
        self.window_size = window_size
        self.eval_interval = eval_interval
        self.escalation_threshold = escalation_threshold
        self.evaluate_fn = evaluate_fn
        self.on_whisper = on_whisper
        self.on_escalation = on_escalation
        self.task_description = task_description
        self._window: deque[dict[str, Any]] = deque(maxlen=window_size)
        self._turn_count: int = 0
        self._consecutive_failures: int = 0
        self.paused: bool = False

    async def observe(self, turn: dict[str, Any]) -> None:
        self._window.append(turn)
        self._turn_count += 1
        if self._turn_count % self.eval_interval == 0:
            await self._evaluate()

    async def _evaluate(self) -> None:
        if self.paused:
            return
        try:
            verdict = await self.evaluate_fn(list(self._window), self.task_description)
        except Exception:
            logger.exception("Supervisor evaluation failed")
            return
        if verdict.action == "OK":
            self._consecutive_failures = 0
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.escalation_threshold:
            self.paused = True
            if self.on_escalation:
                await self.on_escalation(verdict.message)
        else:
            if self.on_whisper:
                await self.on_whisper(verdict.message, verdict.action)


def _format_window(window: list[dict[str, Any]], task: str) -> str:
    """Format the rolling window into a prompt for the supervisor."""
    lines = [f"Task: {task}" if task else "Task: (none provided)"]
    lines.append(f"\nRecent agent activity ({len(window)} turns):\n")
    for i, turn in enumerate(window, 1):
        turn_type = turn.get("type", "unknown")
        content = turn.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, default=str)
        lines.append(f"Turn {i} [{turn_type}]: {content}")
    lines.append("\nEvaluate the agent's productivity. Respond with your verdict.")
    return "\n".join(lines)
