# Public demo infra. Two modules with different test stories:
#   module.quota   - S3 counter bucket + IAM (LocalStack-testable, applied in CI)
#   module.service - App Runner service (App Runner has no LocalStack support,
#                    so it only ever applies against real AWS in the deploy step)
module "quota" {
  source      = "./modules/quota"
  bucket_name = var.quota_bucket_name
}

module "service" {
  source       = "./modules/service"
  app_name     = var.app_name
  image_uri    = var.image_uri
  quota_bucket = module.quota.bucket
  daily_limit  = var.daily_limit
}
