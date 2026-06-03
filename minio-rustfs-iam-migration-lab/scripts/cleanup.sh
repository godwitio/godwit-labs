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
# cleanup.sh — Tear down the lab and remove the exported zip.

set -euo pipefail

cd "$(dirname "$0")/../infra"

echo "==> Stopping containers and removing volumes ..."
docker compose down -v

echo "==> Removing exported IAM zip ..."
rm -f ../iam-export.zip /tmp/import-resp.txt /tmp/deny.txt 2>/dev/null || true

echo "==> Done."
