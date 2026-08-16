"""
otel.py
-------
Stage 6: OpenTelemetry Tracing & Metrics Exporter.

Speaks the industry-standard observability language (OTel Traces + Metrics).
Currently instruments OpenTelemetry trace spans and metric counters, emitting
structured OTel traces and metrics to stdout/console.

Production Integration Note:
To stream these metrics directly into a live Prometheus or Grafana backend,
attach an OTLP MetricExporter (e.g. `OTLPMetricExporter` or `PrometheusMetricReader`).
"""

import sys
import time
from contextlib import contextmanager

# Try importing official OpenTelemetry SDK packages if available in environment
try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider

    # Initialize standard OTel Providers
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer("llmops.tracer", "0.1.0")

    meter_provider = MeterProvider()
    metrics.set_meter_provider(meter_provider)
    meter = metrics.get_meter("llmops.meter", "0.1.0")

    # Metrics instruments
    request_counter = meter.create_counter(
        "llmops_requests_total",
        description="Total count of LLM requests processed by gateway",
    )
    latency_histogram = meter.create_histogram(
        "llmops_latency_ms",
        description="Histogram of request latency in milliseconds",
    )
    cost_counter = meter.create_counter(
        "llmops_cost_usd_total",
        description="Total USD cost incurred across providers",
    )
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    tracer = None
    meter = None


@contextmanager
def trace_span(name: str, attributes: dict | None = None):
    """Context manager for an OpenTelemetry trace span."""
    start_time = time.perf_counter()
    attributes = attributes or {}

    if OTEL_AVAILABLE and tracer:
        with tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span
    else:
        # Structured OTel Span stdout fallback when OTel SDK is not loaded
        span_id = f"span_{int(start_time * 1000) % 100000}"
        print(f"INFO:     OTEL TRACE SPAN START [{span_id}] {name} attr={attributes}", flush=True)
        try:
            yield span_id
        finally:
            dur_ms = (time.perf_counter() - start_time) * 1000
            print(f"INFO:     OTEL TRACE SPAN END   [{span_id}] {name} duration={dur_ms:.2f}ms", flush=True)


def record_otel_metrics(
    provider: str,
    model: str,
    status: str,
    latency_ms: float,
    total_tokens: int,
    cost_usd: float,
):
    """Record standard OpenTelemetry request metrics."""
    labels = {"provider": provider, "model": model, "status": status}

    if OTEL_AVAILABLE and meter:
        try:
            request_counter.add(1, labels)
            latency_histogram.record(latency_ms, labels)
            cost_counter.add(cost_usd, labels)
        except Exception as e:
            print(f"WARNING:  Failed to record OTel metric: {e}", flush=True)

    # Always flush structured OTel Metric output directly to stdout
    print(
        f"INFO:     OTEL METRIC | provider={provider} model={model} status={status} latency={latency_ms:.2f}ms tokens={total_tokens} cost=${cost_usd:.6f}",
        flush=True
    )
