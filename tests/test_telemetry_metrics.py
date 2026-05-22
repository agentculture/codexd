"""Unit tests for ``codexd.telemetry.metrics.init_metrics``."""

from __future__ import annotations

import pytest
from agentirc.config import ServerConfig, TelemetryConfig
from opentelemetry.metrics import Counter, Histogram, UpDownCounter

from codexd.telemetry import metrics


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    metrics.reset_for_tests()
    yield
    metrics.reset_for_tests()


def _make_config(**telemetry_overrides) -> ServerConfig:
    return ServerConfig(name="test", telemetry=TelemetryConfig(**telemetry_overrides))


def test_init_metrics_disabled_returns_proxy_registry() -> None:
    cfg = _make_config(enabled=False)
    reg = metrics.init_metrics(cfg)
    assert isinstance(reg.irc_bytes_sent, Counter)
    assert isinstance(reg.irc_message_size, Histogram)
    assert isinstance(reg.clients_connected, UpDownCounter)


def test_init_metrics_metrics_disabled_returns_proxy_registry() -> None:
    cfg = _make_config(enabled=True, metrics_enabled=False)
    reg = metrics.init_metrics(cfg)
    # All instruments are still constructed (bound to proxy meter).
    assert reg.audit_writes is not None
    assert reg.bot_invocations is not None


def test_init_metrics_idempotent_for_identical_config() -> None:
    cfg = _make_config(enabled=False)
    r1 = metrics.init_metrics(cfg)
    r2 = metrics.init_metrics(cfg)
    assert r1 is r2


def test_init_metrics_reinit_on_instance_name_change() -> None:
    """Two configs with same TelemetryConfig but different `name` get
    independent registries (so service.instance.id differs)."""
    a = _make_config(enabled=False)
    b = _make_config(enabled=False)
    b.name = "other"
    r_a = metrics.init_metrics(a)
    r_b = metrics.init_metrics(b)
    assert r_a is not r_b


def test_init_metrics_enabled_installs_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``enabled=True`` path: install MeterProvider + PeriodicExportingMetricReader.

    The OTLP exporter is stubbed so no network traffic occurs. We don't need
    a public observable here — just that the call returns a complete registry
    without raising, and the SDK provider has been wired (covered indirectly
    by the next call producing a different registry when name changes).
    """

    from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult

    class _StubExporter(MetricExporter):
        def __init__(self, **kw) -> None:
            # MetricExporter.__init__ sets _preferred_temporality / _aggregation
            # from kwargs or sensible defaults; calling super() satisfies the
            # PeriodicExportingMetricReader contract.
            super().__init__()
            self.kw = kw

        def export(self, *args, **kwargs) -> MetricExportResult:  # noqa: D401
            return MetricExportResult.SUCCESS

        def shutdown(self, *args, **kwargs) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    monkeypatch.setattr(metrics, "OTLPMetricExporter", _StubExporter)
    cfg = _make_config(
        enabled=True,
        metrics_enabled=True,
        otlp_endpoint="http://localhost:4317",
        otlp_compression="none",
    )
    reg = metrics.init_metrics(cfg)
    # Every documented instrument is constructed.
    assert isinstance(reg.irc_bytes_sent, Counter)
    assert isinstance(reg.s2s_relay_latency, Histogram)
    assert isinstance(reg.s2s_links_active, UpDownCounter)


def test_reset_for_tests_shutdown_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider whose shutdown() raises must not propagate from reset_for_tests."""

    class _BadProvider:
        def shutdown(self) -> None:
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(metrics, "_meter_provider", _BadProvider())
    metrics.reset_for_tests()  # must not raise
    assert metrics._meter_provider is None


def test_init_metrics_reinit_shutdown_error_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _BadProvider:
        def shutdown(self) -> None:
            raise RuntimeError("simulated failure")

    cfg = _make_config(enabled=False)
    monkeypatch.setattr(metrics, "_meter_provider", _BadProvider())
    with caplog.at_level("DEBUG", logger="codexd.telemetry.metrics"):
        reg = metrics.init_metrics(cfg)

    assert reg is not None
    assert metrics._meter_provider is None
    assert any("MeterProvider shutdown failed" in r.message for r in caplog.records)
