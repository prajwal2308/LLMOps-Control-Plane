# LLMOps Control Plane — Helm Chart

This Helm chart deploys the **LLMOps Control Plane** application alongside PostgreSQL and Redis onto any Kubernetes cluster.

## Quickstart

```bash
# Install chart into namespace 'llmops':
helm install llmops ./chart --create-namespace --namespace llmops

# Verify running pods (2 control plane replicas + postgres + redis):
kubectl get pods -n llmops

# Access Live Dashboard via Port Forward:
kubectl port-forward -n llmops svc/llmops 8000:8000
```

Open your browser to: `http://localhost:8000/dashboard`

## Production Cloud Deployment (EKS / GKE / AKS)

When deploying to production cloud environments:
1. Disable in-cluster PostgreSQL and Redis subcharts in `values.yaml`:
   ```yaml
   postgres:
     enabled: false
   redis:
     enabled: false
   ```
2. Point `telemetry.databaseUrl` to your managed PostgreSQL instance (e.g., AWS RDS or GCP Cloud SQL).
3. Run `helm upgrade llmops ./chart --namespace llmops`.
