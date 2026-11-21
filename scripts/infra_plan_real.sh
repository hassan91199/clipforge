#!/bin/sh
# Real `terraform plan` against the real AWS account + Cloudflare zone and
# the real S3 state (read-only - never applies). LocalStack/`terraform
# validate` catch syntax and schema problems, but not AWS-account-specific
# facts (missing IAM actions, an AMI's minimum root volume size, which AZs
# support a given instance type) - those only surface on a real plan/apply.
# Running this locally catches them in seconds instead of a full demo-up
# CI round-trip.
#
# Requires: an `aws configure` profile named "clipforge" with the
# clipforge-deploy credentials, the Cloudflare token at
# ~/.cloudflare-tokens/clipforge (or CLOUDFLARE_API_TOKEN set), and `gh` authenticated as a repo admin (set GH_CMD to wrap it)
# (to read the production environment's vars - never its secrets).
set -e
cd "$(dirname "$0")/../infra"

REPO=hassan91199/clipforge
CLOUDFLARE_TOKEN=${CLOUDFLARE_API_TOKEN:-$(cat ~/.cloudflare-tokens/clipforge)}
AWS_ACCOUNT_ID=$(AWS_PROFILE=clipforge aws sts get-caller-identity --query Account --output text)
IMAGE_TAG=$(AWS_PROFILE=clipforge aws ecr describe-images --repository-name clipforge --region us-east-1 \
    --query 'sort_by(imageDetails,& imagePushedAt)[-1].imageTags[0]' --output text)

VARS_JSON=$(${GH_CMD:-gh} variable list --repo "$REPO" --env production --json name,value)
var() {
    echo "$VARS_JSON" | python3 -c "
import sys, json
for v in json.load(sys.stdin):
    if v['name'] == '$1':
        print(v['value'])
        break
"
}

eval "$(AWS_PROFILE=clipforge aws configure export-credentials --format env)"

tf() {
    docker run --rm \
        -v "$PWD":/workspace -w /workspace \
        -v clipforge-tf-plugin-cache:/plugin-cache \
        -e TF_PLUGIN_CACHE_DIR=/plugin-cache \
        -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
        -e AWS_DEFAULT_REGION="$(var AWS_REGION)" \
        -e TF_VAR_quota_bucket_name="$(var QUOTA_BUCKET_NAME)" \
        -e TF_VAR_image_uri="$AWS_ACCOUNT_ID.dkr.ecr.$(var AWS_REGION).amazonaws.com/clipforge:$IMAGE_TAG" \
        -e TF_VAR_frontend_bucket_name="$(var FRONTEND_BUCKET_NAME)" \
        -e TF_VAR_frontend_domain_name="$(var FRONTEND_DOMAIN_NAME)" \
        -e TF_VAR_api_domain_name="$(var API_DOMAIN_NAME)" \
        -e TF_VAR_cloudflare_zone_id="$(var CLOUDFLARE_ZONE_ID)" \
        -e TF_VAR_cloudflare_api_token="$CLOUDFLARE_TOKEN" \
        -e TF_VAR_shared_secret_env_vars="{\"OPENAI_API_KEY\":\"$(var OPENAI_API_KEY_PARAM_ARN)\",\"REPLICATE_API_TOKEN\":\"$(var REPLICATE_API_TOKEN_PARAM_ARN)\",\"GOOGLE_CLIENT_SECRET\":\"$(var GOOGLE_CLIENT_SECRET_PARAM_ARN)\"}" \
        -e TF_VAR_shared_plain_env_vars="{\"GOOGLE_CLIENT_ID\":\"$(var GOOGLE_CLIENT_ID)\",\"GOOGLE_REDIRECT_URI\":\"$(var GOOGLE_REDIRECT_URI)\"}" \
        hashicorp/terraform:1.16 "$@"
}

tf init -input=false
tf plan -input=false
