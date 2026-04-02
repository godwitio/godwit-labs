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

# migrate.sh -- Execute multiple round-trip migrations with Prometheus metrics
# to generate 20+ minutes of continuous Grafana dashboard data.
#
# Each round runs the full three-hop cycle:
#   hop1: local FS  -> MinIO 1  (fs-to-s3)
#   hop2: MinIO 1   -> MinIO 2  (s3-to-s3)
#   hop3: MinIO 2   -> local FS (s3-to-fs)
#
# After the round-trip hops, a version-history migration replicates all object
# versions between two MinIO 1 buckets (versioned-src -> versioned-dst).
#
# Rounds use separate S3 prefixes (round-1/, round-2/, ...) and unique run-ids
# so all runs appear independently in the Grafana per-run panels. Throttle rates
# vary between rounds to create visible throughput pattern changes in the charts.
#
# All hops use --status-addr :9091 and --drain-timeout 15 (3x the 5s
# Prometheus scrape interval) so Prometheus can scrape final metrics.
# Open http://localhost:3000 (Grafana) to watch the dashboards live.
#
# Prerequisites:
#   docker compose -f infra/docker-compose.yml up -d
#   python3 scripts/seed-data.py

set -euo pipefail

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DB="${LAB_ROOT}/godwit.state.db"

# MinIO 1 (source) -- port 8000
MINIO1_ENDPOINT="localhost:8000"
MINIO1_AK="minioadmin"
MINIO1_SK="minioadmin"

# MinIO 2 (destination) -- port 8002
MINIO2_ENDPOINT="localhost:8002"
MINIO2_AK="minioadmin"
MINIO2_SK="minioadmin"

# Number of rounds -- 4 rounds at ~5 min each = ~20 minutes of metrics
ROUNDS=4

# Throttle rates per round (bytes/sec). Varying these creates visible throughput
# pattern changes in the Grafana charts.
#   Round 1: 30 MB/s  (slow start)
#   Round 2: 60 MB/s  (ramp up)
#   Round 3: 40 MB/s  (dip)
#   Round 4: 80 MB/s  (fast finish)
THROTTLE_RATES=(31457280 62914560 41943040 83886080)

# Resolve godwit binary: PATH first, then ./godwit in CWD, then ./godwit in lab root
if command -v godwit &>/dev/null; then
  GODWIT=godwit
elif [[ -x "./godwit" ]]; then
  GODWIT="./godwit"
elif [[ -x "${LAB_ROOT}/godwit" ]]; then
  GODWIT="${LAB_ROOT}/godwit"
else
  echo "Error: godwit binary not found on PATH, in CWD, or at ${LAB_ROOT}/godwit" >&2
  exit 1
fi

# Print the command being executed (shows "godwit" regardless of resolved path)
run() {
  echo ""
  echo "  \$ godwit $*"
  echo ""
  "${GODWIT}" "$@"
}

# -- Ensure MinIO 2 has the demo-bucket ----------------------------------------
echo "==> Creating 'demo-bucket' on MinIO 2 (if needed) ..."
python3 -c "
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
s3 = boto3.client('s3', endpoint_url='http://${MINIO2_ENDPOINT}',
    aws_access_key_id='${MINIO2_AK}', aws_secret_access_key='${MINIO2_SK}',
    config=Config(signature_version='s3v4'), region_name='us-east-1')
try:
    s3.create_bucket(Bucket='demo-bucket')
    print('  Created demo-bucket on MinIO 2')
except ClientError as e:
    if e.response['Error']['Code'] in ('BucketAlreadyOwnedByYou','BucketAlreadyExists'):
        print('  demo-bucket already exists on MinIO 2 -- OK')
    else:
        raise
"

echo ""
echo "==========================================="
echo "  Round-Trip Migration with Grafana"
echo "  ${ROUNDS} rounds x 3 hops + version"
echo "  history (~20 minutes)"
echo "==========================================="
echo ""
echo "  Grafana:     http://localhost:3000"
echo "  Prometheus:  http://localhost:9090"
echo "  Metrics:     http://localhost:9091/metrics"
echo ""

for ROUND in $(seq 1 "${ROUNDS}"); do
  BPS=${THROTTLE_RATES[$((ROUND - 1))]}
  BPS_MB=$(( BPS / 1048576 ))
  PREFIX="round-${ROUND}"

  echo ""
  echo "==========================================="
  echo "  Round ${ROUND}/${ROUNDS}  (throttle: ${BPS_MB} MB/s)"
  echo "  S3 prefix: ${PREFIX}/"
  echo "==========================================="

  # -- HOP 1: Local FS -> MinIO 1 ---------------------------------------------
  echo ""
  echo "--- Round ${ROUND} / Hop 1: fs -> MinIO 1 ---"

  echo "--> Plan"
  run sync \
    --source "${LAB_ROOT}/data/seed" \
    --destination "s3://demo-bucket/${PREFIX}" \
    --destination-endpoint "${MINIO1_ENDPOINT}" \
    --destination-access-key "${MINIO1_AK}" \
    --destination-secret-key "${MINIO1_SK}" \
    --destination-secure=false \
    --state-path "${STATE_DB}" \
    --run-id "r${ROUND}-hop1" \
    --plan-only \
    --status-addr :9091 \
    --drain-timeout 15 \
    --brief

  echo "--> Execute"
  run sync \
    --source "${LAB_ROOT}/data/seed" \
    --destination "s3://demo-bucket/${PREFIX}" \
    --destination-endpoint "${MINIO1_ENDPOINT}" \
    --destination-access-key "${MINIO1_AK}" \
    --destination-secret-key "${MINIO1_SK}" \
    --destination-secure=false \
    --state-path "${STATE_DB}" \
    --run-id "r${ROUND}-hop1" \
    --resume \
    --read-bps "${BPS}" \
    --status-addr :9091 \
    --drain-timeout 15 \
    --brief

  echo "--> Inspect"
  run plan inspect \
    --run-id "r${ROUND}-hop1" \
    --state-path "${STATE_DB}"

  # -- HOP 2: MinIO 1 -> MinIO 2 ----------------------------------------------
  echo ""
  echo "--- Round ${ROUND} / Hop 2: MinIO 1 -> MinIO 2 ---"
  echo "    Metrics at http://localhost:9091/metrics"

  echo "--> Plan"
  run sync \
    --source "s3://demo-bucket/${PREFIX}" \
    --source-endpoint "${MINIO1_ENDPOINT}" \
    --source-access-key "${MINIO1_AK}" \
    --source-secret-key "${MINIO1_SK}" \
    --source-secure=false \
    --destination "s3://demo-bucket/${PREFIX}" \
    --destination-endpoint "${MINIO2_ENDPOINT}" \
    --destination-access-key "${MINIO2_AK}" \
    --destination-secret-key "${MINIO2_SK}" \
    --destination-secure=false \
    --skip-tags \
    --skip .md5 \
    --state-path "${STATE_DB}" \
    --run-id "r${ROUND}-hop2" \
    --plan-only \
    --status-addr :9091 \
    --drain-timeout 15 \
    --brief

  echo "--> Execute"
  run sync \
    --source "s3://demo-bucket/${PREFIX}" \
    --source-endpoint "${MINIO1_ENDPOINT}" \
    --source-access-key "${MINIO1_AK}" \
    --source-secret-key "${MINIO1_SK}" \
    --source-secure=false \
    --destination "s3://demo-bucket/${PREFIX}" \
    --destination-endpoint "${MINIO2_ENDPOINT}" \
    --destination-access-key "${MINIO2_AK}" \
    --destination-secret-key "${MINIO2_SK}" \
    --destination-secure=false \
    --skip-tags \
    --state-path "${STATE_DB}" \
    --run-id "r${ROUND}-hop2" \
    --resume \
    --read-bps "${BPS}" \
    --status-addr :9091 \
    --drain-timeout 15 \
    --brief

  echo "--> Inspect"
  run plan inspect \
    --run-id "r${ROUND}-hop2" \
    --state-path "${STATE_DB}"

  # -- HOP 3: MinIO 2 -> Local FS ---------------------------------------------
  echo ""
  echo "--- Round ${ROUND} / Hop 3: MinIO 2 -> fs ---"

  RESTORE_DIR="${LAB_ROOT}/data/restored-${ROUND}"
  mkdir -p "${RESTORE_DIR}"

  echo "--> Plan"
  run sync \
    --source "s3://demo-bucket/${PREFIX}" \
    --source-endpoint "${MINIO2_ENDPOINT}" \
    --source-access-key "${MINIO2_AK}" \
    --source-secret-key "${MINIO2_SK}" \
    --source-secure=false \
    --skip-tags \
    --skip .md5 \
    --destination "${RESTORE_DIR}" \
    --state-path "${STATE_DB}" \
    --run-id "r${ROUND}-hop3" \
    --plan-only \
    --status-addr :9091 \
    --drain-timeout 10 \
    --brief

  echo "--> Execute"
  run sync \
    --source "s3://demo-bucket/${PREFIX}" \
    --source-endpoint "${MINIO2_ENDPOINT}" \
    --source-access-key "${MINIO2_AK}" \
    --source-secret-key "${MINIO2_SK}" \
    --source-secure=false \
    --skip-tags \
    --destination "${RESTORE_DIR}" \
    --state-path "${STATE_DB}" \
    --run-id "r${ROUND}-hop3" \
    --resume \
    --read-bps "${BPS}" \
    --status-addr :9091 \
    --drain-timeout 15 \
    --brief

  echo "--> Inspect"
  run plan inspect \
    --run-id "r${ROUND}-hop3" \
    --state-path "${STATE_DB}"

  # -- Verify hop2 checksums for this round -----------------------------------
  echo ""
  echo "--- Round ${ROUND} / Verify hop2 checksums ---"
  run plan verify \
    --run-id "r${ROUND}-hop2" \
    --destination "s3://demo-bucket/${PREFIX}" \
    --destination-endpoint "${MINIO2_ENDPOINT}" \
    --destination-access-key "${MINIO2_AK}" \
    --destination-secret-key "${MINIO2_SK}" \
    --destination-secure=false \
    --skip-tags \
    --state-path "${STATE_DB}" \
    --status-addr :9091 \
    --drain-timeout 15 \
    --brief

  # -- Version History: MinIO 1 -> MinIO 1 (all versions) ---------------------
  echo ""
  echo "--- Round ${ROUND} / Version History: MinIO 1 -> MinIO 1 ---"
  echo "    versioned-src -> versioned-dst (--version-mode all)"

  echo "--> Plan"
  run sync \
    --source s3://versioned-src \
    --source-endpoint "${MINIO1_ENDPOINT}" \
    --source-access-key "${MINIO1_AK}" \
    --source-secret-key "${MINIO1_SK}" \
    --source-secure=false \
    --destination s3://versioned-dst \
    --destination-endpoint "${MINIO1_ENDPOINT}" \
    --destination-access-key "${MINIO1_AK}" \
    --destination-secret-key "${MINIO1_SK}" \
    --destination-secure=false \
    --state-path "${STATE_DB}" \
    --run-id "r${ROUND}-vhist" \
    --version-mode all \
    --plan-only \
    --status-addr :9091 \
    --drain-timeout 15 \
    --brief

  echo "--> Execute"
  run sync \
    --source s3://versioned-src \
    --source-endpoint "${MINIO1_ENDPOINT}" \
    --source-access-key "${MINIO1_AK}" \
    --source-secret-key "${MINIO1_SK}" \
    --source-secure=false \
    --destination s3://versioned-dst \
    --destination-endpoint "${MINIO1_ENDPOINT}" \
    --destination-access-key "${MINIO1_AK}" \
    --destination-secret-key "${MINIO1_SK}" \
    --destination-secure=false \
    --state-path "${STATE_DB}" \
    --run-id "r${ROUND}-vhist" \
    --version-mode all \
    --resume \
    --read-bps "${BPS}" \
    --status-addr :9091 \
    --drain-timeout 15 \
    --brief

  echo "--> Inspect"
  run plan inspect \
    --run-id "r${ROUND}-vhist" \
    --state-path "${STATE_DB}"

done

# -- Object Lock Migration ----------------------------------------------------
OL_STATE_DB="${LAB_ROOT}/object-lock.state.db"

echo ""
echo "==========================================="
echo "  Object Lock Migration"
echo "  ol-src -> ol-dst (MinIO 1)"
echo "  --object-lock --version-mode all"
echo "==========================================="

echo "--> Plan + Execute"
run sync \
  --source s3://ol-src \
  --source-endpoint "${MINIO1_ENDPOINT}" \
  --source-access-key "${MINIO1_AK}" \
  --source-secret-key "${MINIO1_SK}" \
  --source-secure=false \
  --destination s3://ol-dst \
  --destination-endpoint "${MINIO1_ENDPOINT}" \
  --destination-access-key "${MINIO1_AK}" \
  --destination-secret-key "${MINIO1_SK}" \
  --destination-secure=false \
  --state-path "${OL_STATE_DB}" \
  --run-id object-lock \
  --version-mode all \
  --object-lock \
  --status-addr :9091 \
  --drain-timeout 15 \
  --brief

echo "--> Inspect"
run plan inspect \
  --run-id object-lock \
  --state-path "${OL_STATE_DB}"

# -- All runs summary ---------------------------------------------------------
echo ""
echo "--- All runs --------------------------------"
run plan list \
  --state-path "${STATE_DB}"
run plan list \
  --state-path "${OL_STATE_DB}"

echo ""
echo "==========================================="
echo "  All migrations complete."
echo "  ${ROUNDS} rounds x (3 hops + version history)"
echo "  + 1 object-lock migration."
echo "  Check Grafana at http://localhost:3000"
echo "  for the full migration dashboard."
echo "  Set time range to 'Last 30 minutes'"
echo "  to see all runs."
echo "==========================================="
echo "==========================================="
