#!/usr/bin/env bash
#
# Copyright (c) 2026 Godwit.io
#
# Licensed under the MIT License. You may obtain a copy of the License at
#
#     https://opensource.org/licenses/MIT
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# verify-iam.sh — Confirm a migrated identity authenticates against RustFS and
# that its policy is enforced. Uses the appuser credentials seeded on MinIO.
#
# Pass: appuser can list demo-bucket (allowed) and is denied a write (read-only).

set -euo pipefail

RUSTFS_HOST="http://localhost:6000"
USER_KEY="appuser"
USER_SECRET="appsecret123"
BUCKET="demo-bucket"

export AWS_ACCESS_KEY_ID="${USER_KEY}"
export AWS_SECRET_ACCESS_KEY="${USER_SECRET}"

echo "==> Test 1: migrated user lists ${BUCKET} (expect success) ..."
if aws s3 ls "s3://${BUCKET}" --endpoint-url "${RUSTFS_HOST}"; then
  echo "    PASS: ${USER_KEY} authenticated and read access is allowed."
else
  echo "    FAIL: ${USER_KEY} could not authenticate or list the bucket."
  echo "    The import did not transfer this user on your RustFS version."
  exit 1
fi

echo ""
echo "==> Test 2: migrated user attempts a write (expect AccessDenied) ..."
if echo "should be denied" | aws s3 cp - "s3://${BUCKET}/denied.txt" --endpoint-url "${RUSTFS_HOST}" 2>/tmp/deny.txt; then
  echo "    FAIL: write succeeded; the read-only policy did not transfer."
  exit 1
else
  if grep -qi "AccessDenied" /tmp/deny.txt; then
    echo "    PASS: write was denied, read-only policy is enforced."
  else
    echo "    INCONCLUSIVE: write failed for another reason:"
    cat /tmp/deny.txt
  fi
fi

echo ""
echo "==> Verification complete."
