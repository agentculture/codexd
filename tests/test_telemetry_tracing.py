"""Unit tests for ``codexd.telemetry.tracing.init_telemetry``.

Covers all branches of `_build_sampler` and the enabled/disabled paths
of `init_telemetry` (without sending OTLP traffic — the exporter is
constructed but BatchSpanProcessor.add_span_processor only buffers
locally; we shut down the provider in teardown via reset_for_tests).
"""

from __future__ import annotations

import logging

import grpc
import pytest
from agentirc.config import ServerConfig, TelemetryConfig
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ParentBased,
)
from opentelemetry.trace import Tracer

from codexd.telemetry import tracing


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """Each test gets a fresh module state + global OTEL provider."""
    tracing.reset_for_tests()
    yield
    tracing.reset_for_tests()


def _make_config(**telemetry_overrides) -> ServerConfig:
    return ServerConfig(name="test", telemetry=TelemetryConfig(**telemetry_overrides))


def _stub_span_exporter_class(exporter_kwargs: list[dict]):
    class _StubExporter:
        def __init__(self, **kw) -> None:
            self.kw = kw
            exporter_kwargs.append(kw)

        def export(self, spans):  # noqa: D401
            return 0

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    return _StubExporter


# ── _build_sampler ───────────────────────────────────────────────────


def test_build_sampler_parentbased_always_on() -> None:
    s = tracing._build_sampler("parentbased_always_on")
    assert isinstance(s, ParentBased)


def test_build_sampler_parentbased_traceidratio() -> None:
    s = tracing._build_sampler("parentbased_traceidratio:0.25")
    assert isinstance(s, ParentBased)


def test_build_sampler_always_off() -> None:
    s = tracing._build_sampler("always_off")
    assert s is ALWAYS_OFF


def test_build_sampler_unknown_falls_back_with_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="codexd.telemetry.tracing"):
        s = tracing._build_sampler("totally-bogus")
    assert isinstance(s, ParentBased)
    assert any("Unknown telemetry.traces_sampler" in r.message for r in caplog.records)


# ── init_telemetry — disabled paths ──────────────────────────────────


def test_init_telemetry_disabled_returns_noop_tracer() -> None:
    cfg = _make_config(enabled=False)
    t = tracing.init_telemetry(cfg)
    assert isinstance(t, Tracer)
    # When disabled, no SDK provider is installed.


def test_init_telemetry_traces_disabled_returns_noop_tracer() -> None:
    cfg = _make_config(enabled=True, traces_enabled=False)
    t = tracing.init_telemetry(cfg)
    assert isinstance(t, Tracer)


def test_init_telemetry_idempotent_for_identical_config() -> None:
    cfg = _make_config(enabled=False)
    t1 = tracing.init_telemetry(cfg)
    t2 = tracing.init_telemetry(cfg)
    assert t1 is t2  # cached


def test_init_telemetry_reinit_on_config_change() -> None:
    """In-place mutation of TelemetryConfig must trigger re-init."""
    cfg = _make_config(enabled=False)
    tracing.init_telemetry(cfg)
    cfg.telemetry.service_name = "different"
    # Don't assert identity — the second call should not raise and should
    # not return the stale snapshot.
    t2 = tracing.init_telemetry(cfg)
    assert isinstance(t2, Tracer)


# ── init_telemetry — enabled path ────────────────────────────────────


def test_init_telemetry_enabled_default_compression_uses_grpc_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter_kwargs: list[dict] = []
    monkeypatch.setattr(tracing, "OTLPSpanExporter", _stub_span_exporter_class(exporter_kwargs))
    cfg = _make_config(enabled=True, traces_enabled=True)

    tracing.init_telemetry(cfg)

    assert exporter_kwargs[0]["compression"] is grpc.Compression.Gzip


def test_init_telemetry_unknown_compression_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported telemetry.otlp_compression"):
        tracing._grpc_compression("brotli")


def test_init_telemetry_enabled_reinit_keeps_first_global_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter_kwargs: list[dict] = []
    set_calls = 0
    real_set_tracer_provider = tracing.trace.set_tracer_provider

    def _counting_set_tracer_provider(provider) -> None:
        nonlocal set_calls
        set_calls += 1
        real_set_tracer_provider(provider)

    monkeypatch.setattr(tracing, "OTLPSpanExporter", _stub_span_exporter_class(exporter_kwargs))
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", _counting_set_tracer_provider)

    first = _make_config(enabled=True, traces_enabled=True)
    second = _make_config(enabled=True, traces_enabled=True)
    second.name = "other"

    first_tracer = tracing.init_telemetry(first)
    second_tracer = tracing.init_telemetry(second)

    assert second_tracer is first_tracer
    assert set_calls == 1
    assert len(exporter_kwargs) == 1


def test_init_telemetry_enabled_installs_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When telemetry.enabled and traces_enabled, init builds an SDK provider.

    We avoid sending OTLP traffic by stubbing the exporter constructor with
    a no-op replacement that still satisfies BatchSpanProcessor's interface.
    """

    exporter_kwargs: list[dict] = []
    monkeypatch.setattr(tracing, "OTLPSpanExporter", _stub_span_exporter_class(exporter_kwargs))
    cfg = _make_config(
        enabled=True,
        traces_enabled=True,
        otlp_endpoint="http://localhost:4317",
        otlp_compression="none",
        traces_sampler="parentbased_always_on",
    )
    t = tracing.init_telemetry(cfg)
    assert isinstance(t, Tracer)
    assert exporter_kwargs[0]["compression"] is grpc.Compression.NoCompression
