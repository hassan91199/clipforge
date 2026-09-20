# App Runner pulls the image from ECR with an access role; the instance
# itself only needs the S3 counter permissions.
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

resource "aws_apprunner_service" "demo" {
  service_name = var.app_name

  source_configuration {
    auto_deployments_enabled = false

    image_repository {
      image_repository_type = "ECR"
      image_identifier      = var.image_uri

      image_configuration {
        port = "8501"

        runtime_environment_variables = {
          DEMO_BUCKET      = var.quota_bucket
          DEMO_DAILY_LIMIT = tostring(var.daily_limit)
        }
      }
    }

    authentication_configuration {
      access_role_arn = aws_iam_role.ecr_access.arn
    }
  }

  instance_configuration {
    cpu    = "0.25 vCPU"
    memory = "1 GB"
  }

  # App Runner scales to a single provisioned instance when idle; the demo
  # never needs more than 2 active at once, bounding worst-case compute.
  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.demo.arn

  health_check_configuration {
    protocol = "HTTP"
    path     = "/_stcore/health"
  }
}

resource "aws_apprunner_auto_scaling_configuration_version" "demo" {
  auto_scaling_configuration_name = "${var.app_name}-scaling"
  max_size                        = 2
  min_size                        = 1
  max_concurrency                 = 5
}
