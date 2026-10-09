variable "project_name" {
  type        = string
  description = "Prefix applied to AWS resources."
  default     = "heritageflow"
}

variable "aws_region" {
  type        = string
  description = "AWS region used for the assessment deployment."
  default     = "eu-west-1"
}

variable "container_image" {
  type        = string
  description = "Immutable ECR image URI including a tag or digest."
}

variable "api_keys" {
  type = map(object({
    tenant_id = string
    role      = string
  }))
  description = "Opaque runtime tokens mapped to tenant and role. Supply through a sensitive tfvars file or TF_VAR_api_keys."
  sensitive   = true
}

variable "alert_email" {
  type        = string
  description = "Address for operational and budget alerts."
}

variable "monthly_budget_usd" {
  type        = number
  description = "Monthly cost threshold for the student deployment."
  default     = 30
}

variable "desired_count" {
  type        = number
  description = "Baseline ECS task count. Keep two tasks for failure experiments."
  default     = 2
}

variable "certificate_arn" {
  type        = string
  description = "Optional ACM certificate ARN. When omitted, the assessment endpoint uses HTTP."
  default     = null
  nullable    = true
}

