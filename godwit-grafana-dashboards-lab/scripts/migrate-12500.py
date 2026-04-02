#!/usr/bin/env python3
# Copyright (c) 2026 Godwit.io
#
# Licensed under the MIT License. You may obtain a copy of the License at
#
#     https://opensource.org/licenses/MIT
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""
migrate-12500.py -- Migrate 12 500 object versions from MinIO 1 to MinIO 2
and verify.

  MinIO 1 :8000 (many-src) -> MinIO 2 :8002 (many-dst)   s3-to-s3
  --version-mode all  (700 multi-version keys with 10 versions each)
  --object-lock       (200 keys with GOVERNANCE retention or legal hold)
  followed by plan verify

Throttle is set low (5 MB/s) so the migration takes visible time in Grafana.

Prerequisites:
  docker compose -f infra/docker-compose.yml up -d
  python3 scripts/seed-data-12500.py
"""

import os
import shutil
import subprocess
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

LAB_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_DB = os.path.join(LAB_ROOT, "many.state.db")

# MinIO 1 (source) -- port 8000
MINIO1_ENDPOINT = "localhost:8000"
MINIO1_AK       = "minioadmin"
MINIO1_SK       = "minioadmin"

# MinIO 2 (destination) -- port 8002
MINIO2_ENDPOINT = "localhost:8002"
MINIO2_AK       = "minioadmin"
MINIO2_SK       = "minioadmin"

MANY_DST = "many-dst"

# 5 MB/s -- slow enough that 12 500 versions (~44 GB) take extended time
BPS = "5242880"


def find_godwit() -> str:
    """Resolve the godwit binary."""
    if shutil.which("godwit"):
        return "godwit"
    local = os.path.join(".", "godwit")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    lab = os.path.join(LAB_ROOT, "godwit")
    if os.path.isfile(lab) and os.access(lab, os.X_OK):
        return lab
    # Windows: check for .exe
    for p in [local + ".exe", lab + ".exe"]:
        if os.path.isfile(p):
            return p
    print("Error: godwit binary not found on PATH, in CWD, or at", lab, file=sys.stderr)
    sys.exit(1)


def s3_client_minio2():
    return boto3.client(
        "s3",
        endpoint_url          = f"http://{MINIO2_ENDPOINT}",
        aws_access_key_id     = MINIO2_AK,
        aws_secret_access_key = MINIO2_SK,
        config                = Config(signature_version="s3v4"),
        region_name           = "us-east-1",
    )


def ensure_dst_bucket() -> None:
    """Create many-dst on MinIO 2 with Object Lock enabled (idempotent)."""
    s3 = s3_client_minio2()
    try:
        s3.create_bucket(Bucket=MANY_DST, ObjectLockEnabledForBucket=True)
        print("    Created bucket 'many-dst' on MinIO 2 (Object Lock + versioning enabled)")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print("    Bucket 'many-dst' already exists on MinIO 2 -- OK")
        else:
            raise


def run(godwit: str, *args: str) -> None:
    """Run a godwit command, printing it first."""
    cmd = [godwit] + list(args)
    print(f"\n  $ godwit {' '.join(args)}\n")
    subprocess.run(cmd, check=True)


def main() -> None:
    godwit = find_godwit()

    # -- Ensure MinIO 2 has the many-dst bucket with Object Lock ---------------
    print("==> Creating MinIO 2 bucket 'many-dst' (if needed) ...")
    ensure_dst_bucket()

    bps_mb = int(BPS) // 1_048_576
    multi_keys = 700
    single_keys = 5_500
    total_keys = multi_keys + single_keys
    total_versions = 12_500
    print(f"""
===========================================
  Large Migration: {total_versions} versions
  {total_keys} keys ({multi_keys} multi-version, {single_keys} single)
  MinIO 1 :8000 (many-src) -> MinIO 2 :8002 (many-dst)
  --version-mode all  --object-lock
  Throttle: {bps_mb} MB/s
===========================================

  Grafana:     http://localhost:3000
  Prometheus:  http://localhost:9090
  Metrics:     http://localhost:9091/metrics
""")

    # -- Migrate: MinIO 1 -> MinIO 2 (s3-to-s3) --------------------------------
    print("\n--- MinIO 1 (many-src) -> MinIO 2 (many-dst) ---")

    common_src = [
        "--source", "s3://many-src",
        "--source-endpoint", MINIO1_ENDPOINT,
        "--source-access-key", MINIO1_AK,
        "--source-secret-key", MINIO1_SK,
        "--source-secure=false",
    ]
    common_dst = [
        "--destination", "s3://many-dst",
        "--destination-endpoint", MINIO2_ENDPOINT,
        "--destination-access-key", MINIO2_AK,
        "--destination-secret-key", MINIO2_SK,
        "--destination-secure=false",
    ]
    common_flags = [
        "--skip-tags",
        "--state-path", STATE_DB,
        "--run-id", "many-12500",
        "--status-addr", ":9091",
        "--drain-timeout", "15",
        "--version-mode", "all",
        "--object-lock",
        "--brief",
    ]

    print("--> Plan")
    run(godwit, "sync", *common_src, *common_dst, *common_flags, "--plan-only")

    print("--> Execute")
    run(godwit, "sync", *common_src, *common_dst, *common_flags,
        "--resume", "--read-bps", BPS)

    print("--> Inspect")
    run(godwit, "plan", "inspect",
        "--run-id", "many-12500", "--state-path", STATE_DB)

    # -- Verify checksums ------------------------------------------------------
    print("\n--- Verify checksums ---")
    run(godwit, "plan", "verify",
        "--run-id", "many-12500",
        *common_dst,
        "--skip-tags",
        "--state-path", STATE_DB,
        "--status-addr", ":9091",
        "--drain-timeout", "15",
        "--brief")

    # -- Summary ---------------------------------------------------------------
    print("\n--- Run summary --------------------------------")
    run(godwit, "plan", "list", "--state-path", STATE_DB)

    print(f"""
===========================================
  Migration complete.
  {total_versions} versions ({total_keys} keys)
  MinIO 1 :8000 -> MinIO 2 :8002
  --version-mode all  --object-lock
  Verified.
  Check Grafana at http://localhost:3000
===========================================""")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"\nERROR: command failed with exit code {exc.returncode}", file=sys.stderr)
        sys.exit(exc.returncode)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
