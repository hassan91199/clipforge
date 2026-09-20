output "service_url" {
  description = "Public HTTPS URL of the deployed demo."
  value       = aws_apprunner_service.demo.service_url
}
