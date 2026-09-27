output "quota_bucket" {
  value = module.quota.bucket
}

output "demo_service_url" {
  description = "Default App Runner URL for the Streamlit demo (no custom domain in this setup)."
  value       = module.demo_service.service_url
}

output "api_service_url" {
  description = "Default App Runner URL for the FastAPI backend (before the custom domain)."
  value       = module.api_service.service_url
}

output "frontend_bucket" {
  value = module.frontend.bucket_name
}

output "frontend_distribution_id" {
  description = "CloudFront distribution ID - invalidate this after each frontend sync."
  value       = module.frontend.distribution_id
}

output "frontend_url" {
  value = "https://${var.frontend_domain_name}"
}

output "api_url" {
  value = "https://${var.api_domain_name}"
}
