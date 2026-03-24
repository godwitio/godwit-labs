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
# init-minio.sh — Create the demo-bucket in MinIO (idempotent).
#
# Requires: MinIO container running on localhost:8000

set -euo pipefail

CONTAINER="godwit-lab-minio"
BUCKET_NAME="demo-bucket"

echo "==> Waiting for MinIO ..."
until curl -sf "http://localhost:8000/minio/health/live" >/dev/null 2>&1; do
  printf "    not ready yet, retrying in 3s ...\r"
  sleep 3
done
echo "    MinIO is up."

echo ""
echo "==> Creating bucket '${BUCKET_NAME}' ..."
docker exec "${CONTAINER}" mc alias set local http://localhost:9000 minioadmin minioadmin --quiet
docker exec "${CONTAINER}" mc mb --ignore-existing local/${BUCKET_NAME}

echo ""
echo "==> MinIO initialized."
echo "    Bucket: ${BUCKET_NAME}"
