"""Shared base for the four backend daemons.

Hosts the universal-shared surface — methods that are byte-identical across
all four per-backend daemons (claude/codex/copilot/acp). Per-backend
subclasses provide the lifecycle wiring (``__init__``, ``start``, ``stop``,
``_start_agent_runner``, ``_handle_roominvite``) and any backend-specific
overrides.

Two architectural shapes coexist for mention routing:

- **claude**: synchronous routing — ``_on_mention`` builds the prompt and
  dispatches it directly to the agent runner.
- **codex / copilot / acp**: FIFO queue routing — ``_on_mention`` enqueues
  to ``_mention_targets``; the agent later pulls from the queue via
  ``_relay_response_to_irc``.

This module hosts the claude-shape methods. ``QueuedBaseDaemon`` (which
extends this class) overrides the routing methods for the queued shape.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
import stat
import time
from typing import Any

from codexd.aio import maybe_await
from codexd.harness.attention import AttentionTracker, Band
from codexd.harness.ipc import make_response
from codexd.harness.irc_transport import IRCTransport
from codexd.harness.message_buffer import MessageBuffer
from codexd.harness.socket_server import SocketServer
from codexd.harness.telemetry import init_harness_telemetry
from codexd.harness.webhook import AlertEvent, WebhookClient
from codexd.pidfile import remove_pid, write_pid

logger = logging.getLogger(__name__)


def culture_runtime_dir() -> str:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return xdg
    home = os.path.expanduser("~")
    if not home or home == "~" or not os.path.isabs(home):
        raise RuntimeError("culture_runtime_dir(): cannot resolve a home directory")
    fallback = os.path.join(home, ".culture", "run")
    os.makedirs(fallback, mode=0o700, exist_ok=True)
    os.chmod(fallback, stat.S_IRWXU)
    return fallback


MAX_CRASH_COUNT = 3
CRASH_WINDOW_SECONDS = 300
CRASH_RESTART_DELAY = 5

# IPC validation error messages
_ERR_MISSING_CHANNEL = "Missing 'channel'"
_ERR_MISSING_CHANNEL_THREAD = "Missing 'channel' or 'thread'"
_ERR_MISSING_CHANNEL_THREAD_MSG = "Missing 'channel', 'thread', or 'message'"
_ERR_CHANNEL_PREFIX = "Channel name must start with '#'"

# Regex to extract @mentioned nicks from messages
_MENTION_RE = re.compile(r"@([\w-]+)")


class BaseDaemon:
    """Central orchestrator that ties together the IRC transport, socket server,
    agent runner, supervisor, and webhook client for a single agent nick.

    Subclasses MUST set ``BACKEND_NAME`` and implement ``start``, ``stop``,
    ``_start_agent_runner``, ``_handle_roominvite``.
    """

    BACKEND_NAME: str = ""  # subclass override: "claude" / "codex" / "copilot" / "acp"

    def __init__(
        self,
        config: Any,
        agent: Any,
        socket_dir: str | None = None,
        skip_agent: bool = False,
    ) -> None:
        self.config = config
        self.agent = agent
        self.skip_agent = skip_agent

        self._socket_path = os.path.join(
            socket_dir or culture_runtime_dir(),
            f"culture-{agent.nick}.sock",
        )

        self._buffer: MessageBuffer | None = None
        self._transport: IRCTransport | None = None
        self._webhook: WebhookClient | None = None
        self._socket_server: SocketServer | None = None
        self._agent_runner: Any | None = None
        self._supervisor: Any | None = None
        self._tracer: Any = None
        self._metrics: Any = None

        # Crash-recovery state
        self._crash_times: list[float] = []
        self._circuit_open = False

        # Pause/sleep state
        self._paused: bool = False
        self._manually_paused: bool = False
        self._last_activation: float | None = None

        # Status query state — for asking the agent what it's doing
        self._status_query_event: asyncio.Event | None = None
        self._status_query_response: str = ""
        self._last_activity_text: str = ""

        # Attention state — initialized by _init_attention(), called from start()
        self._attention: AttentionTracker | None = None
        self._attention_enabled: bool = False
        self._last_engaged_at: dict[str, float] = {}

        # Background tasks (prevent GC of fire-and-forget tasks)
        self._background_tasks: set[asyncio.Task] = set()

        # Graceful shutdown
        self._stop_event: asyncio.Event | None = None
        self._pid_name: str = ""

        # IPC dispatch table — maps message type → bound handler method
        self._ipc_dispatch: dict = {
            "irc_send": self._ipc_irc_send,
            "irc_read": self._ipc_irc_read,
            "irc_join": self._ipc_irc_join,
            "irc_part": self._ipc_irc_part,
            "irc_channels": self._ipc_irc_channels,
            "irc_who": self._ipc_irc_who,
            "irc_topic": self._ipc_irc_topic,
            "irc_ask": self._ipc_irc_ask,
            "compact": self._ipc_compact,
            "clear": self._ipc_clear,
            "status": self._ipc_status,
            "pause": self._ipc_pause,
            "resume": self._ipc_resume,
            "irc_thread_create": self._ipc_irc_thread_create,
            "irc_thread_reply": self._ipc_irc_thread_reply,
            "irc_threads": self._ipc_irc_threads,
            "irc_thread_close": self._ipc_irc_thread_close,
            "irc_thread_read": self._ipc_irc_thread_read,
            "shutdown": self._ipc_shutdown,
        }

    # ------------------------------------------------------------------
    # Lifecycle (template-method shape)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start all components in dependency order.

        Template method — subclasses implement the abstract hooks
        (``_create_supervisor``, ``_start_agent_runner``) and may override
        ``_on_start_agent_runner_failure`` for backend-specific recovery.
        """
        self._pid_name = f"agent-{self.agent.nick}"
        write_pid(self._pid_name, os.getpid())

        self._tracer, self._metrics = init_harness_telemetry(self.config)

        self._buffer = MessageBuffer(max_per_channel=self.config.buffer_size)

        self._transport = IRCTransport(
            host=self.config.server.host,
            port=self.config.server.port,
            nick=self.agent.nick,
            user=self.agent.nick,
            channels=list(self.agent.channels),
            buffer=self._buffer,
            on_mention=self._on_mention,
            tags=list(self.agent.tags),
            on_roominvite=self._on_roominvite,
            tracer=self._tracer,
            metrics=self._metrics,
            backend=self.BACKEND_NAME,
        )
        self._transport.on_ambient = self._on_ambient
        self._transport.on_outgoing = self._on_outgoing
        await self._transport.connect()

        self._webhook = WebhookClient(
            config=self.config.webhooks,
            irc_send=self._transport.send_privmsg,
        )

        self._socket_server = SocketServer(
            path=self._socket_path,
            handler=self._handle_ipc,
        )
        await self._socket_server.start()

        self._supervisor = self._create_supervisor()

        if not self.skip_agent:
            try:
                await self._start_agent_runner()
            except Exception:
                self._on_start_agent_runner_failure()

        self._sleep_task = asyncio.create_task(self._sleep_scheduler())
        self._init_attention()
        self._poll_task = asyncio.create_task(self._poll_loop())

        logger.info(
            "%s started for %s (socket=%s)",
            type(self).__name__,
            self.agent.nick,
            self._socket_path,
        )

    async def stop(self) -> None:
        """Cleanly shut down all components."""
        if hasattr(self, "_poll_task") and self._poll_task:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None

        if hasattr(self, "_sleep_task") and self._sleep_task:
            self._sleep_task.cancel()
            await asyncio.gather(self._sleep_task, return_exceptions=True)
            self._sleep_task = None

        # Cancel _background_tasks (e.g. _delayed_restart) so they don't outlive
        # stop(). Exclude the current task: _ipc_shutdown schedules
        # _graceful_shutdown onto _background_tasks, and _graceful_shutdown
        # awaits self.stop() — so stop() can run inside one of these tracked
        # tasks. Cancelling self mid-teardown would raise CancelledError and
        # abort cleanup. Tasks' add_done_callback(discard) handles removal.
        current = asyncio.current_task()
        to_cancel = [t for t in self._background_tasks if t is not current and not t.done()]
        for task in to_cancel:
            task.cancel()
        if to_cancel:
            await asyncio.gather(*to_cancel, return_exceptions=True)

        if self._agent_runner is not None:
            await self._agent_runner.stop()
            self._agent_runner = None

        if self._socket_server is not None:
            await self._socket_server.stop()
            self._socket_server = None

        if self._transport is not None:
            await self._transport.disconnect()
            self._transport = None

        if self._pid_name:
            remove_pid(self._pid_name)

        logger.info("%s stopped for %s", type(self).__name__, self.agent.nick)

    # ------------------------------------------------------------------
    # Abstract / overridable hooks (subclass implements)
    # ------------------------------------------------------------------

    def _create_supervisor(self) -> Any:
        """Build the backend-specific supervisor. Subclass override."""
        raise NotImplementedError

    async def _start_agent_runner(self) -> None:  # NOSONAR — live_query: harness contract
        """Wire up the backend-specific agent runner. Subclass override."""
        raise NotImplementedError

    def _on_start_agent_runner_failure(self) -> None:
        """Hook for backend-specific recovery when ``_start_agent_runner`` raises.

        Default: log + re-raise. ACP overrides to schedule a delayed restart.
        """
        logger.exception("Failed to start agent runner for %s", self.agent.nick)
        raise

    # ------------------------------------------------------------------
    # Schedulers + polling (Bucket A — universal)
    # ------------------------------------------------------------------

    def _parse_sleep_schedule(self) -> tuple[int, int] | None:
        """Parse sleep_start/sleep_end into minutes. Returns None if invalid."""
        try:
            sh, sm = (int(x) for x in self.config.sleep_start.split(":"))
            wh, wm = (int(x) for x in self.config.sleep_end.split(":"))
            if not (0 <= sh <= 23 and 0 <= sm <= 59 and 0 <= wh <= 23 and 0 <= wm <= 59):
                raise ValueError("hours/minutes out of range")
            return (sh * 60 + sm, wh * 60 + wm)
        except (ValueError, AttributeError):
            logger.warning(
                "Invalid sleep schedule '%s'-'%s' for %s — scheduler disabled",
                getattr(self.config, "sleep_start", None),
                getattr(self.config, "sleep_end", None),
                self.agent.nick,
            )
            return None

    async def _sleep_scheduler(self) -> None:
        """Background task that auto-pauses/resumes based on sleep schedule."""
        schedule = self._parse_sleep_schedule()
        if schedule is None:
            return
        sleep_minutes, wake_minutes = schedule

        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                now = datetime.datetime.now()
                current_minutes = now.hour * 60 + now.minute

                if sleep_minutes > wake_minutes:
                    # Overnight: e.g., 23:00-08:00
                    should_sleep = (
                        current_minutes >= sleep_minutes or current_minutes < wake_minutes
                    )
                else:
                    # Same day: e.g., 13:00-14:00
                    should_sleep = sleep_minutes <= current_minutes < wake_minutes

                if should_sleep and not self._paused:
                    self._paused = True
                    logger.info("Sleep schedule: pausing %s", self.agent.nick)
                elif not should_sleep and self._paused and not self._manually_paused:
                    self._paused = False
                    logger.info("Sleep schedule: resuming %s", self.agent.nick)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sleep scheduler error")

    async def _poll_loop(self) -> None:
        """Background task: tick-driven when attention.enabled, else legacy fixed-interval."""
        if not self._attention_enabled:
            await self._legacy_poll_loop()
            return
        # Local import: claude/acp use shared.config-shape but the class lives per-backend.
        # The function is byte-identical across all 4 — call via self.config / self.agent.
        from codexd.harness.attention import AttentionConfig  # noqa: F401

        attention_cfg = self._resolve_attention_config()
        tick_s = attention_cfg.tick_s
        while True:
            try:
                await asyncio.sleep(tick_s)
                self._tick_attention_poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Poll loop error")

    def _resolve_attention_config(self) -> Any:
        """Indirect access to the per-backend ``resolve_attention_config`` helper.

        Each backend's ``config.py`` exposes ``resolve_attention_config``; subclasses
        wire it via this hook so the base doesn't need to know the import path.
        """
        # Default: try claude's config (the canonical surface). Subclasses may override.
        from codexd.harness.config import resolve_attention_config

        return resolve_attention_config(self.config, self.agent)

    def _tick_attention_poll(self) -> None:
        """One poll-loop iteration when attention is enabled. Helper for _poll_loop."""
        if self._paused or not self._agent_runner or not self._agent_runner.is_running():
            return
        if self._attention is None:
            return
        now = time.monotonic()
        for target in self._attention.due_targets(now):
            self._poll_due_target(target, now)

    def _poll_due_target(self, target: str, now: float) -> None:
        """Poll one target and emit the OTel polls counter. Helper for _tick_attention_poll."""
        self._send_channel_poll(target)
        if self._attention is None:
            return
        self._attention.mark_polled(target, now)
        if self._metrics is None or not getattr(self._metrics, "attention_polls", None):
            return
        band = self._attention.snapshot()[target].band
        self._metrics.attention_polls.add(
            1,
            attributes={
                "agent": self.agent.nick,
                "target": target,
                "band": band.name,
            },
        )

    async def _legacy_poll_loop(self) -> None:
        """Fixed-interval polling. Used when attention.enabled is false."""
        interval = self.config.poll_interval
        if interval <= 0:
            return
        while True:
            try:
                await asyncio.sleep(interval)
                self._process_poll_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Poll loop error")

    def _process_poll_cycle(self) -> None:
        if self._paused or not self._agent_runner or not self._agent_runner.is_running():
            return
        for channel in self.agent.channels:
            self._send_channel_poll(channel)

    def _send_channel_poll(self, channel: str) -> None:
        """Build a poll prompt for the channel and dispatch.

        ``QueuedBaseDaemon`` overrides ``_enqueue_relay_target_for_poll`` to
        register the channel as a relay target before dispatch.
        """
        msgs = self._buffer.read(channel)
        if not msgs:
            return
        # Filter out messages that @mention this agent (already handled)
        nick = self.agent.nick
        short = nick.split("-", 1)[1] if "-" in nick else None
        msgs = [
            m
            for m in msgs
            if not re.search(rf"@{re.escape(nick)}\b", m.text)
            and not (short and re.search(rf"@{re.escape(short)}\b", m.text))
        ]
        if not msgs:
            return
        lines = "\n".join(f"  <{m.nick}> {m.text}" for m in msgs)
        prompt = (
            f"[IRC Channel Poll: {channel}] Recent unread messages:\n"
            f"{lines}\n\n"
            "Respond naturally if any messages need your attention."
        )
        self._enqueue_relay_target_for_poll(channel)
        task = asyncio.create_task(self._agent_runner.send_prompt(prompt))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _enqueue_relay_target_for_poll(self, channel: str) -> None:
        """No-op default (claude). ``QueuedBaseDaemon`` overrides to enqueue."""

    async def _graceful_shutdown(self) -> None:
        """Trigger a graceful shutdown, signaling any waiting stop event."""
        logger.info("Graceful shutdown requested for %s", self.agent.nick)
        if self._stop_event is not None:
            self._stop_event.set()
        else:
            # No external stop_event — stop directly
            await self.stop()

    def set_stop_event(self, event: asyncio.Event) -> None:
        """Register an external stop event that _graceful_shutdown will signal."""
        self._stop_event = event

    # ------------------------------------------------------------------
    # Attention (Bucket A — universal)
    # ------------------------------------------------------------------

    def _init_attention(self) -> None:
        """Build the AttentionTracker from merged config. Called once at start."""
        attention_cfg = self._resolve_attention_config()
        self._attention_enabled = attention_cfg.enabled
        self._attention = AttentionTracker(
            attention_cfg, on_transition=self._on_attention_transition
        )
        for channel in self.agent.channels:
            self._attention.seed(channel)

    def _on_attention_transition(self, target: str, prev: Band, new: Band, cause: str) -> None:
        """Logging + OTel counter hook for attention band transitions."""
        logger.info(
            "attention: agent=%s target=%s band=%s→%s cause=%s",
            self.agent.nick,
            target,
            prev.name,
            new.name,
            cause,
        )
        if self._metrics is not None and getattr(self._metrics, "attention_transitions", None):
            self._metrics.attention_transitions.add(
                1,
                attributes={
                    "agent": self.agent.nick,
                    "target": target,
                    "from_band": prev.name,
                    "to_band": new.name,
                    "cause": cause,
                },
            )

    def _on_ambient(self, target: str, sender: str, text: str) -> None:
        """Ambient stimulus — only counts if the agent has engagement on this target."""
        if self._attention is None or target not in self._last_engaged_at:
            return
        now = time.monotonic()
        thread_window_s = self._resolve_attention_config().thread_window_s
        if (now - self._last_engaged_at[target]) > thread_window_s:
            return
        self._attention.on_ambient(target, now)

    def _on_outgoing(self, target: str, line: str) -> None:
        """Track that the agent has spoken on this target — opens the thread window."""
        self._last_engaged_at[target] = time.monotonic()

    def _on_mention(self, target: str, sender: str, text: str) -> None:
        """Build a prompt for an @mention or DM and dispatch.

        ``QueuedBaseDaemon`` overrides ``_enqueue_relay_target_for_mention``
        to register the mention's relay target before dispatch.
        """
        now = time.monotonic()
        self._last_engaged_at[target] = now
        if self._attention is not None:
            self._attention.on_direct(target, now)

        if self._paused:
            return
        if not (self._agent_runner and self._agent_runner.is_running()):
            return
        self._last_activation = time.time()
        self._enqueue_relay_target_for_mention(target, sender)
        if target.startswith("#"):
            prompt = self._build_channel_prompt(target, sender, text)
        else:
            prompt = self._build_dm_prompt(sender, text)
        task = asyncio.create_task(self._agent_runner.send_prompt(prompt))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _enqueue_relay_target_for_mention(self, target: str, sender: str) -> None:
        """No-op default (claude). ``QueuedBaseDaemon`` overrides to enqueue."""

    def _build_channel_prompt(self, target: str, sender: str, text: str) -> str:
        """Build a prompt for a channel @mention, including thread context if present."""
        thread_match = re.match(r"^\[thread:([a-zA-Z0-9\-]+)\] ", text)
        if thread_match and self._buffer:
            thread_name = thread_match.group(1)
            thread_msgs = self._buffer.read_thread(target, thread_name)
            history = "\n".join(f"  <{m.nick}> {m.text}" for m in thread_msgs)
            return (
                f"[IRC @mention in {target}, thread:{thread_name}]\n"
                f"Thread history:\n{history}\n"
                f"  <{sender}> {text}"
            )
        return f"[IRC @mention in {target}] <{sender}> {text}"

    @staticmethod
    def _build_dm_prompt(sender: str, text: str) -> str:
        """Build a prompt for a direct message."""
        return f"[IRC DM] <{sender}> {text}"

    def _on_roominvite(self, channel: str, meta_text: str) -> None:
        """Called by IRCTransport when a ROOMINVITE is received."""
        task = asyncio.create_task(self._handle_roominvite(channel, meta_text))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _on_agent_message(self, msg: dict) -> None:
        """Feed agent activity to the supervisor + capture status.

        ``QueuedBaseDaemon`` overrides ``_handle_agent_message_pre_supervisor``
        to drain the mention queue + relay agent text to IRC before
        supervisor observation.
        """
        await self._handle_agent_message_pre_supervisor(msg)
        if self._supervisor:
            await self._supervisor.observe(msg)
        self._capture_agent_status(msg)

    async def _handle_agent_message_pre_supervisor(self, msg: dict) -> None:
        """No-op default (claude). ``QueuedBaseDaemon`` overrides to relay."""

    def _build_system_prompt(self) -> str:
        """Default (claude/copilot/acp shape). Codex overrides for direct-response shape."""
        if self.agent.system_prompt:
            return self.agent.system_prompt
        return (
            f"You are {self.agent.nick}, an AI agent on the culture IRC network.\n"
            "You have IRC tools available via the irc skill. Use them to communicate.\n"
            f"Your working directory is {self.agent.directory}.\n"
            "Check IRC channels periodically with irc_read() for new messages.\n"
            "When you finish a task, share results in the appropriate channel with irc_send()."
        )

    # ------------------------------------------------------------------
    # Crash recovery (Bucket A — universal)
    # ------------------------------------------------------------------

    async def _record_crash_time(self, exit_code: int) -> None:
        """Log a crash warning, prune the sliding window, record the new crash, fire agent_error."""
        now = time.time()
        logger.warning("Agent %s crashed with exit code %d", self.agent.nick, exit_code)
        self._crash_times = [t for t in self._crash_times if now - t < CRASH_WINDOW_SECONDS]
        self._crash_times.append(now)
        if self._webhook:
            await self._webhook.fire(
                AlertEvent(
                    event_type="agent_error",
                    nick=self.agent.nick,
                    message=f"Agent {self.agent.nick} crashed (exit {exit_code}).",
                )
            )

    async def _evaluate_circuit_breaker(self) -> bool:
        """Open the circuit breaker if crash count reached the threshold."""
        if len(self._crash_times) >= MAX_CRASH_COUNT:
            self._circuit_open = True
            logger.error(
                "Agent %s crashed %d times in %ds — circuit breaker opened, not restarting",
                self.agent.nick,
                len(self._crash_times),
                CRASH_WINDOW_SECONDS,
            )
            if self._webhook:
                await self._webhook.fire(
                    AlertEvent(
                        event_type="agent_spiraling",
                        nick=self.agent.nick,
                        message=(
                            f"Agent {self.agent.nick} has crashed {len(self._crash_times)} times "
                            f"in {CRASH_WINDOW_SECONDS}s — escalating, not restarting."
                        ),
                    )
                )
            return True
        return False

    def _capture_agent_status(self, msg: dict) -> None:
        """Capture the last assistant text for status reporting and fulfill any pending query."""
        if msg.get("type") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    self._last_activity_text = block["text"]
                    break
                elif isinstance(block, str):
                    self._last_activity_text = block
                    break

            # If a status query is pending, fulfill it
            if self._status_query_event and not self._status_query_event.is_set():
                self._status_query_response = self._last_activity_text
                self._status_query_event.set()

    async def _on_agent_exit(self, exit_code: int) -> None:
        """Handle agent process exit with crash recovery and circuit breaker."""
        if exit_code == 0:
            logger.info("Agent %s exited cleanly", self.agent.nick)
            if self._webhook:
                await self._webhook.fire(
                    AlertEvent(
                        event_type="agent_complete",
                        nick=self.agent.nick,
                        message=f"Agent {self.agent.nick} completed successfully.",
                    )
                )
            return

        await self._record_crash_time(exit_code)
        if await self._evaluate_circuit_breaker():
            return

        # Schedule restart after delay
        logger.info(
            "Restarting agent %s in %ds (crash %d/%d in window)",
            self.agent.nick,
            CRASH_RESTART_DELAY,
            len(self._crash_times),
            MAX_CRASH_COUNT,
        )
        task = asyncio.create_task(self._delayed_restart())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _delayed_restart(self) -> None:
        """Default (claude/codex/copilot shape). ACP overrides for its variant."""
        await asyncio.sleep(CRASH_RESTART_DELAY)
        if not self._circuit_open and self._transport is not None:
            await self._start_agent_runner()

    # ------------------------------------------------------------------
    # Supervisor callbacks (Bucket A — universal)
    # ------------------------------------------------------------------

    async def _on_supervisor_whisper(self, message: str, whisper_type: str) -> None:
        """Deliver a supervisor whisper to the skill client via socket."""
        if self._socket_server:
            await self._socket_server.send_whisper(message, whisper_type)

    async def _on_supervisor_escalation(self, message: str) -> None:
        """Escalate via webhook + IRC when supervisor exhausts whispers."""
        if self._webhook:
            await self._webhook.fire(
                AlertEvent(
                    event_type="agent_spiraling",
                    nick=self.agent.nick,
                    message=f"[ESCALATION] {self.agent.nick}: {message}",
                )
            )

    # ------------------------------------------------------------------
    # IPC handler (Bucket A — universal)
    # ------------------------------------------------------------------

    async def _handle_ipc(self, msg: dict) -> dict:
        """Route an IPC request to the appropriate handler."""
        req_id = msg.get("id", "")
        msg_type = msg.get("type", "")
        try:
            handler = self._ipc_dispatch.get(msg_type)
            if handler is None:
                return make_response(req_id, ok=False, error=f"Unknown message type: {msg_type!r}")
            return await maybe_await(handler(req_id, msg))
        except Exception as exc:
            logger.exception("IPC handler error for type %r", msg_type)
            return make_response(req_id, ok=False, error=str(exc))

    def _ipc_pause(self, req_id: str, msg: dict) -> dict:
        self._paused = True
        self._manually_paused = True
        logger.info("Agent %s paused (manual)", self.agent.nick)
        return make_response(req_id, ok=True)

    def _ipc_resume(self, req_id: str, msg: dict) -> dict:
        self._paused = False
        self._manually_paused = False
        logger.info("Agent %s resumed", self.agent.nick)
        return make_response(req_id, ok=True)

    async def _ipc_status(self, req_id: str, msg: dict) -> dict:
        running = self._agent_runner is not None and self._agent_runner.is_running()
        turn_count = self._supervisor._turn_count if self._supervisor else 0

        # Determine activity description
        query = msg.get("query", False)
        description = self._describe_activity(live_query=query)

        # If live query requested and agent is active, ask the agent directly
        if query and running and not self._paused:
            description = await self._query_agent_status()

        if self._paused:
            activity = "paused"
        elif running:
            activity = "working"
        else:
            activity = "idle"

        return make_response(
            req_id,
            ok=True,
            data={
                "running": running,
                "paused": self._paused,
                "circuit_open": self._circuit_open,
                "turn_count": turn_count,
                "last_activation": self._last_activation,
                "activity": activity,
                "description": description,
            },
        )

    @staticmethod
    def _truncate_first_line(text: str, max_len: int = 120) -> str:
        """Return the first line of *text*, truncated to *max_len* characters."""
        first_line = text.strip().split("\n")[0]
        if len(first_line) > max_len:
            return first_line[: max_len - 3] + "..."
        return first_line

    def _describe_activity(  # NOSONAR — interface param required by harness contract
        self, live_query: bool = False  # NOSONAR — interface contract param
    ) -> str:
        """Return a human-readable description of what the agent is doing."""
        if self._paused:
            return "paused"
        if not self._last_activity_text:
            return "nothing"
        return self._truncate_first_line(self._last_activity_text)

    async def _query_agent_status(self) -> str:
        """Ask the agent directly via send_prompt + status_query_event.

        ``QueuedBaseDaemon`` overrides ``_pre_status_query`` to enqueue a
        None relay target so the response doesn't steal a real mention's slot.
        """
        if not self._agent_runner or not self._agent_runner.is_running():
            return "nothing"

        self._status_query_event = asyncio.Event()
        self._status_query_response = ""

        try:
            self._pre_status_query()
            await self._agent_runner.send_prompt(
                "[SYSTEM] Briefly describe what you are currently working on "
                "in one sentence. Reply with just the description, no preamble."
            )
            async with asyncio.timeout(10.0):
                await self._status_query_event.wait()
            return self._truncate_first_line(self._status_query_response) or "nothing"
        except asyncio.TimeoutError:
            return "busy (no response)"
        finally:
            self._status_query_event = None
            self._status_query_response = ""

    def _pre_status_query(self) -> None:
        """No-op default (claude). ``QueuedBaseDaemon`` overrides to enqueue None."""

    async def _handle_roominvite(self, channel: str, meta_text: str) -> None:
        """Evaluate a room invitation using the agent's LLM.

        ``QueuedBaseDaemon`` overrides ``_pre_roominvite_send`` to enqueue a
        None relay target.
        """
        from codexd.harness.rooms import parse_room_meta

        meta = parse_room_meta(meta_text)
        purpose = meta.get("purpose", "")
        instructions = meta.get("instructions", "")
        tags = meta.get("tags", "")
        _ = meta.get("requestor")

        prompt = (
            f"You've been invited to join IRC room {channel}.\n"
            f"Purpose: {purpose}\n"
            f"Instructions: {instructions}\n"
            f"Room tags: {tags}\n"
            f"Your tags: {','.join(self.agent.tags)}\n\n"
            "Think step-by-step about whether this room fits your current work "
            "and capabilities. Then decide: should you join? Answer YES or NO."
        )

        if self._agent_runner is None or not self._agent_runner.is_running():
            # No live agent — auto-join without evaluation
            logger.info(
                "ROOMINVITE for %s: no agent runner active, auto-joining %s",
                self.agent.nick,
                channel,
            )
            assert self._transport is not None
            await self._transport.send_raw(f"JOIN {channel}")
            return

        self._pre_roominvite_send()
        await self._agent_runner.send_prompt(prompt)
        logger.info(
            "ROOMINVITE for %s on %s — evaluation prompt sent to agent",
            self.agent.nick,
            channel,
        )

    def _pre_roominvite_send(self) -> None:
        """No-op default (claude). ``QueuedBaseDaemon`` overrides to enqueue None."""

    def _check_mention_warnings(self, text: str) -> list[str]:
        """Return warnings for @mentioned nicks not seen in any buffer."""
        mentions = _MENTION_RE.findall(text)
        if not mentions or not self._buffer:
            return []
        known_nicks = self._buffer.known_nicks()
        warnings = []
        for nick in mentions:
            if nick not in known_nicks:
                warnings.append(f"Mentioned nick not found: {nick}")
        return warnings

    async def _ipc_irc_send(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        text = msg.get("message", "")
        if not channel:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL)
        if not text or not text.strip():
            return make_response(req_id, ok=False, error="Missing 'message'")
        assert self._transport is not None
        if channel.startswith("#") and channel not in self._transport.channels:
            return make_response(req_id, ok=False, error=f"Not joined to {channel}")
        await self._transport.send_privmsg(channel, text)
        warnings = self._check_mention_warnings(text)
        resp = make_response(req_id, ok=True)
        if warnings:
            resp["warnings"] = warnings
        return resp

    def _ipc_irc_read(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        limit = int(msg.get("limit", 50))
        if not channel:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL)
        assert self._buffer is not None
        messages = self._buffer.read(channel, limit=limit)
        return make_response(
            req_id,
            ok=True,
            data={
                "messages": [
                    {"nick": m.nick, "text": m.text, "timestamp": m.timestamp} for m in messages
                ]
            },
        )

    async def _ipc_irc_join(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        if not channel:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL)
        if not channel.startswith("#"):
            return make_response(req_id, ok=False, error=_ERR_CHANNEL_PREFIX)
        assert self._transport is not None
        await self._transport.join_channel(channel)
        return make_response(req_id, ok=True)

    async def _ipc_irc_part(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        if not channel:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL)
        if not channel.startswith("#"):
            return make_response(req_id, ok=False, error=_ERR_CHANNEL_PREFIX)
        assert self._transport is not None
        await self._transport.part_channel(channel)
        return make_response(req_id, ok=True)

    async def _ipc_irc_thread_create(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        thread_name = msg.get("thread", "")
        text = msg.get("message", "")
        if not channel or not thread_name or not text:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL_THREAD_MSG)
        assert self._transport is not None
        await self._transport.send_thread_create(channel, thread_name, text)
        return make_response(req_id, ok=True)

    async def _ipc_irc_thread_reply(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        thread_name = msg.get("thread", "")
        text = msg.get("message", "")
        if not channel or not thread_name or not text:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL_THREAD_MSG)
        assert self._transport is not None
        await self._transport.send_thread_reply(channel, thread_name, text)
        return make_response(req_id, ok=True)

    async def _ipc_irc_threads(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        if not channel:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL)
        assert self._transport is not None
        await self._transport.send_threads_list(channel)
        return make_response(req_id, ok=True)

    async def _ipc_irc_thread_close(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        thread_name = msg.get("thread", "")
        summary = msg.get("summary", "")
        if not channel or not thread_name:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL_THREAD)
        assert self._transport is not None
        await self._transport.send_thread_close(channel, thread_name, summary)
        return make_response(req_id, ok=True)

    def _ipc_irc_thread_read(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        thread_name = msg.get("thread", "")
        limit = int(msg.get("limit", 50))
        if not channel or not thread_name:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL_THREAD)
        assert self._buffer is not None
        messages = self._buffer.read_thread(channel, thread_name, limit=limit)
        return make_response(
            req_id,
            ok=True,
            data={
                "messages": [
                    {"nick": m.nick, "text": m.text, "timestamp": m.timestamp, "thread": m.thread}
                    for m in messages
                ]
            },
        )

    def _ipc_irc_channels(self, req_id: str, msg: dict) -> dict:
        assert self._transport is not None
        return make_response(req_id, ok=True, data={"channels": self._transport.channels})

    async def _ipc_irc_who(self, req_id: str, msg: dict) -> dict:
        target = msg.get("target", "")
        if not target:
            return make_response(req_id, ok=False, error="Missing 'target'")
        assert self._transport is not None
        await self._transport.send_who(target)
        return make_response(req_id, ok=True)

    async def _ipc_irc_topic(self, req_id: str, msg: dict) -> dict:
        channel = msg.get("channel", "")
        if not channel:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL)
        if not channel.startswith("#"):
            return make_response(req_id, ok=False, error=_ERR_CHANNEL_PREFIX)
        assert self._transport is not None
        topic = msg.get("topic")
        await self._transport.send_topic(channel, topic)
        return make_response(req_id, ok=True)

    async def _ipc_irc_ask(self, req_id: str, msg: dict) -> dict:
        """Send a PRIVMSG and fire a question webhook. Response matching is TODO."""
        channel = msg.get("channel", "")
        question = msg.get("message", "")
        if not channel:
            return make_response(req_id, ok=False, error=_ERR_MISSING_CHANNEL)
        if not question or not question.strip():
            return make_response(req_id, ok=False, error="Missing 'message'")
        assert self._transport is not None
        await self._transport.send_privmsg(channel, question)
        if self._webhook:
            await self._webhook.fire(
                AlertEvent(
                    event_type="agent_question",
                    nick=self.agent.nick,
                    message=f"[QUESTION] [{self.agent.nick}] asked in {channel}: {question}",
                )
            )
        return make_response(req_id, ok=True)

    async def _ipc_compact(self, req_id: str, msg: dict) -> dict:
        if self._agent_runner is None or not self._agent_runner.is_running():
            return make_response(req_id, ok=False, error="Agent runner is not running")
        await self._agent_runner.send_prompt("/compact")
        return make_response(req_id, ok=True)

    async def _ipc_clear(self, req_id: str, msg: dict) -> dict:
        if self._agent_runner is None or not self._agent_runner.is_running():
            return make_response(req_id, ok=False, error="Agent runner is not running")
        await self._agent_runner.send_prompt("/clear")
        return make_response(req_id, ok=True)

    def _ipc_shutdown(self, req_id: str, msg: dict) -> dict:
        task = asyncio.create_task(self._graceful_shutdown())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return make_response(req_id, ok=True)
