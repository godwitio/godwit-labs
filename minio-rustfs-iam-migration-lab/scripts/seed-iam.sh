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
# seed-iam.sh — Populate MinIO with built-in IAM: a policy, a user, a group,
# and a service account, plus a demo bucket. This is the state Path B migrates.
#
# Requires: MinIO container running on localhost:8000 (docker compose up -d)

set -euo pipefail

MINIO="godwit-lab-iam-minio"
BUCKET="demo-bucket"
USER_KEY="appuser"
USER_SECRET="appsecret123"
POLICY="readonly-demo"
GROUP="developers"

mc() { docker exec "${MINIO}" mc "$@"; }

echo "==> Waiting for MinIO ..."
until curl -sf "http://localhost:8000/minio/health/live" >/dev/null 2>&1; do
  printf "    not ready yet, retrying in 3s ...\r"
  sleep 3
done
echo "    MinIO is up."

echo ""
echo "==> Configuring mc alias and demo bucket ..."
mc alias set src http://localhost:9000 minioadmin minioadmin --quiet
mc mb --ignore-existing src/${BUCKET}
echo "hello from minio" | mc pipe src/${BUCKET}/readme.txt

echo ""
echo "==> Creating canned policy '${POLICY}' (read-only on ${BUCKET}) ..."
docker exec -i "${MINIO}" sh -c "cat > /tmp/${POLICY}.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::${BUCKET}", "arn:aws:s3:::${BUCKET}/*"]
    }
  ]
}
JSON
mc admin policy create src ${POLICY} /tmp/${POLICY}.json

echo ""
echo "==> Creating user '${USER_KEY}' and attaching policy ..."
mc admin user add src ${USER_KEY} ${USER_SECRET}
mc admin policy attach src ${POLICY} --user ${USER_KEY}

echo ""
echo "==> Creating group '${GROUP}' with the user as a member ..."
mc admin group add src ${GROUP} ${USER_KEY}
mc admin policy attach src ${POLICY} --group ${GROUP}

echo ""
echo "==> Creating a service account under '${USER_KEY}' ..."
mc admin user svcacct add src ${USER_KEY} \
  --access-key svc-demo-key \
  --secret-key svc-demo-secret123

echo ""
echo "==> Seeded MinIO IAM:"
mc admin user list src
echo "    policy:  ${POLICY}"
echo "    group:   ${GROUP}"
echo "    svcacct: svc-demo-key"
