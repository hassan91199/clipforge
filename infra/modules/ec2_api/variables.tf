variable "app_name" {
  description = "Name prefix for this instance's resources (security group, IAM role, log group)."
  type        = string
}

variable "image_uri" {
  description = "ECR image URI (registry/repo:tag) to pull and run on boot."
  type        = string
}

variable "container_port" {
  description = "Port the container listens on (also exposed directly over HTTP for smoke-testing, and reverse-proxied by Caddy for HTTPS)."
  type        = string
  default     = "8080"
}

variable "domain_name" {
  description = "Public domain Caddy requests a Let's Encrypt certificate for and reverse-proxies to the container (e.g. api.clipforge.example.com)."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type. t3.medium gives headroom for ffmpeg/Whisper during a short demo window."
  type        = string
  default     = "t3.medium"
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
  description = "Additional non-secret runtime env vars (e.g. FRONTEND_ORIGIN)."
  type        = map(string)
  default     = {}
}

variable "secret_env_vars" {
  description = "Map of env var name -> SSM Parameter Store ARN (SecureString). Fetched and decrypted by the instance's own role at boot, via user-data - never passed as a plain Terraform variable or baked into the AMI/image."
  type        = map(string)
  default     = {}
}
