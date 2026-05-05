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
# Register token.actions.githubusercontent.com as an IAM OIDC provider.
# One-time per AWS account. Idempotent.
set -euo pipefail

OIDC_URL="https://token.actions.githubusercontent.com"
OIDC_AUDIENCE="sts.amazonaws.com"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

echo "==> Checking for existing GitHub OIDC provider"
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "${PROVIDER_ARN}" >/dev/null 2>&1; then
  echo "    provider already exists at ${PROVIDER_ARN}"
  exit 0
fi

echo "==> Creating OIDC provider"
# IAM now fetches and verifies the thumbprint itself when --thumbprint-list is
# omitted for well-known TLS roots (2023+). For older AWS CLI versions,
# pass --thumbprint-list with the current GitHub Actions root CA thumbprint.
aws iam create-open-id-connect-provider \
  --url "${OIDC_URL}" \
  --client-id-list "${OIDC_AUDIENCE}" \
  >/dev/null

echo
echo "OIDC provider created: ${PROVIDER_ARN}"
