variable "region" {
  description = "AWS region for App Runner/S3/IAM."
  type        = string
  default     = "us-east-1"
}

variable "localstack" {
  description = "Run the provider against LocalStack instead of real AWS."
  type        = bool
  default     = false
}

variable "quota_bucket_name" {
  description = "S3 bucket holding the per-day demo run counter."
  type        = string
}

variable "image_uri" {
  description = "ECR image URI (registry/repo:tag), shared by both the demo and api services."
  type        = string
}

variable "demo_app_name" {
  description = "App Runner service name for the Streamlit demo."
  type        = string
  default     = "clipforge-demo"
}

variable "api_app_name" {
  description = "App Runner service name for the FastAPI backend."
  type        = string
  default     = "clipforge-api"
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

variable "shared_secret_env_vars" {
  description = "Env var name -> SSM Parameter Store ARN (SecureString), applied to both services - e.g. OPENAI_API_KEY, REPLICATE_API_TOKEN, GOOGLE_CLIENT_SECRET. Never pass raw secret values here."
  type        = map(string)
  default     = {}
}

variable "shared_plain_env_vars" {
  description = "Non-secret env vars applied to both services - e.g. GOOGLE_CLIENT_ID, GOOGLE_REDIRECT_URI."
  type        = map(string)
  default     = {}
}

variable "frontend_bucket_name" {
  description = "S3 bucket for the static-exported Next.js build (must be globally unique)."
  type        = string
}

variable "frontend_domain_name" {
  description = "Custom domain the frontend is served under, e.g. clipforge.<your-domain>."
  type        = string
}

variable "api_domain_name" {
  description = "Custom domain the API is served under, e.g. api.clipforge.<your-domain>."
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID that frontend_domain_name and api_domain_name's parent domain lives in."
  type        = string
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token, scoped to DNS edit on the zone above."
  type        = string
  sensitive   = true
}
