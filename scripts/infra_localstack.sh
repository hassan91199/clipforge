#!/bin/sh
# LocalStack gate for the Terraform infra: starts LocalStack, applies the
# quota module (S3+IAM) against it, then tears down. App Runner has no
# LocalStack support, so module.service is only planned/validated here and
# applied against real AWS in the deploy workflow.
set -e
cd "$(dirname "$0")/../infra"

COMPOSE="docker compose -f localstack/docker-compose.yml"
TMP=$(mktemp -d)

# Runs against a temp copy of infra/: LocalStack 4.x cannot parse the
# streaming-checksum state uploads Terraform's S3 backend sends, so the
# gate runs with backend.tf removed (plain local state) instead. Real
# deploys keep the committed S3 backend - real S3 accepts those payloads.
cp -r ./* "$TMP"/ 2>/dev/null || cp ./*.tf "$TMP"/
rm -f "$TMP"/backend.tf

tf() {
    docker run --rm --network host \
        -v "$TMP":/workspace -w /workspace \
        -v clipforge-tf-plugin-cache:/plugin-cache \
        -e TF_PLUGIN_CACHE_DIR=/plugin-cache \
        -e TF_VAR_localstack=true \
        -e TF_VAR_quota_bucket_name=clipforge-demo-quota-local \
        -e TF_VAR_image_uri=local/clipforge:ci \
        hashicorp/terraform:1.16 "$@"
}

cleanup() {
    $COMPOSE down -v >/dev/null 2>&1 || true
    # terraform leaves root-owned files; delete the temp dir as root too.
    docker run --rm --entrypoint sh \
        -v "$(dirname "$TMP")":/hosttmp hashicorp/terraform:1.16 \
        -c "rm -rf /hosttmp/$(basename "$TMP")"
}
trap cleanup EXIT

$COMPOSE up -d --wait

tf fmt -check -recursive
tf init -input=false
tf validate
# Targeted apply: only the LocalStack-supported part of the tree.
tf apply -auto-approve -target=module.quota
echo "LocalStack infra gate passed"
