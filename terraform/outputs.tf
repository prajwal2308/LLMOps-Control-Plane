output "namespace" {
  value       = kubernetes_namespace.llmops.metadata[0].name
  description = "Kubernetes namespace where LLMOps is deployed"
}

output "helm_release_status" {
  value       = helm_release.llmops.status
  description = "Status of the deployed Helm release"
}

output "dashboard_port_forward_cmd" {
  value       = "kubectl port-forward -n ${var.namespace} svc/llmops 8000:8000"
  description = "Command to access live dashboard locally"
}
