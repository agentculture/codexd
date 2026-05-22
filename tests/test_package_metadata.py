"""Package metadata requirements for the migrated codexd runtime."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _project() -> dict:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_runtime_dependencies_include_harness_requirements() -> None:
    deps = set(_project()["dependencies"])

    assert "pyyaml>=6.0" in deps
    assert "agentirc-cli>=9.6,<10" in deps
    assert "opentelemetry-api>=1.25" in deps
    assert "opentelemetry-sdk>=1.25" in deps
    assert "opentelemetry-exporter-otlp-proto-grpc>=1.25" in deps
    assert "opentelemetry-semantic-conventions>=0.46b0" in deps
    assert "opentelemetry-instrumentation-aiohttp-server>=0.46b0" in deps


def test_pytest_asyncio_is_available_for_harness_tests() -> None:
    dev_deps = set(
        tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"][
            "dev"
        ]
    )

    assert "pytest-asyncio>=0.25" in dev_deps


def test_codexd_workspace_is_gitignored() -> None:
    ignored = Path(".gitignore").read_text(encoding="utf-8")

    assert ".codexd/" in ignored
