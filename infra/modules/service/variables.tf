variable "app_name" {
  description = "App Runner service name."
  type        = string
}

variable "image_uri" {
  description = "ECR image URI (registry/repo:tag) for the demo container."
  type        = string
}

variable "quota_bucket" {
  description = "Name of the S3 bucket backing the daily run cap."
  type        = string
}

variable "daily_limit" {
  description = "Global daily demo run cap surfaced to the app."
  type        = number
  default     = 100
}
