#!/bin/sh
# LocalStack gate for the Terraform infra: starts LocalStack, applies the
# quota module (S3+IAM) against it, then tears down. App Runner has no
# LocalStack support, so module.service is only planned/validated here and
# applied against real AWS in the deploy workflow.
set -e
cd "$(dirname "$0")/../infra"

COMPOSE="docker compose -f localstack/docker-compose.yml"

tf() {
    docker run --rm --network host \
        -v "$PWD":/workspace -w /workspace \
        -v clipforge-tf-plugin-cache:/plugin-cache \
        -e TF_PLUGIN_CACHE_DIR=/plugin-cache \
        -e TF_VAR_localstack=true \
        -e TF_VAR_quota_bucket_name=clipforge-demo-quota-local \
        -e TF_VAR_image_uri=local/clipforge:ci \
        hashicorp/terraform:1.9 "$@"
}

cleanup() {
    $COMPOSE down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

$COMPOSE up -d --wait

# Never let the LocalStack run touch real-AWS state or the S3 backend.
# Clean through the container: the earlier terraform steps leave root-owned
# files the host user cannot delete.
docker run --rm --entrypoint sh -v "$PWD":/workspace -w /workspace \
    hashicorp/terraform:1.9 \
    -c "rm -rf .terraform terraform.tfstate terraform.tfstate.backup"

tf fmt -check -recursive
tf init -input=false -backend=false
tf validate
# Targeted apply: only the LocalStack-supported part of the tree.
tf apply -auto-approve -target=module.quota
echo "LocalStack infra gate passed"
