variable "region" {
  description = "AWS region for all resources."
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

variable "app_name" {
  description = "App Runner service name."
  type        = string
  default     = "clipforge-demo"
}

variable "image_uri" {
  description = "ECR image URI (registry/repo:tag) for the demo container."
  type        = string
}

variable "daily_limit" {
  description = "Global daily demo run cap surfaced to the app."
  type        = number
  default     = 100
}
