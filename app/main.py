"""
main.py
-------
The API layer. This wires everything together:

  request comes in  ->  route to a provider  ->  TIME the call
                    ->  record telemetry      ->  return the answer

Endpoints:
  POST /v1/chat/completions   send an LLM request through the platform
  GET  /telemetry             see every recorded request (supports status and provider filters)
  GET  /telemetry/summary     see aggregate numbers (supports status and provider filters)
  GET  /health                is the service up?

Run it with:  uvicorn app.main:app --reload
"""

import logging
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.providers import get_provider, estimate_cost, ClientError, ProviderError
from app.telemetry import TelemetryStore, RequestTelemetry
from app.routing import build_attempt_plan, calculate_backoff_with_jitter  # Stage 4: routing + failover
from app.alerts import evaluate_alerts, ALERT_WINDOW_SIZE  # Stage 5: operational alerting
from app.guardrails import check_input_guardrails, check_output_guardrails  # Stage 6: guardrails
from app.otel import trace_span, record_otel_metrics  # Stage 6: OpenTelemetry
from app.stream import publish_telemetry_event, telemetry_event_generator  # SSE + Redis Pub/Sub Streaming


# Setup server-side logger for operational alerts
logger = logging.getLogger("llmops.alerts")
logging.basicConfig(level=logging.INFO)

DASHBOARD_HTML_PATH = Path(__file__).parent / "static" / "dashboard.html"

app = FastAPI(title="LLMOps Control Plane", version="0.1.0")

# One shared telemetry store for the whole app.
store = TelemetryStore()



@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    """Live operations dashboard showing real-time metrics and logs."""
    return DASHBOARD_HTML_PATH.read_text(encoding="utf-8")


# ---- What an incoming request looks like (OpenAI-style shape) --------------
class Message(BaseModel):
    role: str          # "user", "assistant", or "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]          # the conversation so far
    model: str | None = None         # e.g. "mock-model" or "claude-3-5-haiku-20241022"
    provider: str | None = None      # e.g. "mock" or "anthropic"


@app.get("/health")
def health():
    """Simple liveness check."""
    return {"status": "ok"}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    """
    The core path. Every LLM call flows through here so we can observe it.
    Stage 6: Enforces safety guardrails & emits OpenTelemetry traces + metrics.
    """
    with trace_span("llmops.chat_completions", attributes={"provider": req.provider or "auto", "model": req.model or "auto"}):
        messages = [{"role": m.role, "content": m.content} for m in req.messages]

        # Stage 6 Input Guardrail Check (Prompt Injection / Jailbreak Detection)
        is_safe, violation_type, violation_msg = check_input_guardrails(messages)
        if not is_safe:
            store.record(RequestTelemetry(
                provider=req.provider or "none",
                model=req.model or "none",
                latency_ms=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_usd=0.0,
                status="error",
                error=f"[guardrail blocked] {violation_type}: {violation_msg}",
            ))
            record_otel_metrics(req.provider or "none", req.model or "none", "guardrail_blocked", 0.0, 0, 0.0)
            return {
                "error": f"blocked by input guardrail: {violation_msg}",
                "blocked_by_guardrail": True,
                "violation_type": violation_type,
                "routing": {"attempts": 0, "failed_over": False, "plan": []},
            }

        plan = build_attempt_plan(req.provider, req.model, messages)
        plan_str = [f"{p}:{m}" for p, m in plan]

        last_error = None
        for attempt_index, (provider_name, model_name) in enumerate(plan):
            # Stage 4 Resiliency: Apply Exponential Backoff + Full Jitter before retrying / failing over
            if attempt_index > 0:
                backoff_sec = calculate_backoff_with_jitter(attempt_index - 1)
                time.sleep(backoff_sec)

            start = time.perf_counter()

            try:
                provider = get_provider(provider_name)
                text, prompt_tokens, completion_tokens = provider.generate(model_name, messages)
                latency_ms = (time.perf_counter() - start) * 1000
                cost = estimate_cost(model_name, prompt_tokens, completion_tokens)

                # Stage 6 Output Guardrail Check (PII Leak Detection & Redaction)
                is_clean, sanitized_text, detected_pii = check_output_guardrails(text)
                if not is_clean:
                    text = sanitized_text  # redact sensitive PII values before returning

                total_tokens = prompt_tokens + completion_tokens

                record_entry = RequestTelemetry(
                    provider=provider_name,
                    model=model_name,
                    latency_ms=round(latency_ms, 2),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost,
                    status="ok",
                    error=f"[pii_redacted: {','.join(detected_pii)}]" if detected_pii else None,
                )
                store.record(record_entry)
                publish_telemetry_event(record_entry.to_dict())  # Publish event for real-time SSE streaming

                record_otel_metrics(provider_name, model_name, "ok", latency_ms, total_tokens, cost)


                return {
                    "model": model_name,
                    "provider": provider_name,
                    "choices": [{"message": {"role": "assistant", "content": text}}],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                    "cost_usd": cost,
                    "latency_ms": round(latency_ms, 2),
                    "guardrails": {
                        "pii_detected": detected_pii,
                        "pii_redacted": len(detected_pii) > 0,
                    },
                    "routing": {
                        "attempts": attempt_index + 1,
                        "failed_over": attempt_index > 0,
                        "plan": plan_str,
                    },
                }

            except ClientError as e:
                # 4xx User/Client Error: NON-RETRYABLE. Fail fast immediately without failing over!
                latency_ms = (time.perf_counter() - start) * 1000
                store.record(RequestTelemetry(
                    provider=provider_name,
                    model=model_name,
                    latency_ms=round(latency_ms, 2),
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cost_usd=0.0,
                    status="error",
                    error=f"[client error] {e}",
                ))
                record_otel_metrics(provider_name, model_name, "client_error", latency_ms, 0, 0.0)
                return {
                    "error": f"client error (non-retryable): {e}",
                    "routing": {"attempts": attempt_index + 1, "failed_over": False, "plan": plan_str},
                }

            except Exception as e:
                # 5xx Provider / Outage Error: RETRYABLE & Failover-eligible.
                latency_ms = (time.perf_counter() - start) * 1000
                last_error = str(e)
                store.record(RequestTelemetry(
                    provider=provider_name,
                    model=model_name,
                    latency_ms=round(latency_ms, 2),
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cost_usd=0.0,
                    status="error",
                    error=f"[attempt {attempt_index + 1}/{len(plan)}] {e}",
                ))
                record_otel_metrics(provider_name, model_name, "provider_error", latency_ms, 0, 0.0)

        return {
            "error": f"all providers failed: {last_error}",
            "routing": {"attempts": len(plan), "failed_over": True, "plan": plan_str},
        }


@app.get("/telemetry")
def telemetry(
    limit: int | None = None,
    status: str | None = None,
    provider: str | None = None,
):
    """Requests we've seen, as a list. Accepts status and provider filters."""
    return store.all(limit=limit, status=status, provider=provider)


@app.get("/telemetry/summary")
def telemetry_summary(
    status: str | None = None,
    provider: str | None = None,
):
    """The aggregate numbers computed with optional status and provider filters."""
    return store.summary(status=status, provider=provider)


@app.get("/alerts")
def get_alerts():
    """Evaluate current operational telemetry against alert rules.

    Reads the recent ALERT_WINDOW_SIZE telemetry records, runs pure alert rules,
    logs any fired alerts server-side with Python's logging module, and returns JSON.
    """
    records = store.all(limit=ALERT_WINDOW_SIZE)
    fired = evaluate_alerts(records)

    # Server-side logging for every fired alert
    for alert in fired:
        logger.warning(
            "OPERATIONAL ALERT [%s] - %s: %s",
            alert.get("severity", "WARNING").upper(),
            alert.get("rule_id"),
            alert.get("message"),
        )

    return {"alerts": fired, "count": len(fired)}


@app.get("/telemetry/stream")
async def telemetry_stream(request: Request):
    """Real-time Server-Sent Events (SSE) stream endpoint.

    Pushes new telemetry records to connected dashboard browsers instantly
    via Redis Pub/Sub with zero HTTP polling.
    """
    return StreamingResponse(
        telemetry_event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


