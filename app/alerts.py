"""
alerts.py
---------
Stage 5: Operational Alerting for the LLMOps Control Plane.

Design Principle:
  Keep decisions and side-effects separate (matching app/routing.py).
  This module is a PURE rule engine — no network calls, no database, no timing.
  It takes telemetry records in and returns a list of fired alert dictionaries.

Rule Inventory:
  1. Error-rate spike      (fraction of status='error' > 50%)
  2. Provider-failure burst (single provider has > 3 failures)
  3. Cost spike            (total spend in window > $1.00)
  4. Latency spike         (average latency in window > 5000 ms)

All thresholds are constants at the top of the file for easy tuning.
"""

from datetime import datetime, timezone

# --- Alert Threshold Tuning Constants ---------------------------------------
ALERT_WINDOW_SIZE = 50             # evaluate rules over recent N telemetry rows
ERROR_RATE_THRESHOLD = 0.5         # 50% error rate threshold
PROVIDER_FAILURE_THRESHOLD = 3      # 3 recorded errors for a provider in window
COST_SPIKE_THRESHOLD_USD = 1.0     # $1.00 total USD spend threshold
LATENCY_SPIKE_THRESHOLD_MS = 5000.0 # 5000 ms average latency threshold


def evaluate_error_rate(
    records: list[dict],
    window_size: int = ALERT_WINDOW_SIZE,
    threshold: float = ERROR_RATE_THRESHOLD,
) -> dict | None:
    """Rule 1: Error-rate spike.

    Fires if the fraction of failed requests (status='error') in the window
    exceeds the threshold.
    """
    if not records:
        return None

    window = records[-window_size:]
    total = len(window)
    error_count = sum(1 for r in window if r.get("status") == "error")
    rate = error_count / total

    if rate > threshold:
        return {
            "rule_id": "error_rate_spike",
            "severity": "critical",
            "message": f"Error rate spike: {rate:.1%} of recent requests failed (threshold: {threshold:.1%}, {error_count}/{total} calls)",
            "measured_value": round(rate, 4),
            "threshold_value": threshold,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    return None


def evaluate_provider_failures(
    records: list[dict],
    window_size: int = ALERT_WINDOW_SIZE,
    threshold: int = PROVIDER_FAILURE_THRESHOLD,
) -> list[dict]:
    """Rule 2: Provider-failure burst.

    Fires if any single provider has accumulated more than `threshold` errors in the window,
    signaling an upstream outage or missing key.
    """
    if not records:
        return []

    window = records[-window_size:]
    provider_errors: dict[str, int] = {}
    for r in window:
        if r.get("status") == "error":
            p = r.get("provider", "unknown")
            provider_errors[p] = provider_errors.get(p, 0) + 1

    alerts = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for provider, count in provider_errors.items():
        if count > threshold:
            alerts.append({
                "rule_id": "provider_failure_burst",
                "severity": "critical",
                "message": f"Provider failure burst: Provider '{provider}' failed {count} times in recent window (threshold: {threshold})",
                "measured_value": count,
                "threshold_value": threshold,
                "provider": provider,
                "timestamp": now_iso,
            })
    return alerts


def evaluate_cost_spike(
    records: list[dict],
    window_size: int = ALERT_WINDOW_SIZE,
    threshold: float = COST_SPIKE_THRESHOLD_USD,
) -> dict | None:
    """Rule 3: Cost spike.

    Fires if total cost_usd spent across requests in the window exceeds the threshold.
    """
    if not records:
        return None

    window = records[-window_size:]
    total_cost = sum(r.get("cost_usd", 0.0) or 0.0 for r in window)

    if total_cost > threshold:
        return {
            "rule_id": "cost_spike",
            "severity": "warning",
            "message": f"Cost spike detected: Spend in window is ${total_cost:.4f} (threshold: ${threshold:.2f})",
            "measured_value": round(total_cost, 6),
            "threshold_value": threshold,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    return None


def evaluate_latency_spike(
    records: list[dict],
    window_size: int = ALERT_WINDOW_SIZE,
    threshold: float = LATENCY_SPIKE_THRESHOLD_MS,
) -> dict | None:
    """Rule 4: Latency spike.

    Fires if average latency_ms across requests in the window exceeds the threshold.
    """
    if not records:
        return None

    window = records[-window_size:]
    total = len(window)
    avg_latency = sum(r.get("latency_ms", 0.0) or 0.0 for r in window) / total

    if avg_latency > threshold:
        return {
            "rule_id": "latency_spike",
            "severity": "warning",
            "message": f"Latency spike detected: Average window latency is {avg_latency:.1f}ms (threshold: {threshold:.1f}ms)",
            "measured_value": round(avg_latency, 2),
            "threshold_value": threshold,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    return None


def evaluate_alerts(records: list[dict]) -> list[dict]:
    """Run all 4 operational alert rules against the given telemetry records.

    Returns a list of fired alert dictionaries.
    """
    fired_alerts: list[dict] = []

    # 1. Error rate
    err_alert = evaluate_error_rate(records)
    if err_alert:
        fired_alerts.append(err_alert)

    # 2. Provider failures
    prov_alerts = evaluate_provider_failures(records)
    fired_alerts.extend(prov_alerts)

    # 3. Cost spike
    cost_alert = evaluate_cost_spike(records)
    if cost_alert:
        fired_alerts.append(cost_alert)

    # 4. Latency spike
    lat_alert = evaluate_latency_spike(records)
    if lat_alert:
        fired_alerts.append(lat_alert)

    return fired_alerts
