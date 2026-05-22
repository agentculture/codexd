"""Queued-routing variant of ``BaseDaemon``.

Used by codex / copilot / acp backends — they all share a FIFO mention
queue topology (claude doesn't, hence the split). Each ``@mention``
enqueues a relay target onto ``_mention_targets``; each agent response
pops the next target and sends the response there.

The shared implementations of mention/poll/status/roominvite live in
``BaseDaemon`` as template methods. This subclass overrides the four
queue-shape hooks (``_enqueue_relay_target_for_mention``,
``_enqueue_relay_target_for_poll``, ``_pre_status_query``,
``_pre_roominvite_send``) plus the queue-only methods
(``_handle_agent_message_pre_supervisor``, ``_relay_response_to_irc``,
``_send_relay_lines``, ``_on_turn_error``).
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from codexd.harness.base_daemon import AlertEvent, BaseDaemon

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_TURN_FAILURES = 3


class QueuedBaseDaemon(BaseDaemon):
    """BaseDaemon + FIFO mention-queue routing."""

    def __init__(
        self,
        config: Any,
        agent: Any,
        socket_dir: str | None = None,
        skip_agent: bool = False,
    ) -> None:
        super().__init__(config, agent, socket_dir=socket_dir, skip_agent=skip_agent)
        # FIFO queue of relay targets — each @mention enqueues a target,
        # each agent response dequeues one, ensuring correct routing even
        # when multiple mentions arrive while the agent is busy.
        self._mention_targets: deque = deque()
        self._consecutive_turn_failures: int = 0

    # ------------------------------------------------------------------
    # BaseDaemon hook overrides — register relay targets on the queue
    # ------------------------------------------------------------------

    def _enqueue_relay_target_for_mention(self, target: str, sender: str) -> None:
        # FIFO matches prompt queue order: channel target if mention is in a
        # channel, otherwise sender (DM).
        self._mention_targets.append(target if target.startswith("#") else sender)

    def _enqueue_relay_target_for_poll(self, channel: str) -> None:
        self._mention_targets.append(channel)

    def _pre_status_query(self) -> None:
        # Enqueue None so the status-query response doesn't steal a real
        # mention's relay target.
        self._mention_targets.append(None)

    def _pre_roominvite_send(self) -> None:
        # Enqueue None so the roominvite-evaluation response doesn't steal a
        # real mention's relay target.
        self._mention_targets.append(None)

    async def _handle_agent_message_pre_supervisor(self, msg: dict) -> None:
        """Relay agent text to IRC and reset the turn-failure counter."""
        self._consecutive_turn_failures = 0
        await self._relay_response_to_irc(msg)

    # ------------------------------------------------------------------
    # Turn-error handling (queue-only)
    # ------------------------------------------------------------------

    async def _on_turn_error(self) -> None:
        """Send error feedback to IRC and clean up stale relay target."""
        if self._mention_targets:
            relay_target = self._mention_targets.popleft()
            if self._transport and relay_target:
                await self._transport.send_privmsg(
                    relay_target,
                    "Sorry, I encountered an error processing your request.",
                )
        self._consecutive_turn_failures += 1
        if self._consecutive_turn_failures >= MAX_CONSECUTIVE_TURN_FAILURES:
            self._paused = True
            self._manually_paused = True
            logger.error(
                "Agent %s paused after %d consecutive turn failures",
                self.agent.nick,
                self._consecutive_turn_failures,
            )
            if self._webhook:
                await self._webhook.fire(
                    AlertEvent(
                        event_type="agent_spiraling",
                        nick=self.agent.nick,
                        message=(
                            f"Agent {self.agent.nick} paused after "
                            f"{self._consecutive_turn_failures} consecutive turn failures."
                        ),
                    )
                )

    # ------------------------------------------------------------------
    # Relay (queue-only — claude has no equivalent)
    # ------------------------------------------------------------------

    async def _relay_response_to_irc(self, msg: dict) -> None:
        """Dequeue the next relay target and send agent text lines to IRC."""
        relay_target = self._mention_targets.popleft() if self._mention_targets else None
        if self._transport and relay_target:
            content = msg.get("content", [])
            await self._send_relay_lines(relay_target, content)

    async def _send_relay_lines(self, relay_target: str, content: list) -> None:
        """Send each text content item line-by-line to the relay target.

        Default: copilot/acp shape (inline strip + filter empty lines).
        Codex overrides this to use ``_clean_relay_lines`` (its meta-stripping
        helper).
        """
        for item in content:
            if item.get("type") != "text":
                continue
            text = item["text"].strip()
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    await self._transport.send_privmsg(relay_target, line)
