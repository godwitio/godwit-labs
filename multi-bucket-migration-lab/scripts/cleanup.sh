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

# cleanup.sh -- Tear down the lab environment and remove all generated files.

set -euo pipefail

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Stopping lab infrastructure ..."
docker compose -f "${LAB_ROOT}/infra/docker-compose.yml" down -v
echo "    Containers stopped and volumes removed."

echo ""
echo "==> Removing state databases ..."
rm -rf "${LAB_ROOT}/state"
echo "    State directory removed."

echo ""
echo "==> Cleanup complete."
