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
# Remove the role, the bucket, and the inline policies created by the lab.
# The OIDC provider is left in place (account-level shared resource).
set -euo pipefail

: "${AWS_REGION:?AWS_REGION must be set}"
: "${LAB_PREFIX:?LAB_PREFIX must be set}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="${LAB_PREFIX}-${ACCOUNT_ID}"
ROLE_NAME="${LAB_PREFIX}-role"

echo "==> Deleting inline role policy"
aws iam delete-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${LAB_PREFIX}-s3" 2>/dev/null || true

echo "==> Deleting role"
aws iam delete-role --role-name "${ROLE_NAME}" 2>/dev/null || true

echo "==> Emptying and deleting bucket s3://${BUCKET}"
if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  aws s3 rm "s3://${BUCKET}" --recursive --only-show-errors
  aws s3api delete-bucket --bucket "${BUCKET}" --region "${AWS_REGION}"
fi

echo
echo "Teardown complete. OIDC provider left in place."
echo "To remove it (only if this is a scratch account):"
echo "  aws iam delete-open-id-connect-provider \\"
echo "    --open-id-connect-provider-arn arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
