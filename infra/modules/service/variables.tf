variable "app_name" {
  description = "App Runner service name."
  type        = string
}

variable "image_uri" {
  description = "ECR image URI (registry/repo:tag), shared by both the demo and api services."
  type        = string
}

variable "start_command" {
  description = "docker-entrypoint.sh arg to start this service (\"ui\" or \"api\")."
  type        = string
}

variable "port" {
  description = "Port the container listens on for this service."
  type        = string
}

variable "health_check_path" {
  description = "HTTP path App Runner polls to determine service health."
  type        = string
}

variable "cpu" {
  description = "App Runner instance vCPU allocation."
  type        = string
  default     = "1 vCPU"
}

variable "memory" {
  description = "App Runner instance memory allocation."
  type        = string
  default     = "2 GB"
}

variable "min_size" {
  description = "Minimum provisioned instances - 1 keeps the service warm (no cold start) for the whole demo window."
  type        = number
  default     = 1
}

variable "max_size" {
  description = "Maximum concurrent instances, bounding worst-case compute."
  type        = number
  default     = 2
}

variable "quota_bucket" {
  description = "Name of the S3 bucket backing the daily run cap (clipforge/quota.py)."
  type        = string
}

variable "daily_limit" {
  description = "Global daily demo run cap surfaced to the app."
  type        = number
  default     = 100
}

variable "per_ip_daily_limit" {
  description = "Per-IP daily demo run cap surfaced to the app."
  type        = number
  default     = 10
}

variable "plain_env_vars" {
  description = "Additional non-secret runtime env vars specific to this service (e.g. FRONTEND_ORIGIN for the api service)."
  type        = map(string)
  default     = {}
}

variable "secret_env_vars" {
  description = "Map of env var name -> SSM Parameter Store ARN (SecureString). Kept out of plain env vars/state - App Runner resolves these at container start."
  type        = map(string)
  default     = {}
}

variable "custom_domain_name" {
  description = "Custom domain to associate with this service (e.g. api.clipforge.example.com). Null skips custom-domain setup, using only the default *.awsapprunner.com URL."
  type        = string
  default     = null
}
