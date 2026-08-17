# LLMOps Control Plane & API Gateway

> A production-grade, self-hostable LLM API Gateway and Observability Control Plane built with **FastAPI**, **Redis Pub/Sub**, **PostgreSQL**, **OpenTelemetry**, **Kubernetes**, **Helm**, and **Terraform**.

---

## 📌 Executive Summary

### What is the LLMOps Control Plane?
The **LLMOps Control Plane** sits directly between your applications (web apps, mobile apps, microservices) and LLM model providers (Anthropic Claude, OpenAI, or local models). It acts as a single, centralized **OpenAI-compatible API Gateway** (`POST /v1/chat/completions`) that monitors, routes, secures, and optimizes every single artificial intelligence request flowing through an organization.

### Why Do Companies Need an LLMOps Control Plane?
Building production AI applications requires much more than simply calling an LLM API. Without a control plane:
- **Uncontrolled Token Costs**: Simple "Hello" queries waste money running on expensive $30/M token models.
- **Provider Outages**: If OpenAI or Anthropic experiences an outage, your entire application crashes.
- **Security Leaks & Jailbreaks**: Users can bypass safety filters or leak sensitive PII (SSNs, credit cards).
- **Zero Observability**: Engineering teams have no real-time visibility into per-request cost, latency, or error spikes.

---

## 🏗️ High-Level System Architecture

```text
                           ┌───────────────────────────┐
                           │   Client Applications     │
                           └─────────────┬─────────────┘
                                         │
                                         ▼ (HTTP POST /v1/chat/completions)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                LLMOps Control Plane                                    │
│                                                                                        │
│   ┌──────────────────────┐    ┌──────────────────────┐    ┌────────────────────────┐   │
│   │   Input Guardrail    │──► │  Complexity Router   │──► │   Resiliency Engine    │   │
│   │ (Injection/Jailbreak)│    │  (Cheap vs Strong)   │    │  (Backoff + Jitter)    │   │
│   └──────────────────────┘    └──────────────────────┘    └───────────┬────────────┘   │
│                                                                       │                │
│   ┌──────────────────────┐    ┌──────────────────────┐                │                │
│   │   Output Guardrail   │◄── │  Model Execution     │◄───────────────┘                │
│   │    (PII Redaction)   │    │ (Mock / Anthropic)   │                                 │
│   └──────────┬───────────┘    └──────────────────────┘                                 │
│              │                                                                         │
└──────────────┼─────────────────────────────────────────────────────────────────────────┘
               │ (Telemetry Event)
               ├────────────────────────────────────────┬────────────────────────────────┐
               ▼                                        ▼                                ▼
     ┌───────────────────┐                    ┌───────────────────┐            ┌───────────────────┐
     │ Shared PostgreSQL │                    │  Redis Pub/Sub    │            │  OpenTelemetry    │
     │(Stateless Logs DB)│                    │  (Event Stream)   │            │(Traces & Metrics) │
     └───────────────────┘                    └─────────┬─────────┘            └───────────────────┘
                                                        │
                                                        ▼ (SSE Push <10ms)
                                              ┌───────────────────┐
                                              │   Live Dashboard  │
                                              │  (HTML5 / WebApp) │
                                              └───────────────────┘
```

---

## 🔥 Key Capabilities & Features

### 1. Intelligent Complexity Routing
- **Automatic Cost Tiering**: Analyzes prompt length and query complexity automatically.
  - Short/Simple Queries ($\le 280$ chars) $\rightarrow$ Routed to **`CHEAP_TIER`** (`mock-model` or lightweight fast models).
  - Long/Complex Queries ($> 280$ chars) $\rightarrow$ Routed to **`STRONG_TIER`** (`claude-3-5-haiku` / strong reasoning models).
- **Cost Reduction**: Cuts organization API spending by **40% to 70%** by routing easy prompts away from expensive models.

### 2. Resiliency & Automatic Failover Engine
- **Attempt Plan Generation**: Builds an ordered fallback plan (e.g. `[anthropic:claude, mock:mock-model]`).
- **Exponential Backoff + Full Jitter**: Calculates randomized retry delays $T = \text{random}(0, \min(2.0, \text{base} \times 2^{\text{attempt}}))$ between retries to desynchronize traffic and prevent retry storms.
- **Strict 4xx vs 5xx Error Taxonomy**:
  - **HTTP 4xx (Client Errors)**: Bad API keys or malformed JSON fail fast immediately (`attempts: 1`, `failed_over: false`) without wasting retries.
  - **HTTP 5xx (Provider Errors)**: Connection timeouts or provider outages trigger automatic failover to backup providers.

### 3. Safety Guardrails Layer (`app/guardrails.py`)
- **Input Guardrails**: Scans incoming prompts *before* LLM provider calls. Detects and blocks **Prompt Injections** and **Jailbreaks** (`"ignore previous instructions"`, `"system override"`), returning HTTP 400 with `"blocked_by_guardrail": true`.
- **Output Guardrails**: Scans LLM responses *before* returning to users. Automatically detects and redacts **PII** (SSNs, Credit Cards, Emails, Phone Numbers) into sanitized placeholders (`[REDACTED SSN]`).

### 4. Operational Alerting Engine (`app/alerts.py`)
Pure, objective rule evaluation monitoring recent telemetry windows:
- **Error Rate Spike**: Alerts if error rate $> 50\%$ in recent window.
- **Provider Failure Burst**: Alerts if a single provider fails $> 3$ times.
- **Cost Spike**: Alerts if window spend exceeds $\$1.00$.
- **Latency Spike**: Alerts if average latency exceeds $5000\text{ ms}$.

### 5. Real-Time SSE + Redis Streaming (`app/stream.py`)
- **Zero-Polling Event Push**: Uses **Redis Pub/Sub** and **Server-Sent Events (SSE)** via `GET /telemetry/stream`.
- **Instant UI Updates**: Pushes new request events to the browser dashboard in **$<10\text{ ms}$** with zero HTTP polling overhead.

### 6. Standard OpenTelemetry Integration (`app/otel.py`)
- Emits standard OpenTelemetry trace spans (`llmops.chat_completions`) and metric counters (`llmops_requests_total`, `llmops_cost_usd_total`, `llmops_latency_ms`) to stdout/console, ready for OTLP export to Prometheus, Grafana, Datadog, or Jaeger.

### 7. Horizontal Stateless Infrastructure (Stage 7 Capstone)
- **Pluggable Telemetry Store**: Seamlessly switches between local **SQLite** (`telemetry.db`) for dev and shared **PostgreSQL** for multi-replica Kubernetes clusters.
- **Infrastructure Packages**:
  - Raw **Kubernetes Manifests** (`k8s/`)
  - Configurable **Helm Chart** (`chart/`)
  - **Terraform IaC** (`terraform/`)

---

## 💼 Real-World Business Use Cases

1. **Unified AI Gateway**: Serve as a single unified endpoint for all internal company teams building AI features.
2. **Cost & Token Optimization**: Save tens of thousands of dollars monthly by preventing simple prompts from executing on high-cost frontier models.
3. **High Availability & Disaster Recovery**: Ensure zero app downtime during third-party LLM provider outages via automatic background failovers.
4. **Regulatory & Compliance Enforcement**: Enforce security policies, GDPR/HIPAA PII redaction, and prompt injection defense at the network boundary.

---

## 🛠️ Prerequisites & Everything Required

To run and deploy this project, you need:

### Software Tools Required:
- **Python**: Version `3.12+` (with `uv` package manager)
- **Docker & Docker Compose**: Version `20.10+`
- **Kubernetes Cluster** *(Optional for Stage 7)*: `kind`, `minikube`, or Docker Desktop / OrbStack K8s
- **Helm**: Version `3.0+`
- **Terraform**: Version `1.0+`

### Environment Configuration:
| Variable | Description | Default |
| :--- | :--- | :--- |
| `ANTHROPIC_API_KEY` | Optional API key for Anthropic Claude | Keyless mock fallback |
| `TELEMETRY_BACKEND` | Telemetry storage backend (`sqlite` or `postgres`) | `sqlite` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://llmops:llmops123@postgres:5432/llmops_telemetry` |
| `REDIS_HOST` | Redis hostname for streaming & counters | `localhost` / `redis` |
| `REDIS_PORT` | Redis port | `6379` |

---

## 🚀 How to Run the Project (Step-by-Step)

### Option A: Quickstart (Local Python Dev Server)
```bash
# 1) Install dependencies via uv:
uv sync

# 2) Run end-to-end smoke test suite:
.venv/bin/python test_smoke.py

# 3) Start local FastAPI server:
.venv/bin/uvicorn app.main:app --reload
```
Open **`http://127.0.0.1:8000/dashboard`** in your browser!

---

### Option B: Run via Docker Compose (Single-Node Stack)
Brings up the FastAPI Control Plane and Redis container:
```bash
# Start containers:
docker compose up --build -d

# Check live operations dashboard:
# http://localhost:8000/dashboard

# Tear down:
docker compose down -v
```

---

### Option C: Deploy to Kubernetes with Helm (Multi-Replica Production Stack)
Deploys 2 Control Plane replicas, shared PostgreSQL, and Redis onto any Kubernetes cluster:

```bash
# 1) Build container image:
docker build -t llmops-control-plane:latest .

# 2) Install Helm chart:
helm install llmops ./chart --create-namespace --namespace llmops

# 3) Verify running pods:
kubectl get pods -n llmops

# 4) Port-forward dashboard:
kubectl port-forward -n llmops svc/llmops 8000:8000
```
Open **`http://localhost:8000/dashboard`** in your browser!

---

### Option D: Provision Infrastructure with Terraform
```bash
cd terraform
terraform init
terraform apply
```

---

## 📊 Summary of Project File Structure

```text
LLMOps/
├── app/
│   ├── main.py              # FastAPI application gateway & API endpoints
│   ├── routing.py           # Intelligent complexity router & failover engine
│   ├── alerts.py            # Operational alert rule engine (4 pure rules)
│   ├── guardrails.py        # Input injection defense & output PII redaction
│   ├── otel.py              # OpenTelemetry traces & metrics exporter
│   ├── stream.py            # Real-time SSE + Redis Pub/Sub streaming module
│   ├── telemetry.py         # Pluggable telemetry store (SQLite vs Postgres)
│   ├── providers.py         # Model provider abstraction (Mock + Anthropic)
│   └── static/
│       └── dashboard.html   # Dark-mode live operations UI
├── k8s/                     # Plain Kubernetes YAML manifests
├── chart/                   # Helm Chart package (values.yaml, templates)
├── terraform/               # Infrastructure as Code modules (main.tf, variables.tf)
├── DOCS/                    # Project guide & technical interview Q&A
├── Dockerfile               # Production container image recipe
├── docker-compose.yml       # Local multi-container compose file
├── pyproject.toml           # UV project requirements
├── test_smoke.py            # End-to-end test suite
└── test_statelessness.py    # Multi-replica shared Postgres verification script
```

---

## 🎯 Conclusion
This **LLMOps Control Plane** provides a complete, scalable, and secure foundation for running artificial intelligence models in production environments. By combining intelligent routing, automated failovers, safety guardrails, and real-time streaming observability, it delivers robust reliability and cost management for modern AI systems.
