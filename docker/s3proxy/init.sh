#!/usr/bin/env bash
# Idempotent local object-store bootstrap against S3Proxy (filesystem backend).
# Creates private application buckets using the same S3_ACCESS_KEY / S3_SECRET_KEY
# the API uses. No separate root/operator identity.
set -euo pipefail

ENDPOINT="${S3_ENDPOINT_URL:-http://s3proxy:80}"
export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
export AWS_SECRET_ACCESS_KEY="${S3_SECRET_KEY:?S3_SECRET_KEY is required}"
export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"
# Path-style is required for S3Proxy / most local S3-compatible stores.
export AWS_EC2_METADATA_DISABLED=true

aws_s3() {
  aws --endpoint-url "$ENDPOINT" --no-verify-ssl s3 "$@"
}

ensure_bucket() {
  local bucket="$1"
  if aws_s3 ls "s3://${bucket}" >/dev/null 2>&1; then
    return 0
  fi
  aws_s3 mb "s3://${bucket}" >/dev/null
}

for bucket in \
  "$S3_BUCKET_DOCUMENTS" \
  "$S3_BUCKET_AUDIO" \
  "$S3_BUCKET_EXPORTS" \
  "$S3_BUCKET_ANCHORS" \
  "$S3_BUCKET_EVAL" \
  "$S3_BUCKET_BACKUPS"; do
  [[ -n "$bucket" ]] || continue
  ensure_bucket "$bucket"
done

echo "object store ready: ${S3_BUCKET_DOCUMENTS}, ${S3_BUCKET_AUDIO}, ${S3_BUCKET_EXPORTS}, ${S3_BUCKET_ANCHORS}, ${S3_BUCKET_EVAL}, ${S3_BUCKET_BACKUPS}"
