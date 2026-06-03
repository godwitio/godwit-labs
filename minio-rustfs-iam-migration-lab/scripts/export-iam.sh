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
# export-iam.sh — Export the full IAM configuration from MinIO as a zip and
# copy it to the host. This is Step 1 of Path B.
#
# Output: ./iam-export.zip (in the lab root)

set -euo pipefail

MINIO="godwit-lab-iam-minio"
OUT="iam-export.zip"

echo "==> Exporting IAM from MinIO ..."
docker exec "${MINIO}" mc alias set src http://localhost:9000 minioadmin minioadmin --quiet
docker exec -w /tmp "${MINIO}" mc admin cluster iam export src

# mc writes <alias>-iam-info.zip into the working directory.
ZIP_IN_CONTAINER=$(docker exec "${MINIO}" sh -c 'ls -1 /tmp/*-iam-*.zip 2>/dev/null | head -1')
if [ -z "${ZIP_IN_CONTAINER}" ]; then
  echo "ERROR: export produced no zip. Check 'mc admin cluster iam export' output." >&2
  exit 1
fi

docker cp "${MINIO}:${ZIP_IN_CONTAINER}" "./${OUT}"
echo ""
echo "==> Exported to ./${OUT}"
echo "    Contents:"
unzip -l "./${OUT}" || true
