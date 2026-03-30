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

# migrate-versions.sh — Demonstrate version history migration with mixed storage classes.
#
# Source: Moto (:5555) — AWS S3 mock that supports GLACIER storage class
# Destination: MinIO (:8000) — receives STANDARD versions; GLACIER versions are skipped
#
# Steps:
#   1. Plan + execute --version-mode all (full history, mixed storage classes)
#   2. Inspect version completeness (partial/complete/fully_skipped per key)
#   3. List keys with partial version history (GLACIER gaps)
#   4. Plan + execute --version-mode since: (point-in-time)
#   5. Verify checksums
#
# Prerequisites:
#   docker compose -f infra/docker-compose.yml up -d
#   python3 scripts/seed-versioned-data.py

set -euo pipefail

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DB="${LAB_ROOT}/godwit.state.db"

# Resolve godwit binary: PATH first, then ./godwit in the lab root
if command -v godwit &>/dev/null; then
  GODWIT=godwit
elif [[ -x "${LAB_ROOT}/godwit" ]]; then
  GODWIT="${LAB_ROOT}/godwit"
else
  echo "Error: godwit binary not found on PATH or at ${LAB_ROOT}/godwit" >&2
  exit 1
fi

# Print the command being executed (shows "godwit" regardless of resolved path)
run() {
  echo ""
  echo "  \$ godwit $*"
  echo ""
  "${GODWIT}" "$@"
}

# Moto source (AWS S3 mock — supports GLACIER in listings)
SRC_ENDPOINT="localhost:5555"
SRC_ACCESS_KEY="testing"
SRC_SECRET_KEY="testing"

# MinIO destination
DST_ENDPOINT="localhost:8000"
DST_ACCESS_KEY="minioadmin"
DST_SECRET_KEY="minioadmin"

echo ""
echo "==========================================="
echo "  S3 Version History Migration Lab"
echo "  Source: Moto (:5555)  →  Dest: MinIO (:8000)"
echo "==========================================="

# ── STEP 1: Full version history migration ───────────────────────────────────
echo ""
echo "─── Step 1: Full version history migration ──"
echo "    source-versioned (Moto) → dest-versioned (MinIO)"
echo "    --version-mode all"
echo "    STANDARD versions will be copied; GLACIER versions will be skipped"

echo "--> Plan"
run sync \
  --source s3://source-versioned \
  --source-endpoint "${SRC_ENDPOINT}" \
  --source-access-key "${SRC_ACCESS_KEY}" \
  --source-secret-key "${SRC_SECRET_KEY}" \
  --source-secure=false \
  --destination s3://dest-versioned \
  --destination-endpoint "${DST_ENDPOINT}" \
  --destination-access-key "${DST_ACCESS_KEY}" \
  --destination-secret-key "${DST_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --run-id version-all \
  --version-mode all \
  --plan-only \
  --brief

echo "--> Inspect plan (note: storage class breakdown and glacier warnings)"
run plan inspect \
  --run-id version-all \
  --state-path "${STATE_DB}"

echo "--> Execute"
run sync \
  --source s3://source-versioned \
  --source-endpoint "${SRC_ENDPOINT}" \
  --source-access-key "${SRC_ACCESS_KEY}" \
  --source-secret-key "${SRC_SECRET_KEY}" \
  --source-secure=false \
  --destination s3://dest-versioned \
  --destination-endpoint "${DST_ENDPOINT}" \
  --destination-access-key "${DST_ACCESS_KEY}" \
  --destination-secret-key "${DST_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --run-id version-all \
  --version-mode all \
  --resume \
  --brief

echo "--> Inspect result (shows version history completeness per key)"
run plan inspect \
  --run-id version-all \
  --state-path "${STATE_DB}"

# ── STEP 2: Version completeness check ──────────────────────────────────────
echo ""
echo "─── Step 2: Version completeness ─────────────"
echo "    Keys with partial history have some GLACIER versions that were skipped."
echo "    Keys with complete history had all STANDARD versions — all copied."
echo "    Keys fully skipped had only GLACIER versions — nothing to copy."

echo "--> List keys with partial version history"
run plan list objects all \
  --partial-history \
  --run-id version-all \
  --state-path "${STATE_DB}" || echo "    (no partial histories found)"

# ── STEP 3: List glacier-skipped objects ─────────────────────────────────────
echo ""
echo "─── Step 3: Glacier-skipped objects ──────────"
echo "    These specific versions were skipped because they are in GLACIER storage class."

run plan list objects glacier \
  --run-id version-all \
  --state-path "${STATE_DB}" || echo "    (no glacier objects found)"

# ── STEP 4: Point-in-time migration ─────────────────────────────────────────
echo ""
echo "─── Step 4: Point-in-time migration ──────────"
echo "    source-versioned (Moto) → pit-bucket (MinIO)"
echo "    --version-mode since: (last 2 minutes)"

# Read the midpoint timestamp written by seed-versioned-data.py
SINCE_FILE="${LAB_ROOT}/since-timestamp.txt"
if [[ ! -f "${SINCE_FILE}" ]]; then
  echo "Error: ${SINCE_FILE} not found. Run seed-versioned-data.py first." >&2
  exit 1
fi
SINCE_TIME=$(<"${SINCE_FILE}")
echo "    since: ${SINCE_TIME} (from since-timestamp.txt)"

echo "--> Plan"
run sync \
  --source s3://source-versioned \
  --source-endpoint "${SRC_ENDPOINT}" \
  --source-access-key "${SRC_ACCESS_KEY}" \
  --source-secret-key "${SRC_SECRET_KEY}" \
  --source-secure=false \
  --destination s3://pit-bucket \
  --destination-endpoint "${DST_ENDPOINT}" \
  --destination-access-key "${DST_ACCESS_KEY}" \
  --destination-secret-key "${DST_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --run-id version-since \
  --version-mode "since:${SINCE_TIME}" \
  --plan-only \
  --brief

echo "--> Inspect plan (should show fewer versions than full migration)"
run plan inspect \
  --run-id version-since \
  --state-path "${STATE_DB}"

echo "--> Execute"
run sync \
  --source s3://source-versioned \
  --source-endpoint "${SRC_ENDPOINT}" \
  --source-access-key "${SRC_ACCESS_KEY}" \
  --source-secret-key "${SRC_SECRET_KEY}" \
  --source-secure=false \
  --destination s3://pit-bucket \
  --destination-endpoint "${DST_ENDPOINT}" \
  --destination-access-key "${DST_ACCESS_KEY}" \
  --destination-secret-key "${DST_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --run-id version-since \
  --version-mode "since:${SINCE_TIME}" \
  --resume \
  --brief

echo "--> Inspect result"
run plan inspect \
  --run-id version-since \
  --state-path "${STATE_DB}"

# ── STEP 5: Verify ──────────────────────────────────────────────────────────
echo ""
echo "─── Step 5: Verify full migration checksums ──"
run plan verify \
  --run-id version-all \
  --destination s3://dest-versioned \
  --destination-endpoint "${DST_ENDPOINT}" \
  --destination-access-key "${DST_ACCESS_KEY}" \
  --destination-secret-key "${DST_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --brief

# ── STEP 6: Object Lock migration ────────────────────────────────────────────
echo ""
echo "─── Step 6: Object Lock migration ──────────"
echo "    ol-lab-src (MinIO) → ol-lab-dst (MinIO)"
echo "    --object-lock --version-mode all"
echo "    Retention and legal hold replicated per-version"

OL_STATE_DB="${LAB_ROOT}/object-lock.state.db"

echo "--> Plan + execute"
run sync \
  --source s3://ol-lab-src \
  --source-endpoint "${DST_ENDPOINT}" \
  --source-access-key "${DST_ACCESS_KEY}" \
  --source-secret-key "${DST_SECRET_KEY}" \
  --source-secure=false \
  --destination s3://ol-lab-dst \
  --destination-endpoint "${DST_ENDPOINT}" \
  --destination-access-key "${DST_ACCESS_KEY}" \
  --destination-secret-key "${DST_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${OL_STATE_DB}" \
  --run-id object-lock-test \
  --version-mode all \
  --object-lock \
  --brief

echo "--> Inspect (note: Object Lock summary section)"
run plan inspect \
  --run-id object-lock-test \
  --state-path "${OL_STATE_DB}"

# ── STEP 7: Object Lock pre-flight rejection ─────────────────────────────────
echo ""
echo "─── Step 7: Object Lock pre-flight rejection ──"
echo "    --object-lock against dest-versioned (no Object Lock) → expects failure"

echo ""
echo "  \$ godwit sync --source s3://ol-lab-src --destination s3://dest-versioned --object-lock --plan-only --brief"
echo ""
"${GODWIT}" sync \
  --source s3://ol-lab-src \
  --source-endpoint "${DST_ENDPOINT}" \
  --source-access-key "${DST_ACCESS_KEY}" \
  --source-secret-key "${DST_SECRET_KEY}" \
  --source-secure=false \
  --destination s3://dest-versioned \
  --destination-endpoint "${DST_ENDPOINT}" \
  --destination-access-key "${DST_ACCESS_KEY}" \
  --destination-secret-key "${DST_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${OL_STATE_DB}" \
  --run-id object-lock-fail-test \
  --object-lock \
  --plan-only \
  --brief 2>&1 && echo "  ERROR: should have failed!" || echo "  ✓ Correctly rejected: destination bucket lacks Object Lock"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "─── All runs ───────────────────────────────"
run plan list \
  --state-path "${STATE_DB}"
run plan list \
  --state-path "${OL_STATE_DB}"

echo ""
echo "==========================================="
echo "  Version history migration complete."
echo ""
echo "  version-all:   full history migrated"
echo "    - STANDARD versions:  copied"
echo "    - GLACIER versions:   skipped (reported)"
echo "    - Delete markers:     replicated"
echo ""
echo "  version-since: point-in-time migrated"
echo ""
echo "  object-lock:   Object Lock metadata replicated"
echo "    - GOVERNANCE retention: copied"
echo "    - COMPLIANCE retention: copied"
echo "    - Legal hold:           copied"
echo "    - Non-lock bucket:      rejected (pre-flight)"
echo "==========================================="
