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
# Create an IAM role whose trust policy pins the lab's GitHub repo and ref,
# plus an inline S3 policy scoped to the lab bucket.
set -euo pipefail

: "${AWS_REGION:?AWS_REGION must be set}"
: "${LAB_PREFIX:?LAB_PREFIX must be set}"
: "${GITHUB_REPO:?GITHUB_REPO must be set (e.g. my-org/my-repo)}"
: "${GITHUB_REF:?GITHUB_REF must be set (e.g. refs/heads/main)}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="${LAB_PREFIX}-${ACCOUNT_ID}"
ROLE_NAME="${LAB_PREFIX}-role"
OIDC_PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
TRUST_SUB="repo:${GITHUB_REPO}:ref:${GITHUB_REF}"

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

cat > "${TMP}/trust.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "${OIDC_PROVIDER_ARN}" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "${TRUST_SUB}"
      }
    }
  }]
}
EOF

cat > "${TMP}/permissions.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::${BUCKET}"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::${BUCKET}/*"
    }
  ]
}
EOF

echo "==> Creating or updating role ${ROLE_NAME}"
if aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  echo "    role exists, updating trust policy"
  aws iam update-assume-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-document "file://${TMP}/trust.json"
else
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${TMP}/trust.json" \
    --max-session-duration 3600 \
    --description "Godwit OIDC lab role. Trusts ${GITHUB_REPO} on ${GITHUB_REF}." \
    >/dev/null
fi

echo "==> Attaching inline S3 policy"
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${LAB_PREFIX}-s3" \
  --policy-document "file://${TMP}/permissions.json"

# IAM propagation is eventually consistent; the first workflow run occasionally
# needs to retry. Give it a head start.
sleep 10

ROLE_ARN=$(aws iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)

echo
echo "Role ready: ${ROLE_ARN}"
echo "Trust sub: ${TRUST_SUB}"
echo
echo "Set these in your GitHub repository variables (Settings → Secrets and variables → Actions → Variables):"
echo "  AWS_ROLE_ARN = ${ROLE_ARN}"
echo "  AWS_REGION   = ${AWS_REGION}"
echo "  LAB_BUCKET   = ${BUCKET}"
