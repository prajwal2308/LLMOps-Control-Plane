# ==============================================================================
# TERRAFORM INFRASTRUCTURE AS CODE -- STAGE 7 CAPSTONE
# Provisions local Kubernetes resources and deploys the LLMOps Helm Chart.
#
# Cloud Swap Note:
# In real enterprise cloud deployments (AWS / GCP / Azure), replace the local
# Kubernetes provider setup with:
#   1. AWS EKS / GCP GKE Terraform module (e.g. module "eks" { source = "terraform-aws-modules/eks/aws" })
#   2. AWS RDS PostgreSQL module (e.g. module "rds" { source = "terraform-aws-modules/rds/aws" })
#   3. AWS ElastiCache Redis module
# The helm_release resource below remains 100% IDENTICAL when targeting cloud EKS/GKE.
# ==============================================================================

terraform {
  required_version = ">= 1.0.0"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.25.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12.0"
    }
  }
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}

provider "helm" {
  kubernetes {
    config_path = var.kubeconfig_path
  }
}

# Create Kubernetes Namespace
resource "kubernetes_namespace" "llmops" {
  metadata {
    name = var.namespace
  }
}

# Deploy LLMOps Control Plane Helm Release
resource "helm_release" "llmops" {
  name       = "llmops"
  repository = "../chart"
  chart      = "../chart"
  namespace  = kubernetes_namespace.llmops.metadata[0].name

  values = [
    <<-EOT
    replicaCount: ${var.replica_count}
    secrets:
      anthropicApiKey: "${var.anthropic_api_key}"
    EOT
  ]
}
