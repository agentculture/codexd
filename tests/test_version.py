"""Verify package metadata exposes a version."""

from __future__ import annotations


def test_version_is_populated() -> None:
    from codexd import __version__

    assert __version__
    assert __version__ != "0.0.0"
