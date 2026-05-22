"""Run codexd as a module."""

from __future__ import annotations

import sys

from codexd.cli import main

if __name__ == "__main__":
    sys.exit(main())
