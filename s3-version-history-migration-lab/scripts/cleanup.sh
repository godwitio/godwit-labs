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

# cleanup.sh — Tear down the version history lab environment.

set -euo pipefail

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Stopping Docker containers ..."
docker compose -f "${LAB_ROOT}/infra/docker-compose.yml" down --volumes --remove-orphans
echo "    Containers stopped and volumes removed."

echo ""
echo "==> Removing local state ..."

for target in \
  "${LAB_ROOT}/godwit.state.db" \
  "${LAB_ROOT}/godwit.state.db-wal" \
  "${LAB_ROOT}/godwit.state.db-shm" \
  "${LAB_ROOT}/godwit-sync.state.db" \
  "${LAB_ROOT}/godwit-sync.state.db-wal" \
  "${LAB_ROOT}/godwit-sync.state.db-shm" \
  "${LAB_ROOT}/object-lock.state.db" \
  "${LAB_ROOT}/object-lock.state.db-wal" \
  "${LAB_ROOT}/object-lock.state.db-shm"
do
  if [[ -e "${target}" ]]; then
    rm -f "${target}"
    echo "    removed: ${target}"
  fi
done

echo ""
echo "==> Cleanup complete."
