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
# migrate.sh — Run all three S3 migration use cases:
#   upload:   local FS  → MinIO   (fs-to-s3, basic sync with --ui)
#   transfer: MinIO     → Garage  (s3-to-s3, plan-first with --plan-only then --resume)
#   download: Garage    → local FS (s3-to-fs, with live HTTP status via --status-addr)
# Then inspect each run and verify transfer checksums.
#
# Prerequisites:
#   docker compose -f infra/docker-compose.yml up -d
#   python3 scripts/seed-data.py
#   bash scripts/init-minio.sh
#   bash scripts/init-garage.sh

set -euo pipefail

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CREDENTIALS_FILE="${LAB_ROOT}/.credentials"
STATE_DB="${LAB_ROOT}/godwit.state.db"

# ── Resolve godwit binary ────────────────────────────────────────────────────
if command -v godwit >/dev/null 2>&1; then
  GODWIT=godwit
elif [[ -x "${LAB_ROOT}/godwit" ]]; then
  GODWIT="${LAB_ROOT}/godwit"
elif [[ -x "${LAB_ROOT}/godwit.exe" ]]; then
  GODWIT="${LAB_ROOT}/godwit.exe"
else
  echo "ERROR: godwit not found on PATH or in ${LAB_ROOT}"
  echo "Install Godwit Sync from https://godwit.io/docs/quickstart"
  exit 1
fi

# ── Load Garage credentials ────────────────────────────────────────────────────
if [[ ! -f "${CREDENTIALS_FILE}" ]]; then
  echo "ERROR: .credentials not found."
  echo "Run scripts/init-garage.sh first."
  exit 1
fi
# shellcheck source=/dev/null
source "${CREDENTIALS_FILE}"

echo ""
echo "==========================================="
echo "  S3 Migration Guide"
echo "  Upload · Transfer · Download"
echo "==========================================="

# ── USE CASE 1: Upload — Local FS → MinIO ────────────────────────────────────
# Demonstrates: basic godwit sync with --ui for live terminal progress.
# Single command — plans and executes in one step.
echo ""
echo "─── Use Case 1: Upload (fs → S3) ────────────"

# NOTE: --read-bps is set to ~50 MB/s for demo purposes so you can observe
# the transfer in real time. Remove it for maximum throughput.
"${GODWIT}" sync \
  --source "${LAB_ROOT}/data/seed" \
  --destination s3://demo-bucket \
  --destination-endpoint localhost:8000 \
  --destination-access-key minioadmin \
  --destination-secret-key minioadmin \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --run-id upload \
  --read-bps 52428800 \
  --status-addr :8888 \
  --brief

echo "--> Status"
"${GODWIT}" plan inspect \
  --run-id upload \
  --state-path "${STATE_DB}"

# ── USE CASE 2: Transfer — MinIO → Garage ────────────────────────────────────
# Demonstrates: plan-first workflow with --plan-only, then --resume.
echo ""
echo "─── Use Case 2: Transfer (S3 → S3) ──────────"

echo "--> Step 1: Plan (no data copied yet)"
"${GODWIT}" sync \
  --source s3://demo-bucket \
  --source-endpoint localhost:8000 \
  --source-access-key minioadmin \
  --source-secret-key minioadmin \
  --source-secure=false \
  --destination s3://demo-bucket \
  --destination-endpoint localhost:3900 \
  --destination-access-key "${GARAGE_ACCESS_KEY}" \
  --destination-secret-key "${GARAGE_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --run-id transfer \
  --skip .md5 \
  --skip-tags \
  --plan-only \
  --status-addr :8888 \
  --brief

echo "--> Inspect the plan"
"${GODWIT}" plan inspect \
  --run-id transfer \
  --state-path "${STATE_DB}"

# NOTE: --read-bps is set to ~50 MB/s for demo purposes so you can observe
# the transfer in real time. Remove it for maximum throughput.
echo "--> Step 2: Execute with --resume"
"${GODWIT}" sync \
  --source s3://demo-bucket \
  --source-endpoint localhost:8000 \
  --source-access-key minioadmin \
  --source-secret-key minioadmin \
  --source-secure=false \
  --destination s3://demo-bucket \
  --destination-endpoint localhost:3900 \
  --destination-access-key "${GARAGE_ACCESS_KEY}" \
  --destination-secret-key "${GARAGE_SECRET_KEY}" \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --run-id transfer \
  --resume \
  --skip-tags \
  --read-bps 52428800 \
  --status-addr :8888 \
  --brief

echo "--> Status"
"${GODWIT}" plan inspect \
  --run-id transfer \
  --state-path "${STATE_DB}"

# ── USE CASE 3: Download — Garage → Local FS ─────────────────────────────────
# Demonstrates: --status-addr for live HTTP progress monitoring.
echo ""
echo "─── Use Case 3: Download (S3 → fs) ──────────"
echo "    (HTTP status available at http://localhost:8080/status while running)"

mkdir -p "${LAB_ROOT}/data/restored"

# NOTE: --read-bps is set to ~50 MB/s for demo purposes so you can observe
# the transfer in real time. Remove it for maximum throughput.
"${GODWIT}" sync \
  --source s3://demo-bucket \
  --source-endpoint localhost:3900 \
  --source-access-key "${GARAGE_ACCESS_KEY}" \
  --source-secret-key "${GARAGE_SECRET_KEY}" \
  --source-secure=false \
  --destination "${LAB_ROOT}/data/restored" \
  --state-path "${STATE_DB}" \
  --run-id download \
  --skip .md5 \
  --skip-tags \
  --read-bps 52428800 \
  --status-addr :8888 \
  --brief

echo "--> Status"
"${GODWIT}" plan inspect \
  --run-id download \
  --state-path "${STATE_DB}"

# ── All runs summary ──────────────────────────────────────────────────────────
echo ""
echo "─── All runs ───────────────────────────────"
"${GODWIT}" plan list \
  --state-path "${STATE_DB}"

# ── Verify transfer checksums ─────────────────────────────────────────────────
echo ""
echo "─── Verify upload checksums ──────────────────"
"${GODWIT}" plan verify \
  --run-id upload \
  --destination s3://demo-bucket \
  --destination-endpoint localhost:8000 \
  --destination-access-key minioadmin \
  --destination-secret-key minioadmin \
  --destination-secure=false \
  --state-path "${STATE_DB}" \
  --brief


echo ""
echo "==========================================="
echo "  All three use cases complete."
echo "==========================================="
