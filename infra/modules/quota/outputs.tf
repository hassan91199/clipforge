output "bucket" {
  description = "Name of the created quota bucket."
  value       = aws_s3_bucket.quota.id
}
