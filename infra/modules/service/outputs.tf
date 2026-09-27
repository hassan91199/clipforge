output "service_url" {
  description = "Public HTTPS URL of the deployed service."
  value       = aws_apprunner_service.this.service_url
}

output "service_arn" {
  description = "ARN of the App Runner service (needed for custom-domain association)."
  value       = aws_apprunner_service.this.arn
}

output "custom_domain_certificate_validation_records" {
  description = "DNS records to create at the DNS provider to validate the custom domain (empty if custom_domain_name wasn't set)."
  value       = try(aws_apprunner_custom_domain_association.this[0].certificate_validation_records, [])
}

output "custom_domain_dns_target" {
  description = "CNAME target for the custom domain (null if custom_domain_name wasn't set)."
  value       = try(aws_apprunner_custom_domain_association.this[0].dns_target, null)
}
