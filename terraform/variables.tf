variable "kubeconfig_path" {
  type        = string
  description = "Path to local kubeconfig file"
  default     = "~/.kube/config"
}

variable "namespace" {
  type        = string
  description = "Kubernetes namespace for LLMOps deployment"
  default     = "llmops"
}

variable "replica_count" {
  type        = number
  description = "Number of control plane application replicas"
  default     = 2
}

variable "anthropic_api_key" {
  type        = string
  description = "Optional Anthropic API Key for real Claude model routing"
  default     = ""
  sensitive   = true
}
