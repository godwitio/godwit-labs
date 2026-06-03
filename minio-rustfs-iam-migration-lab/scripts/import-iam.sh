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
# import-iam.sh — Import the exported IAM zip into RustFS. This is Step 2 of
# Path B and the experimental part of the lab: the import-iam endpoint is
# undocumented and pre-stable, so behavior varies by RustFS version.
#
# The import goes through RustFS's native admin endpoint with a SigV4 curl PUT.
# Note: `mc admin cluster iam import` targets MinIO's /minio/admin/v3/ namespace
# and reports success against RustFS WITHOUT actually importing anything, so it
# is not used here — the curl path below is the one RustFS actually serves.
#
# Requires: ./iam-export.zip (run export-iam.sh first), curl >= 7.75 (--aws-sigv4)

set -euo pipefail

ZIP="iam-export.zip"
RUSTFS_HOST="http://localhost:6000"
RUSTFS_KEY="rustfsadmin"
RUSTFS_SECRET="rustfsadmin"
BUCKET="demo-bucket"

[ -f "./${ZIP}" ] || { echo "ERROR: ./${ZIP} not found. Run export-iam.sh first." >&2; exit 1; }

echo "==> Waiting for RustFS ..."
# RustFS returns 403 on / (SigV4 required), so do NOT use curl -f here — any HTTP
# response means it is listening. Only a connection failure should keep waiting.
until curl -s -o /dev/null "${RUSTFS_HOST}/"; do
  printf "    not ready yet, retrying in 3s ...\r"
  sleep 3
done
echo "    RustFS is up."

# The migrated policy targets demo-bucket, so the bucket must exist on RustFS.
# In a real Path B migration the object data is already there; here we create it.
echo ""
echo "==> Ensuring ${BUCKET} exists on RustFS ..."
AWS_ACCESS_KEY_ID="${RUSTFS_KEY}" AWS_SECRET_ACCESS_KEY="${RUSTFS_SECRET}" \
  aws s3 mb "s3://${BUCKET}" --endpoint-url "${RUSTFS_HOST}" 2>/dev/null || true

echo ""
echo "==> Importing IAM via SigV4 PUT to /rustfs/admin/v3/import-iam ..."
echo "    (requires curl >= 7.75 for --aws-sigv4)"
HTTP_CODE=$(curl -s -o /tmp/import-resp.txt -w "%{http_code}" -X PUT \
  --aws-sigv4 "aws:amz:us-east-1:s3" \
  --user "${RUSTFS_KEY}:${RUSTFS_SECRET}" \
  --data-binary "@./${ZIP}" \
  "${RUSTFS_HOST}/rustfs/admin/v3/import-iam")

echo "    HTTP ${HTTP_CODE}"
cat /tmp/import-resp.txt 2>/dev/null || true
echo ""
if [ "${HTTP_CODE}" = "200" ] || [ "${HTTP_CODE}" = "204" ]; then
  echo "==> Import accepted. Run verify-iam.sh to confirm enforcement."
else
  echo "==> Import did not succeed on this RustFS version."
  echo "    The exported zip in ./${ZIP} still contains the full IAM config to recreate manually."
fi
