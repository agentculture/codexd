"""IRC Skill Client (codex backend) — re-exports the shared implementation.

The real implementation lives at ``codexd.harness.skill_irc_client``.
This module preserves the per-backend import path
``codexd.agent.skill.irc_client`` and the subprocess entry
point ``python -m codexd.agent.skill.irc_client``.
"""

from __future__ import annotations

import asyncio
import sys

from codexd.harness.skill_irc_client import (  # noqa: F401
    SkillClient,
    _main,
)

if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:]))
