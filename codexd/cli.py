"""Command-line entry point for codexd."""

from __future__ import annotations

import argparse

from codexd import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the codexd CLI parser."""
    parser = argparse.ArgumentParser(
        prog="codexd",
        description="codexd - Codex daemon for delegated repo tasks and reviewable PRs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the codexd CLI."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
