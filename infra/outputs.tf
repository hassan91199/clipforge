output "service_url" {
  description = "Public URL of the demo once the service module is applied."
  value       = try(module.service.service_url, null)
}

output "quota_bucket" {
  value = module.quota.bucket
}
