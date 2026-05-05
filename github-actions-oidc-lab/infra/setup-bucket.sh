#!/usr/bin/env bash
# Copyright (c) 2026 Godwit.io
#
# Licensed under the MIT License. You may obtain a copy of the License at
#
#     https://opensource.org/licenses/MIT
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# Create the S3 bucket used by the lab and seed it with three small objects.
# Idempotent: running twice does not error.
set -euo pipefail
export AWS_PAGER=""

: "${AWS_REGION:?AWS_REGION must be set}"
: "${LAB_PREFIX:?LAB_PREFIX must be set}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="${LAB_PREFIX}-${ACCOUNT_ID}"

echo "==> Creating bucket s3://${BUCKET} in ${AWS_REGION}"
if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  echo "    bucket already exists, skipping create"
else
  if [ "${AWS_REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${AWS_REGION}"
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${AWS_REGION}" \
      --create-bucket-configuration LocationConstraint="${AWS_REGION}"
  fi
fi

echo "==> Blocking public access"
aws s3api put-public-access-block \
  --bucket "${BUCKET}" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "==> Seeding three objects under source/"
TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT
for i in 1 2 3; do
  printf 'godwit-oidc-lab payload %s\n' "${i}" > "${TMP}/file-${i}.txt"
done
aws s3 cp "${TMP}/" "s3://${BUCKET}/source/" --recursive --only-show-errors

echo
echo "Bucket ready: s3://${BUCKET}"
echo "Set LAB_BUCKET=${BUCKET} in your GitHub repository variables."
