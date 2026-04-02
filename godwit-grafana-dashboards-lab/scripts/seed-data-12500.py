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
seed-data-12500.py -- Seed 12 500 object versions into MinIO for the
large-migration Grafana-dashboard demo.

Creates:
  1. many-src bucket (Object Lock enabled, versioning automatic):
     - 6 200 unique keys across 62 directories
     -   700 keys with 10 versions each (7 000 versions)
     - 5 500 keys with 1 version each  (5 500 versions)
     - Total: 12 500 versions
     - ~625 large versions (65-75 MB each), rest small (4-64 KB)
     - 200 keys with Object Lock (100 GOVERNANCE, 100 legal hold)
     Total: ~44 GB expected, 48 GB max
  2. many-dst bucket -- empty destination bucket.

The companion script  migrate-12500.py  consumes these buckets.
"""

import hashlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# -- Configuration -----------------------------------------------------------

MINIO_ENDPOINT   = "http://localhost:8000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"

MANY_SRC = "many-src"
MANY_DST = "many-dst"

# 6 200 unique keys: 62 directories x 100 keys each.
# First 7 dirs (700 keys) carry 10 versions each; remaining 55 dirs are
# single-version.  700 * 10 + 5 500 * 1 = 12 500 total versions.
NUM_DIRS               = 62
FILES_PER_DIR          = 100
MULTI_VERSION_DIRS     = 7          # dirs 0-6
VERSIONS_PER_MULTI_KEY = 10
TOTAL_VERSIONS         = 12_500

MIN_SIZE       = 4_096      #   4 KB
MAX_SIZE       = 65_536     #  64 KB
UPLOAD_WORKERS = 32

# Every 20th version (flat index) is large (65-75 MB).
# 12 500 / 20 = 625 large versions.
# Worst case: 625 x 75 MB + 11 875 x 64 KB ≈ 47.6 GB < 48 GB.
LARGE_EVERY   = 20
LARGE_MIN     = 68_157_440    #  65 MB
LARGE_MAX     = 78_643_200    #  75 MB
PART_SIZE     = 33_554_432    # 32 MB -- upload chunk for large objects

# Object Lock: 100 keys with GOVERNANCE retention, 100 with legal hold.
OL_GOVERNANCE_DIR  = 7     # batch-0007/  (100 single-version keys)
OL_LEGAL_HOLD_DIR  = 8     # batch-0008/  (100 single-version keys)
OL_RETENTION_DAYS  = 1


# -- Helpers -----------------------------------------------------------------

def deterministic_content(seed_str: str, size: int) -> bytes:
    h = hashlib.sha256(seed_str.encode()).digest()
    pieces, total, piece = [], 0, h
    while total < size:
        piece = hashlib.sha256(piece).digest()
        pieces.append(piece)
        total += len(piece)
    return b"".join(pieces)[:size]


def deterministic_size(seed_str: str, lo: int, hi: int) -> int:
    h = int.from_bytes(hashlib.md5(seed_str.encode()).digest()[:4], "big")
    return lo + (h % (hi - lo + 1))


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url          = MINIO_ENDPOINT,
        aws_access_key_id     = MINIO_ACCESS_KEY,
        aws_secret_access_key = MINIO_SECRET_KEY,
        config                = Config(signature_version="s3v4"),
        region_name           = "us-east-1",
    )


def create_object_lock_bucket(s3, bucket: str) -> None:
    """Create a bucket with Object Lock enabled (versioning is automatic)."""
    try:
        s3.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
        print(f"  Created bucket '{bucket}' (Object Lock + versioning enabled)")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"  Bucket '{bucket}' already exists -- OK")
        else:
            raise


def create_bucket(s3, bucket: str) -> None:
    try:
        s3.create_bucket(Bucket=bucket)
        print(f"  Created bucket '{bucket}'")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"  Bucket '{bucket}' already exists -- OK")
        else:
            raise


# -- Upload logic ------------------------------------------------------------

def _upload_key(args) -> int:
    """Upload all versions of a single key. Returns version count."""
    key, num_versions, first_vi = args
    client = _upload_key._local_client
    if client is None:
        client = s3_client()
        _upload_key._local_client = client

    for v in range(num_versions):
        vi = first_vi + v
        seed = f"{key}:v{v + 1}" if num_versions > 1 else key
        is_large = (vi % LARGE_EVERY == 0)
        if is_large:
            size = deterministic_size(seed, LARGE_MIN, LARGE_MAX)
            _upload_multipart(client, key, seed, size)
        else:
            size = deterministic_size(seed, MIN_SIZE, MAX_SIZE)
            body = deterministic_content(seed, size)
            client.put_object(Bucket=MANY_SRC, Key=key, Body=body)

    return num_versions

_upload_key._local_client = None


def _upload_multipart(client, key: str, seed: str, size: int) -> None:
    """Stream a large object via multipart upload (one PART_SIZE chunk at a time)."""
    mpu = client.create_multipart_upload(Bucket=MANY_SRC, Key=key)
    upload_id = mpu["UploadId"]
    parts = []
    offset = 0
    part_num = 1
    try:
        while offset < size:
            chunk_size = min(PART_SIZE, size - offset)
            body = deterministic_content(f"{seed}:{part_num}", chunk_size)
            resp = client.upload_part(
                Bucket=MANY_SRC, Key=key,
                UploadId=upload_id, PartNumber=part_num,
                Body=body,
            )
            parts.append({"ETag": resp["ETag"], "PartNumber": part_num})
            offset += chunk_size
            part_num += 1
        client.complete_multipart_upload(
            Bucket=MANY_SRC, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
    except Exception:
        client.abort_multipart_upload(
            Bucket=MANY_SRC, Key=key, UploadId=upload_id)
        raise


def _init_worker() -> None:
    """Thread initializer: give each worker its own S3 client."""
    _upload_key._local_client = s3_client()


# -- Upload plan -------------------------------------------------------------

def build_upload_plan():
    """Build list of (key, num_versions, first_version_index) tasks."""
    tasks = []
    vi = 0

    # Multi-version keys (dirs 0 .. MULTI_VERSION_DIRS-1)
    for d in range(MULTI_VERSION_DIRS):
        for f in range(FILES_PER_DIR):
            key = f"batch-{d:04d}/obj-{f:04d}.bin"
            tasks.append((key, VERSIONS_PER_MULTI_KEY, vi))
            vi += VERSIONS_PER_MULTI_KEY

    # Single-version keys (dirs MULTI_VERSION_DIRS .. NUM_DIRS-1)
    for d in range(MULTI_VERSION_DIRS, NUM_DIRS):
        for f in range(FILES_PER_DIR):
            key = f"batch-{d:04d}/obj-{f:04d}.bin"
            tasks.append((key, 1, vi))
            vi += 1

    return tasks


# -- Object Lock -------------------------------------------------------------

def apply_object_locks(s3) -> None:
    """Apply GOVERNANCE retention and legal hold to selected keys."""
    retain_until = datetime.now(timezone.utc) + timedelta(days=OL_RETENTION_DAYS)

    print(f"  Applying GOVERNANCE retention to batch-{OL_GOVERNANCE_DIR:04d}/ (100 keys) ...")
    for f in range(FILES_PER_DIR):
        key = f"batch-{OL_GOVERNANCE_DIR:04d}/obj-{f:04d}.bin"
        resp = s3.list_object_versions(Bucket=MANY_SRC, Prefix=key, MaxKeys=1)
        vid = resp["Versions"][0]["VersionId"]
        s3.put_object_retention(
            Bucket=MANY_SRC, Key=key, VersionId=vid,
            Retention={"Mode": "GOVERNANCE", "RetainUntilDate": retain_until},
        )

    print(f"  Applying legal hold to batch-{OL_LEGAL_HOLD_DIR:04d}/ (100 keys) ...")
    for f in range(FILES_PER_DIR):
        key = f"batch-{OL_LEGAL_HOLD_DIR:04d}/obj-{f:04d}.bin"
        resp = s3.list_object_versions(Bucket=MANY_SRC, Prefix=key, MaxKeys=1)
        vid = resp["Versions"][0]["VersionId"]
        s3.put_object_legal_hold(
            Bucket=MANY_SRC, Key=key, VersionId=vid,
            LegalHold={"Status": "ON"},
        )

    print(f"  Done: 100 GOVERNANCE + 100 legal hold")


# -- Seed --------------------------------------------------------------------

def seed_many_objects(s3) -> None:
    multi_keys = MULTI_VERSION_DIRS * FILES_PER_DIR
    single_keys = (NUM_DIRS - MULTI_VERSION_DIRS) * FILES_PER_DIR
    total_keys = multi_keys + single_keys
    multi_versions = multi_keys * VERSIONS_PER_MULTI_KEY
    large = TOTAL_VERSIONS // LARGE_EVERY

    print("\n── Many Objects (12 500 versions) ─────────────────────────\n")
    print(f"  Plan:")
    print(f"    Unique keys:      {total_keys:>6}   across {NUM_DIRS} directories")
    print(f"    Multi-version:    {multi_keys:>6}   x {VERSIONS_PER_MULTI_KEY} = {multi_versions} versions (dirs 0-{MULTI_VERSION_DIRS - 1})")
    print(f"    Single-version:   {single_keys:>6}   (dirs {MULTI_VERSION_DIRS}-{NUM_DIRS - 1})")
    print(f"    Total versions:   {TOTAL_VERSIONS:>6}   ({large} large 65-75 MB, {TOTAL_VERSIONS - large} small 4-64 KB)")
    print(f"    Object Lock:      {200:>6}   (100 GOVERNANCE, 100 legal hold)")
    print(f"    Estimated size:   ~44 GB   (48 GB max)")
    print()

    create_object_lock_bucket(s3, MANY_SRC)
    create_bucket(s3, MANY_DST)

    tasks = build_upload_plan()

    uploaded_versions = 0
    last_half_pct = -1
    bar_width = 40
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS, initializer=_init_worker) as pool:
        futures = {pool.submit(_upload_key, task): task for task in tasks}
        for future in as_completed(futures):
            versions_done = future.result()
            uploaded_versions += versions_done
            half_pct = uploaded_versions * 200 // TOTAL_VERSIONS
            if half_pct != last_half_pct:
                last_half_pct = half_pct
                pct = uploaded_versions * 100 // TOTAL_VERSIONS
                filled = uploaded_versions * bar_width // TOTAL_VERSIONS
                bar = "█" * filled + "░" * (bar_width - filled)
                elapsed = time.monotonic() - t0
                if uploaded_versions > 0:
                    eta = (elapsed / uploaded_versions) * (TOTAL_VERSIONS - uploaded_versions)
                else:
                    eta = 0
                eta_m, eta_s = divmod(int(eta), 60)
                line = f"\r  [{bar}] {pct:>3}%  {uploaded_versions:>6}/{TOTAL_VERSIONS}  ETA {eta_m}m{eta_s:02d}s"
                print(f"{line:<80}", end="", flush=True)

    print(f"\n  Uploaded: {uploaded_versions} versions across {total_keys} keys")

    print("\n── Object Lock ────────────────────────────────────────────\n")
    apply_object_locks(s3)


# -- Main --------------------------------------------------------------------

def main() -> None:
    print("seed-data-12500: seeding MinIO for the large-migration demo\n")

    s3 = s3_client()
    seed_many_objects(s3)

    print(f"\n── Done ───────────────────────────────────────────────────")
    print()
    print("Ready. Run next:")
    print("  python3 scripts/migrate-12500.py")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print("Is MinIO running?  docker compose -f infra/docker-compose.yml up -d",
              file=sys.stderr)
        sys.exit(1)
