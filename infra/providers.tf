provider "aws" {
  region = var.region

  # LocalStack mode: dummy credentials, path-style S3, local endpoints.
  access_key                  = var.localstack ? "test" : null
  secret_key                  = var.localstack ? "test" : null
  s3_use_path_style           = var.localstack
  skip_credentials_validation = var.localstack
  skip_metadata_api_check     = var.localstack
  skip_requesting_account_id  = var.localstack

  dynamic "endpoints" {
    for_each = var.localstack ? [1] : []
    content {
      s3  = "http://localhost:4566"
      iam = "http://localhost:4566"
      ecr = "http://localhost:4566"
      sts = "http://localhost:4566"
    }
  }
}
