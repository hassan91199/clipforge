output "quota_bucket" {
  value = module.quota.bucket
}

output "demo_service_url" {
  description = "Default App Runner URL for the Streamlit demo (no custom domain in this setup)."
  value       = module.demo_service.service_url
}

output "api_service_url" {
  description = "Direct http://ip:8080 URL for the FastAPI backend container, reachable before DNS/TLS are ready - used for CI smoke-testing only; real traffic goes through the custom domain via Caddy."
  value       = "http://${module.api_ec2.public_ip}:8080"
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
