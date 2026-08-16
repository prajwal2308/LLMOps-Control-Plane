# LLMOps Control Plane 🚀

[![Deploy to Render](https://render.com/images/deploy-to-render.svg)](https://render.com/deploy?repo=https://github.com/prajwal2308/LLMOps-Control-Plane)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=flat&logo=python)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED.svg?style=flat&logo=docker)](https://www.docker.com/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-Helm%20%7C%20Terraform-326CE5.svg?style=flat&logo=kubernetes)](https://kubernetes.io/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Traces%20%26%20Metrics-F54842.svg?style=flat&logo=opentelemetry)](https://opentelemetry.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An enterprise-grade, self-hostable **LLMOps Gateway & Control Plane** that sits between your applications and LLM providers (OpenAI, Anthropic, Google Gemini, Bedrock, Fireworks, xAI). It provides **real-time telemetry, cost tracking, complexity-based model routing, automatic failover chains, security guardrails, operational alerts, and OpenTelemetry observability** — wrapped in an OpenAI-compatible API interface.

---

## 📸 Architecture & Overview

```text
                               ┌──────────────────────────────────────────┐
                               │  Client App / Microservice / Web App    │
                               └────────────────────┬─────────────────────┘
                                                    │ OpenAI-Compatible Payload
                                                    ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       LLMOPS CONTROL PLANE GATEWAY                                     │
│                                                                                                        │
│  ┌────────────────────────┐    ┌──────────────────────┐    ┌──────────────────────────────────────┐    │
│  │ 1. Input Guardrails    │───>│ 2. Complexity Router  │───>│ 3. Automated Failover Chain         │    │
│  │    (Injection Defense) │    │    (Cheap vs Strong) │    │    (Primary → Backup 1 → Backup 2)  │    │
│  └────────────────────────┘    └──────────────────────┘    └──────────────────┬───────────────────┘    │
│                                                                               │                        │
│  ┌────────────────────────┐    ┌──────────────────────┐                       │ Outbound LLM Call      │
│  │ 6. Output Guardrails   │<───│ 5. Telemetry & SSE   │<──────────────────────┘                        │
│  │    (PII Redaction)     │    │    (Postgres/Redis)  │                                                │
│  └───────────┬────────────┘    └──────────┬───────────┘                                                │
└──────────────┼────────────────────────────┼────────────────────────────────────────────────────────────┘
               │ Return Clean Response      │ OTLP / SSE Push
               ▼                            ▼
┌──────────────────────────┐    ┌─────────────────────────────────────────┐
│     Client Response      │    │  - Real-Time Web Dashboard (/dashboard) │
│                          │    │  - Grafana Cloud / OTel Collector       │
└──────────────────────────┘    └─────────────────────────────────────────┘
```

---

## ✨ Key Features & Capability Matrix

| Capability | Module | Description |
| :--- | :--- | :--- |
| **OpenAI-Compatible Gateway** | [`app/main.py`](app/main.py) | Drop-in proxy interface for `POST /v1/chat/completions`. |
| **Smart Complexity Routing** | [`app/routing.py`](app/routing.py) | Automatically routes cheap prompts to lightweight models and complex prompts to strong LLMs. |
| **Automatic Failover Chains** | [`app/routing.py`](app/routing.py) | Seamlessly fails over across model tiers on 429 rate limits or 5xx downtime without dropping caller traffic. |
| **Real-Time Telemetry & SSE** | [`app/stream.py`](app/stream.py) | Redis Pub/Sub backed Server-Sent Events push for instant dashboard updates without UI polling. |
| **Operational Alerts Engine** | [`app/alerts.py`](app/alerts.py) | Evaluates recent request streams against 4 rules: Error Spikes (>50%), Provider Failures (>3), Cost Spikes (>$1.00), and Latency Spikes (>5000ms). |
| **Security Guardrails** | [`app/guardrails.py`](app/guardrails.py) | **Input:** Prompt injection & jailbreak defense. **Output:** Automatic PII redaction (SSNs, Credit Cards, Emails, Phone Numbers). |
| **OpenTelemetry Observability** | [`app/otel.py`](app/otel.py) | OTLP-compliant distributed traces and metrics exporter. Integrates directly with Grafana Cloud, Datadog, or SigNoz. |
| **Live Operations Dashboard** | [`app/static/dashboard.html`](app/static/dashboard.html) | Self-hosted dark-mode live operations UI with real-time alert banners. |
| **Cloud-Native Deployment** | [`chart/`](chart/), [`k8s/`](k8s/), [`terraform/`](terraform/) | Ready for Docker, Docker Compose, Kubernetes (Helm), and Terraform provisioning. |

---

## 📁 Repository Structure

```text
.
├── app/                        # Main Application Package
│   ├── main.py                 # FastAPI application routes & gateway orchestrator
│   ├── routing.py              # Complexity-based router & failover chain engine
│   ├── guardrails.py           # Input injection defense & output PII redaction
│   ├── alerts.py               # Operational alerting rules engine
│   ├── telemetry.py            # SQLite/PostgreSQL telemetry persistence ledger
│   ├── stream.py               # SSE streaming & Redis Pub/Sub event emitter
│   ├── otel.py                 # OpenTelemetry trace & metric exporter
│   ├── providers.py            # Unified LLM provider abstraction (Anthropic, Mock, etc.)
│   └── static/
│       └── dashboard.html      # Dark-mode live operations dashboard frontend
├── chart/                      # Helm chart for Kubernetes deployment
├── k8s/                        # Production Kubernetes manifests (Deployments, Services, Ingress)
├── terraform/                  # Terraform module for cloud infrastructure provisioning
├── DOCS/                       # Documentation Directory
│   ├── README.md               # Documentation catalogue & index
│   ├── OTEL-IMPLEMENTATION-GUIDE.md # Production OpenTelemetry & Grafana Cloud setup guide
│   └── BUILD-BOOK-project-guide.html # Step-by-step engineering build book
├── Dockerfile                  # Production container build definition
├── docker-compose.yml          # Multi-container orchestration (App + Redis + Postgres)
├── test_smoke.py               # End-to-end integration & smoke test suite
├── test_statelessness.py       # Multi-replica statelessness verification suite
├── PROJECT-OVERVIEW.md         # Full project architecture & evolutionary design specification
├── TEST-CASES.md               # Detailed test matrix & curl commands
└── requirements.txt            # Python dependencies
```

---

## ⚡ Quickstart

### 1. Local Development Setup

```bash
# Clone the repository
git clone https://github.com/your-username/LLMOps-control-plane.git
cd LLMOps-control-plane

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the end-to-end smoke test suite (tests routing, failover, guardrails & alerts)
python test_smoke.py

# Start the local development server
uvicorn app.main:app --reload --port 8000
```

Open your browser to:
- **Live Operations Dashboard:** [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
- **API Documentation (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 🐳 Container & Kubernetes Deployment

### Option A: Local Execution with Docker Compose

Spins up the Control Plane container alongside a local Redis instance for rate-limiting and SSE streaming:

```bash
# Build and start services in background
docker compose up --build -d

# View live container logs
docker logs -f llmops-control-plane

# Teardown
docker compose down -v
```

---

### Option B: Deploy to Kubernetes with Helm

Deploys a multi-replica stateless control plane (`replicaCount: 2`) with PostgreSQL and Redis:

```bash
# 1. Build container image
docker build -t llmops-control-plane:latest .

# 2. Install Helm release into 'llmops' namespace
helm install llmops ./chart --create-namespace --namespace llmops

# 3. Verify running pods
kubectl get pods -n llmops

# 4. Port-forward to access dashboard
kubectl port-forward -n llmops svc/llmops 8000:8000
```

---

### Option C: Provision with Terraform

```bash
cd terraform
terraform init
terraform apply
```

---

## 📊 OpenTelemetry & Grafana Cloud Observability

The Control Plane includes native OpenTelemetry (OTLP) instrumentation.

To export traces and metrics directly to **Grafana Cloud** (or Datadog / SigNoz), set the following environment variables:

```bash
export OTEL_ENABLED="1"
export OTEL_SERVICE_NAME="llmops-control-plane"
export OTEL_EXPORTER_OTLP_ENDPOINT="https://otlp-gateway-prod-us-east-0.grafana.net/otlp"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <YOUR_BASE64_TOKEN>"
```

For the complete step-by-step telemetry integration guide, see [`DOCS/OTEL-IMPLEMENTATION-GUIDE.md`](DOCS/OTEL-IMPLEMENTATION-GUIDE.md).

---

## 📡 API Reference Summary

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/v1/chat/completions` | Primary OpenAI-compatible endpoint with guardrails, routing & failover. |
| `GET` | `/dashboard` | Self-hosted dark-mode operations dashboard UI. |
| `GET` | `/telemetry/stream` | Server-Sent Events (SSE) real-time event stream. |
| `GET` | `/telemetry` | Paginated request logs (`?limit=N`). |
| `GET` | `/telemetry/summary` | Aggregate metrics (requests, total spend, average latency, error rate). |
| `GET` | `/alerts` | Current active operational alerts evaluated against telemetry windows. |
| `GET` | `/health` | Service liveness health check. |

---

## 🧪 Running Verification Tests

```bash
# Run complete feature smoke test (routing, alerts, guardrails, failover)
python test_smoke.py

# Run stateless multi-replica consistency test
python test_statelessness.py
```

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details.
