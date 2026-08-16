# Grafana Cloud + OpenTelemetry Observability — Production Implementation Guide

> **Target Audience:** Developers & Technical Team  
> **Environment:** Serverless / AWS Lambda / SAM / FastAPI (No Docker required)  
> **Primary Provider:** Grafana Cloud (Free Tier: 50 GB Traces, 50 GB Logs, 10k Metrics/month)  
> **Scope:** Complete end-to-end guide for adding OpenTelemetry distributed tracing, metric aggregation, structured JSON logging, and Grafana dashboards to the AI Workspace backend.

---

## Table of Contents

1. [Executive Summary & Stack Decision](#1-executive-summary--stack-decision)
2. [Architecture & Signal Flow](#2-architecture--signal-flow)
3. [Grafana Cloud Account Setup (3-Minute Setup)](#3-grafana-cloud-account-setup-3-minute-setup)
4. [Python Dependencies & Requirements](#4-python-dependencies--requirements)
5. [Codebase Implementation (Step-by-Step)](#5-codebase-implementation-step-by-step)
   - [File 1: `otel_bootstrap.py` (SDK & Exporters)](#file-1-otel_bootstrappy-sdk--exporters)
   - [File 2: `otel_llm.py` (LLM Spans, Metrics & JSON Logs)](#file-2-otel_llmpy-llm-spans-metrics--json-logs)
   - [File 3: `main.py` Integration](#file-3-mainpy-integration)
   - [File 4: `llm_utils.py` Chokepoint Integration](#file-4-llm_utilspy-chokepoint-integration)
6. [AWS Lambda / SAM Deployment Configuration](#6-aws-lambda--sam-deployment-configuration)
7. [Grafana Dashboard Configuration & Views](#7-grafana-dashboard-configuration--views)
8. [Environment Variables Reference](#8-environment-variables-reference)
9. [Verification & Verification Checklist](#9-verification--verification-checklist)
10. [Kill Switch & Rollback Safety](#10-kill-switch--rollback-safety)

---

## 1. Executive Summary & Stack Decision

### Why Grafana Cloud?

For an AI startup backend (< 10 GB/month data volume running on serverless infrastructure):

- **Zero Infrastructure:** No Docker containers, ClickHouse DBs, or collector pods to host or maintain.
- **Generous Free Forever Tier:** Includes **50 GB/month traces**, **50 GB/month logs**, and **10,000 active metric series** permanently.
- **Dedicated Dashboard URL:** Accessible via a clean standalone URL (`https://<your-org>.grafana.net`). No logging into AWS Console to debug API calls.
- **Out-of-the-Box APM:** Native OpenTelemetry (OTLP) endpoint automatically maps routes, failure rates, latency percentiles (p50/p95/p99), and distributed call waterfalls.

---

## 2. Architecture & Signal Flow

```text
               ┌──────────────────────────────────────────────────────────┐
               │              User API Request / Turn                     │
               └──────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
               ┌──────────────────────────────────────────────────────────┐
               │              FastAPI App (AWS Lambda)                    │
               │  - Auto-instrumented route spans                         │
               │  - Auto-instrumented httpx client calls                  │
               └──────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
               ┌──────────────────────────────────────────────────────────┐
               │          LLM Invocation Chokepoint (llm_utils.py)        │
               │  - Custom OTel Spans: llm.provider, llm.model_id, etc.   │
               │  - Custom Metrics: tokens, cost_usd, latency_ms          │
               │  - Structured JSON stdout (CloudWatch auto-ingest)       │
               └──────────────────────────┬───────────────────────────────┘
                                          │
                  OTLP gRPC Export        │        AWS CloudWatch
               ┌──────────────────────────┴───────────────────────────────┐
               │                                                          │
               ▼                                                          ▼
┌───────────────────────────────┐                          ┌─────────────────────────────┐
│    Grafana Cloud Endpoint     │                          │   AWS CloudWatch Logs       │
│  (Traces + Metrics + Logs)    │                          │  (Backup stdout JSON logs)  │
└───────────────────────────────┘                          └─────────────────────────────┘
```

---

## 3. Grafana Cloud Account Setup (3-Minute Setup)

1. **Sign Up:** Create a free account at [https://grafana.com/products/cloud/](https://grafana.com/products/cloud/).
2. **Access OpenTelemetry Setup:**
   - In your Grafana Cloud portal, click **Connections** -> **OpenTelemetry (OTLP)**.
3. **Obtain Credentials:**
   - **OTLP Endpoint:** e.g., `https://otlp-gateway-prod-us-east-0.grafana.net/otlp`
   - **Instance ID / API Token:** Generate an Access Policy Token with `telemetry:write` permissions.
   - **Authorization Header:** Copy the generated `Basic <base64_encoded_token>` value.

---

## 4. Python Dependencies & Requirements

Add the following OpenTelemetry packages to your `requirements.txt`:

```text
# --- OpenTelemetry Core & Exporters ---
opentelemetry-api>=1.28.0
opentelemetry-sdk>=1.28.0
opentelemetry-exporter-otlp-proto-http>=1.28.0

# --- OpenTelemetry Auto-Instrumentation ---
opentelemetry-instrumentation-fastapi>=0.49b0
opentelemetry-instrumentation-httpx>=0.49b0
```

*Note: We use `opentelemetry-exporter-otlp-proto-http` as it works seamlessly over HTTPS (Port 443) without requiring custom gRPC channels inside serverless AWS Lambda environments.*

---

## 5. Codebase Implementation (Step-by-Step)

### File 1: `otel_bootstrap.py` (SDK & Exporters)

Create `otel_bootstrap.py` in the root of `aselius_workspace/` (or the backend project root):

```python
"""
otel_bootstrap.py
-----------------
OpenTelemetry SDK Initialization for Grafana Cloud.
Import this ONCE at process startup before creating the FastAPI app.

Safety Guarantee:
- OTEL_ENABLED=0 instantly disables all telemetry without code removal.
- If Grafana Cloud credentials are missing, it logs a warning and fails soft.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Kill switch check
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "1").lower() not in ("0", "false", "no", "off")

if OTEL_ENABLED:
    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME

        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        service_name = os.getenv("OTEL_SERVICE_NAME", "aselius-workspace-backend")
        env_name = os.getenv("DEPLOYMENT_ENV", "production")

        resource = Resource.create({
            SERVICE_NAME: service_name,
            "deployment.environment": env_name,
        })

        # Endpoint & Headers for Grafana Cloud
        OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
        OTLP_HEADERS_RAW = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")

        # Parse comma-separated headers (Key=Value,Key2=Value2)
        headers = {}
        if OTLP_HEADERS_RAW:
            for item in OTLP_HEADERS_RAW.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    headers[k.strip()] = v.strip()

        if OTLP_ENDPOINT:
            # Configure HTTP OTLP Exporters for Grafana Cloud
            span_exporter = OTLPSpanExporter(
                endpoint=f"{OTLP_ENDPOINT}/v1/traces",
                headers=headers,
            )
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
            trace.set_tracer_provider(tracer_provider)

            metric_exporter = OTLPMetricExporter(
                endpoint=f"{OTLP_ENDPOINT}/v1/metrics",
                headers=headers,
            )
            metric_reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL_MS", "15000")),
            )
            meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
            metrics.set_meter_provider(meter_provider)

            # Auto-instrument HTTPX outbound client calls (OpenAI, Vertex, Bedrock, Fireworks)
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()

            logger.info("OpenTelemetry initialized successfully for Grafana Cloud (%s)", service_name)
        else:
            logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT not set — Telemetry disabled.")
            OTEL_ENABLED = False

    except Exception as exc:
        logger.error("Failed to initialize OpenTelemetry — failing soft: %s", exc, exc_info=True)
        OTEL_ENABLED = False
```

---

### File 2: `otel_llm.py` (LLM Spans, Metrics & JSON Logs)

Create `otel_llm.py` alongside `otel_bootstrap.py`:

```python
"""
otel_llm.py
-----------
Custom OpenTelemetry Span, Metric, and Structured JSON Logging Helpers.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_OTEL_READY = False

try:
    if os.getenv("OTEL_ENABLED", "1").lower() not in ("0", "false", "no", "off"):
        from opentelemetry import trace, metrics
        _tracer = trace.get_tracer("aselius.llm", "1.0.0")
        _meter = metrics.get_meter("aselius.llm", "1.0.0")

        # Metric Counters & Histograms
        _requests_counter = _meter.create_counter("workspace_llm_requests_total", description="Total LLM calls")
        _tokens_counter = _meter.create_counter("workspace_llm_tokens_total", description="Total LLM tokens")
        _cost_counter = _meter.create_counter("workspace_llm_cost_usd_total", description="Total LLM cost in USD")
        _latency_histogram = _meter.create_histogram("workspace_llm_latency_ms", description="LLM call latency in ms")
        _OTEL_READY = True
except Exception:
    pass


@contextmanager
def trace_llm_call(provider: str, model_id: str, engine_key: str = ""):
    """Wrap an LLM invocation in an OpenTelemetry Trace Span."""
    if not _OTEL_READY:
        yield _NoOpSpan()
        return

    with _tracer.start_as_current_span("llm.invoke") as span:
        span.set_attribute("llm.provider", provider)
        span.set_attribute("llm.model_id", model_id)
        span.set_attribute("llm.engine_key", engine_key)
        start = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.set_attribute("llm.status", "error")
            span.set_attribute("llm.error", str(exc)[:500])
            span.record_exception(exc)
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("llm.latency_ms", round(latency_ms, 2))


def record_llm_telemetry(
    provider: str,
    model_id: str,
    status: str,
    latency_ms: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    engine_key: str = "",
    error: Optional[str] = None,
):
    """Emit both OTel Metrics and a Structured JSON Log to stdout."""
    labels = {
        "provider": provider,
        "model_id": model_id,
        "status": status,
        "engine_key": engine_key or "unknown",
    }

    # 1. Record Metrics to Grafana Cloud
    if _OTEL_READY:
        try:
            _requests_counter.add(1, labels)
            _latency_histogram.record(latency_ms, labels)
            if input_tokens:
                _tokens_counter.add(input_tokens, {**labels, "direction": "input"})
            if output_tokens:
                _tokens_counter.add(output_tokens, {**labels, "direction": "output"})
            if cost_usd > 0:
                _cost_counter.add(cost_usd, labels)
        except Exception as exc:
            logger.debug("Failed to record OTel metrics: %s", exc)

    # 2. Emit Structured JSON Log to stdout (CloudWatch compatible)
    log_doc = {
        "event": "llm_call",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model_id": model_id,
        "status": status,
        "latency_ms": round(latency_ms, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": round(cost_usd, 8),
        "engine_key": engine_key,
    }
    if error:
        log_doc["error"] = str(error)[:500]

    print(json.dumps(log_doc), file=sys.stdout, flush=True)


class _NoOpSpan:
    def set_attribute(self, key, value): pass
    def record_exception(self, exc): pass
```

---

### File 3: `main.py` Integration

In `main.py`, add the OpenTelemetry bootstrap import at the top and instrument the app object:

```python
# --- OpenTelemetry Bootstrap (Must be imported early) ---
import otel_bootstrap

from fastapi import FastAPI
app = FastAPI(title="Aselius Workspace API")

# --- Auto-instrument FastAPI routes ---
if otel_bootstrap.OTEL_ENABLED:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:
        print(f"FastAPI instrumentation skipped: {exc}")
```

---

### File 4: `llm_utils.py` Chokepoint Integration

In `llm_utils.py`, update the `_usage_meta()` method to invoke telemetry reporting automatically for every model call:

```python
    def _usage_meta(
        self,
        bcid: str,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        **extra: Any,
    ) -> Dict[str, Any]:
        meta = enrich_usage_metadata(
            provider,
            model_id,
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                **extra,
            },
        )
        asyncio.create_task(
            self._track_usage_background(
                bcid, meta, provider=provider, model_id=model_id,
            )
        )

        # ── OpenTelemetry & Structured Telemetry Injection ──
        try:
            from otel_llm import record_llm_telemetry
            from aselius_workspace.billing_context import get_billing_context
            ctx = get_billing_context()

            record_llm_telemetry(
                provider=provider,
                model_id=model_id,
                status="ok",
                latency_ms=float(extra.get("latency_ms", 0)),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=float(meta.get("cost_usd", 0)),
                engine_key=ctx.engine_key or "",
            )
        except Exception:
            pass

        return meta
```

---

## 6. AWS Lambda / SAM Deployment Configuration

In your AWS SAM `template.yaml` (or Serverless Framework / Terraform config), configure the environment variables under your Lambda function:

```yaml
Resources:
  AseliusWorkspaceApiFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: main.handler
      Runtime: python3.11
      MemorySize: 1024
      Timeout: 60
      Environment:
        Variables:
          # --- OpenTelemetry Grafana Cloud Configuration ---
          OTEL_ENABLED: "1"
          OTEL_SERVICE_NAME: "aselius-workspace-prod"
          DEPLOYMENT_ENV: "production"
          OTEL_EXPORTER_OTLP_ENDPOINT: "https://otlp-gateway-prod-us-east-0.grafana.net/otlp"
          OTEL_EXPORTER_OTLP_HEADERS: "Authorization=Basic <YOUR_BASE64_TOKEN_HERE>"
          OTEL_METRIC_EXPORT_INTERVAL_MS: "15000"
```

---

## 7. Grafana Dashboard Configuration & Views

Once your service is live and sending telemetry, log into `https://<your-org>.grafana.net` to view your data:

### View 1: Application Observability (Pre-built APM)
- Click **Explore** -> **Application Observability**.
- Select service: `aselius-workspace-prod`.
- **Displays automatically:**
  - Throughput (Requests per Minute)
  - Error Rates (%)
  - Latency Percentiles ($p_{50}$, $p_{95}$, $p_{99}$)
  - Full Trace Waterfall (FastAPI -> `llm.invoke` -> Outbound Provider HTTP call)

### View 2: Custom LLM Operations Dashboard
Create a new Grafana Dashboard with the following PromQL panels:

1. **Total Costs by Provider (USD):**
   ```promql
   sum(increase(workspace_llm_cost_usd_total[1h])) by (provider)
   ```
2. **Token Consumption Rate (Tokens/min):**
   ```promql
   sum(rate(workspace_llm_tokens_total[5m])) by (direction, provider)
   ```
3. **P95 Latency by Model (ms):**
   ```promql
   histogram_quantile(0.95, sum(rate(workspace_llm_latency_ms_bucket[5m])) by (le, model_id))
   ```
4. **Failure Rate by Engine:**
   ```promql
   sum(rate(workspace_llm_requests_total{status="error"}[5m])) by (engine_key) 
   / sum(rate(workspace_llm_requests_total[5m])) by (engine_key) * 100
   ```

---

## 8. Environment Variables Reference

| Variable | Default | Required? | Description |
| :--- | :--- | :--- | :--- |
| `OTEL_ENABLED` | `"1"` | No | Master kill switch (`"0"` disables all telemetry) |
| `OTEL_SERVICE_NAME` | `"aselius-workspace-backend"` | Recommended | Identifies service name in Grafana |
| `DEPLOYMENT_ENV` | `"production"` | No | Environment tag (`production`, `staging`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | None | **Yes** | Grafana Cloud OTLP Base URL |
| `OTEL_EXPORTER_OTLP_HEADERS` | None | **Yes** | `Authorization=Basic <token>` |
| `OTEL_METRIC_EXPORT_INTERVAL_MS` | `"15000"` | No | Metric export flush frequency in ms |

---

## 9. Verification & Verification Checklist

- [ ] **Step 1:** Confirm `requirements.txt` contains `opentelemetry-exporter-otlp-proto-http`.
- [ ] **Step 2:** Deploy Lambda function with environment variables set.
- [ ] **Step 3:** Send a test request to the API.
- [ ] **Step 4:** Check CloudWatch Logs to confirm structured JSON logs appear:
  ```json
  {"event": "llm_call", "provider": "vertex", "model_id": "gemini-3.6-flash", "status": "ok", "latency_ms": 1420.5, "cost_usd": 0.0032}
  ```
- [ ] **Step 5:** Open Grafana Cloud -> **Explore** -> **Traces (Tempo)** and search for `service.name = aselius-workspace-prod` to verify trace waterfalls.

---

## 10. Kill Switch & Rollback Safety

If Grafana Cloud is ever unreachable or telemetry needs to be disabled immediately:

1. **Set Environment Variable:**
   ```env
   OTEL_ENABLED=0
   ```
2. **Result:** All tracing, metrics collection, and background exporters are bypassed instantly. The application continues functioning cleanly without any performance impact or side effects.
