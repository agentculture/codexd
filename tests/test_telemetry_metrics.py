"""Unit tests for ``codexd.telemetry.metrics.init_metrics``."""

from __future__ import annotations

import grpc
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


def _stub_metric_exporter_class(exporter_kwargs: list[dict]):
    from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult

    class _StubExporter(MetricExporter):
        def __init__(self, **kw) -> None:
            # MetricExporter.__init__ sets _preferred_temporality / _aggregation
            # from kwargs or sensible defaults; calling super() satisfies the
            # PeriodicExportingMetricReader contract.
            super().__init__()
            self.kw = kw
            exporter_kwargs.append(kw)

        def export(self, *args, **kwargs) -> MetricExportResult:  # noqa: D401
            return MetricExportResult.SUCCESS

        def shutdown(self, *args, **kwargs) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    return _StubExporter


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

    exporter_kwargs: list[dict] = []
    monkeypatch.setattr(
        metrics, "OTLPMetricExporter", _stub_metric_exporter_class(exporter_kwargs)
    )
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
    assert exporter_kwargs[0]["compression"] is grpc.Compression.NoCompression


def test_init_metrics_enabled_default_compression_uses_grpc_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter_kwargs: list[dict] = []
    monkeypatch.setattr(
        metrics, "OTLPMetricExporter", _stub_metric_exporter_class(exporter_kwargs)
    )
    cfg = _make_config(enabled=True, metrics_enabled=True)

    metrics.init_metrics(cfg)

    assert exporter_kwargs[0]["compression"] is grpc.Compression.Gzip


def test_init_metrics_unknown_compression_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported telemetry.otlp_compression"):
        metrics._grpc_compression("brotli")


def test_init_metrics_enabled_reinit_keeps_first_global_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter_kwargs: list[dict] = []
    set_calls = 0
    real_set_meter_provider = metrics.metrics.set_meter_provider

    def _counting_set_meter_provider(provider) -> None:
        nonlocal set_calls
        set_calls += 1
        real_set_meter_provider(provider)

    monkeypatch.setattr(
        metrics, "OTLPMetricExporter", _stub_metric_exporter_class(exporter_kwargs)
    )
    monkeypatch.setattr(metrics.metrics, "set_meter_provider", _counting_set_meter_provider)

    first = _make_config(enabled=True, metrics_enabled=True)
    second = _make_config(enabled=True, metrics_enabled=True)
    second.name = "other"

    first_registry = metrics.init_metrics(first)
    second_registry = metrics.init_metrics(second)

    assert second_registry is first_registry
    assert set_calls == 1
    assert len(exporter_kwargs) == 1


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


def test_init_metrics_disabled_leaves_existing_provider_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BadProvider:
        pass

    provider = _BadProvider()
    cfg = _make_config(enabled=False)
    monkeypatch.setattr(metrics, "_meter_provider", provider)

    reg = metrics.init_metrics(cfg)

    assert reg is not None
    assert metrics._meter_provider is provider
