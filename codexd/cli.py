"""Command-line entry point for codexd."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from typing import Any

from codexd import __version__
from codexd.agent.config import load_config
from codexd.agent.daemon import CodexDaemon

EXIT_USER_ERROR = 1
EXIT_ENV_ERROR = 2


def _hint(message: str) -> None:
    print(f"hint: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codexd",
        description="codexd - Codex agent for Culture and delegated repo work.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    daemon = sub.add_parser("daemon", help="Run the Culture Codex daemon.")
    daemon_sub = daemon.add_subparsers(dest="daemon_command")
    start = daemon_sub.add_parser("start", help="Start Codex agent daemon(s).")
    start.add_argument("nick", nargs="?", help="Agent nick to start.")
    start.add_argument("--all", action="store_true", dest="all_agents", help="Start all agents.")
    start.add_argument("--config", default="~/.culture/agents.yaml", help="Config file path.")
    start.set_defaults(func=_cmd_daemon_start)

    repo = sub.add_parser("repo", help="Run Codex against remote repositories.")
    repo_sub = repo.add_subparsers(dest="repo_command")
    run = repo_sub.add_parser("run", help="Clone, run Codex, commit, and push.")
    run.add_argument("remote")
    run.add_argument("--branch", required=True)
    run.add_argument("--task", required=True)
    run.add_argument("--base")
    run.add_argument("--workspace")
    run.set_defaults(func=_cmd_repo_run)

    push = repo_sub.add_parser("push", help="Retry pushing a managed workspace branch.")
    push.add_argument("--workspace")
    push.add_argument("--branch")
    push.set_defaults(func=_cmd_repo_push)

    clean = repo_sub.add_parser("clean", help="Clean the managed repo workspace.")
    clean.add_argument("--workspace")
    clean.set_defaults(func=_cmd_repo_clean)
    return parser


def _cmd_daemon_start(args: argparse.Namespace) -> int:
    if not args.all_agents and not args.nick:
        _hint("provide an agent nick or pass --all")
        return EXIT_USER_ERROR
    return run_daemon_main(nick=args.nick, all_agents=args.all_agents, config_path=args.config)


def _cmd_repo_run(args: argparse.Namespace) -> int:
    from codexd.repo.workflow import run_repo_task

    return run_repo_task(
        args.remote, branch=args.branch, task=args.task, base=args.base, workspace=args.workspace
    )


def _cmd_repo_push(args: argparse.Namespace) -> int:
    from codexd.repo.workflow import push_workspace

    return push_workspace(workspace=args.workspace, branch=args.branch)


def _cmd_repo_clean(args: argparse.Namespace) -> int:
    from codexd.repo.workflow import clean_workspace

    return clean_workspace(workspace=args.workspace)


def run_daemon_main(*, nick: str | None, all_agents: bool, config_path: str) -> int:
    try:
        config = load_config(config_path)
    except OSError as exc:
        _hint(f"failed to load config {config_path!r}: {exc}")
        return EXIT_ENV_ERROR

    if all_agents:
        agents = config.agents
    else:
        agent = config.get_agent(nick or "")
        if agent is None:
            _hint(f"agent {nick!r} was not found in {config_path!r}")
            return EXIT_USER_ERROR
        agents = [agent]

    if not agents:
        _hint("no Codex agents are configured")
        return EXIT_USER_ERROR

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(_run_daemons(config, agents))
    return 0


async def _run_daemons(config: Any, agents: list[Any]) -> None:
    daemons = [CodexDaemon(config, agent) for agent in agents]
    for daemon in daemons:
        await daemon.start()
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()
    for daemon in reversed(daemons):
        await daemon.stop()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
