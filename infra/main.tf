# Public demo infra - CF-34 (on-demand: apply to bring it up, destroy to
# tear it down completely, everything in one AWS+Cloudflare graph).
#   module.quota        - S3 counter bucket + IAM (LocalStack-testable)
#   module.demo_service  - App Runner: clipforge-demo (Streamlit)
#   module.api_ec2       - EC2 + Caddy: clipforge-api (FastAPI), custom domain
#   module.frontend      - S3 + CloudFront: static-exported Next.js frontend
# App Runner/EC2/CloudFront/ACM have no LocalStack support, so only
# module.quota is applied in the LocalStack gate; the rest only ever runs
# against real AWS, in the demo-up/demo-down workflows.
#
# clipforge-api moved off App Runner to EC2 in CF-35: App Runner's managed
# proxy was killing the SSE connection during the render stage's multi-
# minute silence, even with a heartbeat keeping the stream active every 20s
# - evidence the cutoff isn't a simple idle timeout a heartbeat can defeat.
# Caddy on the instance terminates TLS directly, so there's no AWS-managed
# proxy left in the path to impose an undocumented limit.

module "quota" {
  source      = "./modules/quota"
  bucket_name = var.quota_bucket_name
}

module "demo_service" {
  source             = "./modules/service"
  app_name           = var.demo_app_name
  image_uri          = var.image_uri
  start_command      = "ui"
  port               = "8501"
  health_check_path  = "/_stcore/health"
  quota_bucket       = module.quota.bucket
  daily_limit        = var.daily_limit
  per_ip_daily_limit = var.per_ip_daily_limit
  secret_env_vars    = var.shared_secret_env_vars
  plain_env_vars     = var.shared_plain_env_vars
}

module "api_ec2" {
  source             = "./modules/ec2_api"
  app_name           = var.api_app_name
  image_uri          = var.image_uri
  container_port     = "8080"
  domain_name        = var.api_domain_name
  quota_bucket       = module.quota.bucket
  daily_limit        = var.daily_limit
  per_ip_daily_limit = var.per_ip_daily_limit
  secret_env_vars    = var.shared_secret_env_vars

  plain_env_vars = merge(var.shared_plain_env_vars, {
    FRONTEND_ORIGIN = "https://${var.frontend_domain_name}"
  })
}

module "frontend" {
  source      = "./modules/frontend"
  bucket_name = var.frontend_bucket_name
  domain_name = var.frontend_domain_name

  cert_validation_fqdns = [for r in cloudflare_record.frontend_cert_validation : r.hostname]

  providers = {
    aws.us_east_1 = aws.us_east_1
  }
}

# --- DNS (Cloudflare) - created/destroyed in the same apply/destroy as the
# AWS resources above, so a single terraform destroy leaves nothing behind.

resource "cloudflare_record" "frontend_cert_validation" {
  for_each = {
    for dvo in module.frontend.cert_domain_validation_options : dvo.domain_name => dvo
  }
  zone_id = var.cloudflare_zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  content = each.value.resource_record_value
  ttl     = 60
  proxied = false
}

resource "cloudflare_record" "frontend" {
  zone_id = var.cloudflare_zone_id
  name    = var.frontend_domain_name
  type    = "CNAME"
  content = module.frontend.distribution_domain_name
  ttl     = 60
  proxied = false
}

# No cert-validation records here (unlike frontend's ACM cert above) - Caddy
# on the instance gets its own Let's Encrypt cert directly at boot, so there
# is no Terraform-side validation step for the API's domain anymore.
resource "cloudflare_record" "api" {
  zone_id = var.cloudflare_zone_id
  name    = var.api_domain_name
  type    = "A"
  content = module.api_ec2.public_ip
  ttl     = 60
  proxied = false
}
