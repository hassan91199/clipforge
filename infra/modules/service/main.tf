# App Runner pulls the image from ECR with an access role; the instance
# itself only needs the S3 counter permissions (+ SSM for secrets, below).
# Instantiated twice from infra/main.tf, once per app_name (clipforge-demo,
# clipforge-api), off the same image_uri - same pattern deploy.yml already
# used for Cloud Run.
data "aws_region" "current" {}

resource "aws_iam_role" "ecr_access" {
  name = "${var.app_name}-ecr-access"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "build.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ecr_pull" {
  name = "${var.app_name}-ecr-pull"
  role = aws_iam_role.ecr_access.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role" "instance" {
  name = "${var.app_name}-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "tasks.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "quota_counter" {
  name = "${var.app_name}-quota-counter"
  role = aws_iam_role.instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject"]
      Resource = "arn:aws:s3:::${var.quota_bucket}/demo-runs/*"
    }]
  })
}

# SecureString params (OPENAI_API_KEY, REPLICATE_API_TOKEN, etc.) are
# referenced by ARN, never passed as plain Terraform variables - keeps
# secret values out of runtime_environment_variables and out of state.
resource "aws_iam_role_policy" "secrets" {
  count = length(var.secret_env_vars) > 0 ? 1 : 0
  name  = "${var.app_name}-secrets"
  role  = aws_iam_role.instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameters"
        Resource = values(var.secret_env_vars)
      },
      {
        # SecureString params use the AWS-managed alias/aws/ssm key by
        # default - scoping by ViaService avoids having to hardcode that
        # key's account-specific ARN here.
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ssm.${data.aws_region.current.name}.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_apprunner_service" "this" {
  service_name = var.app_name

  source_configuration {
    auto_deployments_enabled = false

    image_repository {
      image_repository_type = "ECR"
      image_identifier      = var.image_uri

      image_configuration {
        port = var.port
        # The image's default CMD runs the test suite (docker run --rm
        # clipforge = gate); App Runner must start ui/api instead.
        start_command = var.start_command

        runtime_environment_variables = merge({
          DEMO_BUCKET             = var.quota_bucket
          DEMO_DAILY_LIMIT        = tostring(var.daily_limit)
          DEMO_PER_IP_DAILY_LIMIT = tostring(var.per_ip_daily_limit)
        }, var.plain_env_vars)

        runtime_environment_secrets = var.secret_env_vars
      }
    }

    authentication_configuration {
      access_role_arn = aws_iam_role.ecr_access.arn
    }
  }

  instance_configuration {
    cpu               = var.cpu
    memory            = var.memory
    instance_role_arn = aws_iam_role.instance.arn
  }

  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.this.arn

  health_check_configuration {
    protocol = "HTTP"
    path     = var.health_check_path
  }
}

resource "aws_apprunner_auto_scaling_configuration_version" "this" {
  auto_scaling_configuration_name = "${var.app_name}-scaling"
  max_size                        = var.max_size
  min_size                        = var.min_size
  max_concurrency                 = 5
}

resource "aws_apprunner_custom_domain_association" "this" {
  count       = var.custom_domain_name != null ? 1 : 0
  domain_name = var.custom_domain_name
  service_arn = aws_apprunner_service.this.arn
}
