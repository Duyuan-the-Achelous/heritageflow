variable "region" {
  description = "Alibaba Cloud region for the evaluation environment."
  type        = string
  default     = "cn-beijing"
}

variable "project_name" {
  description = "Name prefix and resource tag for the platform."
  type        = string
  default     = "heritageflow"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "evaluation"
}

variable "owner" {
  description = "Non-secret owner tag used for cost attribution."
  type        = string
  default     = "duyuan"
}

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    Owner       = var.owner
    ManagedBy   = "terraform"
  }
}

