resource "aws_s3_bucket" "quota" {
  bucket = var.bucket_name
  # Counter objects accumulate daily; force_destroy lets a full teardown
  # (CF-34's demo-down) delete the bucket in one terraform destroy without a
  # separate empty-the-bucket step.
  force_destroy = true
}

# One counter object per UTC day under demo-runs/; keep a week of history.
resource "aws_s3_bucket_lifecycle_configuration" "quota" {
  bucket = aws_s3_bucket.quota.id

  rule {
    id     = "expire-old-counters"
    status = "Enabled"

    filter {
      prefix = "demo-runs/"
    }

    expiration {
      days = 7
    }
  }
}
