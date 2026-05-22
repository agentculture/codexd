"""Codex agent daemon — bridges a Codex agent to the IRC network.

Uses CodexAgentRunner (codex app-server over JSON-RPC/stdio) and
CodexSupervisor (codex exec for periodic evaluation). Inherits the
shared FIFO mention-queue topology from
``codexd.harness.queued_base_daemon.QueuedBaseDaemon``.
"""

from __future__ import annotations

import logging
import re

from codexd.agent.agent_runner import CodexAgentRunner
from codexd.agent.config import (
    AgentConfig,
    DaemonConfig,
    resolve_attention_config,
)
from codexd.agent.constants import DEFAULT_TURN_TIMEOUT_SECONDS
from codexd.agent.supervisor import CodexSupervisor
from codexd.harness.queued_base_daemon import QueuedBaseDaemon

logger = logging.getLogger(__name__)

# Regex to strip meta-response patterns from Codex output
_META_RESPONSE_RE = re.compile(
    r"^(?:I(?:'d| would) (?:reply|respond|say|post|send)(?: (?:in|to|on|with))?\s*"
    r"(?:`?#\S+`?)?\s*(?:with)?:?\s*(?:>\s*)?)",
    re.IGNORECASE,
)


class CodexDaemon(QueuedBaseDaemon):
    """Codex agent daemon — queue-shape mention routing + meta-response cleaning."""

    BACKEND_NAME = "codex"

    def __init__(
        self,
        config: DaemonConfig,
        agent: AgentConfig,
        socket_dir: str | None = None,
        skip_codex: bool = False,
    ) -> None:
        super().__init__(config, agent, socket_dir=socket_dir, skip_agent=skip_codex)
        self.skip_codex = skip_codex
        self._agent_runner: CodexAgentRunner | None = None
        self._supervisor: CodexSupervisor | None = None

    def _resolve_attention_config(self):
        return resolve_attention_config(self.config, self.agent)

    def _create_supervisor(self) -> CodexSupervisor:
        return CodexSupervisor(
            model=self.config.supervisor.model,
            window_size=self.config.supervisor.window_size,
            eval_interval=self.config.supervisor.eval_interval,
            escalation_threshold=self.config.supervisor.escalation_threshold,
            prompt_override=self.config.supervisor.prompt_override,
            on_whisper=self._on_supervisor_whisper,
            on_escalation=self._on_supervisor_escalation,
        )

    async def _start_agent_runner(self) -> None:  # NOSONAR — live_query: harness contract
        self._agent_runner = CodexAgentRunner(  # NOSONAR — receive-as-is contract
            model=self.agent.model,
            directory=self.agent.directory,
            system_prompt=self._build_system_prompt(),
            on_exit=self._on_agent_exit,
            on_message=self._on_agent_message,
            on_turn_error=self._on_turn_error,
            metrics=self._metrics,
            nick=self.agent.nick,
            turn_timeout_seconds=getattr(
                self.agent, "turn_timeout_seconds", DEFAULT_TURN_TIMEOUT_SECONDS
            ),
        )
        await self._agent_runner.start()
        logger.info("CodexAgentRunner started for %s", self.agent.nick)

    # ------------------------------------------------------------------
    # Codex-specific overrides
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Codex variant — adds the 'respond DIRECTLY' instruction."""
        if self.agent.system_prompt:
            return self.agent.system_prompt
        return (
            f"You are {self.agent.nick}, an AI agent on the culture IRC network.\n"
            "You have IRC tools available via the irc skill. Use them to communicate.\n"
            f"Your working directory is {self.agent.directory}.\n"
            "Check IRC channels periodically with irc_read() for new messages.\n"
            "When you finish a task, share results in the appropriate channel with irc_send().\n\n"
            "IMPORTANT: When responding to messages, write your response DIRECTLY — "
            "do not describe what you would say, do not wrap responses in meta-commentary "
            "like 'I'd reply with:' or 'I would say:'. Just write the actual message content. "
            "Your text output is relayed verbatim to IRC channels."
        )

    @staticmethod
    def _strip_meta_response(line: str) -> str:
        """Strip meta-response prefix and blockquote markers from a line."""
        line = _META_RESPONSE_RE.sub("", line).strip()
        if line.startswith("> "):
            line = line[2:]
        return line

    def _clean_relay_lines(self, text: str) -> list[str]:
        """Strip, filter, and clean lines from a text content item."""
        result = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            line = self._strip_meta_response(line)
            if line and line != ">":
                result.append(line)
        return result

    async def _send_relay_lines(self, relay_target: str, content: list) -> None:
        """Codex override — uses the meta-stripping ``_clean_relay_lines`` helper."""
        for item in content:
            if item.get("type") != "text":
                continue
            text = item["text"].strip()
            for line in self._clean_relay_lines(text):
                await self._transport.send_privmsg(relay_target, line)
