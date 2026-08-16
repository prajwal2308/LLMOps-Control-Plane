# LLMOps Control Plane — Documentation Index

Welcome to the documentation directory for the **LLMOps Control Plane**. This directory contains full technical specifications, field guides, observability guides, and architectural references for the platform.

---

## 📚 Documentation Catalogue

| Document | Format | Description |
| :--- | :--- | :--- |
| **[OpenTelemetry Implementation Guide](OTEL-IMPLEMENTATION-GUIDE.md)** | Markdown | Production integration guide for OpenTelemetry, distributed tracing, metrics, and Grafana Cloud observability for serverless & cloud backends. |
| **[Project Overview](../PROJECT-OVERVIEW.md)** | Markdown | Full architectural design, 7-stage evolution plan, and provider integration details. |
| **[Test Suite Specification](../TEST-CASES.md)** | Markdown | Detailed test cases, payload structures, expected behavior, and validation commands. |
| **[Build Book & Project Guide](BUILD-BOOK-project-guide.html)** | HTML | Complete step-by-step engineering build book and stage-by-stage implementation guide. |
| **[Complete Field Guide](COMPLETE-FIELD-GUIDE.html)** | HTML | Executive field guide detailing gateway routing, operational alerts, and security guardrails. |
| **[Field Guide to AI](FIELD-GUIDE-to-AI.html)** | HTML | Deep dive into inference engineering, model failure modes, and resiliency patterns. |

---

## 🚀 Key Architectural Topics Covered

1. **Real-Time Telemetry & SSE Streaming (`app/stream.py` & `app/telemetry.py`)**
   - Redis Pub/Sub integration for instant Server-Sent Events push to dashboards without UI polling.
2. **Complexity-Based Smart Routing (`app/routing.py`)**
   - Heuristic classification routing cheap prompts to lightweight models and complex prompts to strong models.
3. **Automatic Failover Chains**
   - System-level failover advancing across primary → secondary fallback providers on 429 rate limits or 5xx server downtime.
4. **Operational Alert Rules (`app/alerts.py`)**
   - Pure-function evaluation of 4 core signals: Error Rate Spikes (>50%), Provider Failures (>3), Cost Spikes (>$1.00), and Latency Spikes (>5000ms).
5. **Security & Safety Guardrails (`app/guardrails.py`)**
   - Input sanitization blocking prompt injection/jailbreak patterns.
   - Output PII regex scanner with automatic redaction (SSNs, Credit Cards, Emails, Phone Numbers).
6. **Stateless Horizontal Scaling & Kubernetes Deployment (`chart/` & `k8s/`)**
   - PostgreSQL shared ledger + Redis counter store enabling multi-replica scaling with Helm & Terraform.

---

## 📖 Quick Links to Project Files

- **Main API Application:** [`app/main.py`](../app/main.py)
- **OpenTelemetry Exporter:** [`app/otel.py`](../app/otel.py)
- **Interactive Dashboard:** [`app/static/dashboard.html`](../app/static/dashboard.html)
- **Helm Chart Configuration:** [`chart/values.yaml`](../chart/values.yaml)
- **Terraform Manifest:** [`terraform/main.tf`](../terraform/main.tf)
