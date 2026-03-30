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
seed-versioned-data.py — Seed versioned objects with mixed storage classes.

Uses Moto (AWS S3 mock) as source because it preserves StorageClass in
ListObjectVersions responses and accepts GLACIER on PutObject — unlike
MinIO which rejects GLACIER. MinIO is used as the destination.

Test data (8 keys with deliberately mixed storage classes):

  Key                  Versions (oldest -> newest)           Expected outcome
  -------------------  ------------------------------------  -----------------------
  single.txt           1x STANDARD                          complete (copied)
  all-ok.txt           3x STANDARD                          complete (all copied)
  all-glacier.txt      3x GLACIER                           fully_skipped
  half-glacier.txt     2x STANDARD + 2x GLACIER             partial (2 copied, 2 skipped)
  mostly-glacier.txt   1x STANDARD + 3x GLACIER             partial (1 copied, 3 skipped)
  mostly-ok.txt        3x STANDARD + 1x GLACIER             partial (3 copied, 1 skipped)
  docs/report.txt      3x STANDARD + delete marker          complete (3 copied + marker)
  docs/archive.txt     2x STANDARD + 1x GLACIER + marker    partial (2 copied, 1 skipped + marker)
"""

import hashlib
import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# ── Configuration ─────────────────────────────────────────────────────────────

# Moto source (accepts any credentials, supports GLACIER)
MOTO_ENDPOINT    = "http://localhost:5555"
MOTO_ACCESS_KEY  = "testing"
MOTO_SECRET_KEY  = "testing"

# MinIO destination
MINIO_ENDPOINT   = "http://localhost:8000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"

SOURCE_BUCKET = "source-versioned"
DEST_BUCKET   = "dest-versioned"
PIT_BUCKET    = "pit-bucket"

# Object Lock buckets (both on MinIO — Moto does not support get-object-retention)
OL_SRC_BUCKET = "ol-lab-src"
OL_DST_BUCKET = "ol-lab-dst"

FILE_SIZE = 65_536  # 64 KB per version

# Test data: (key, [(payload_seed, storage_class), ...])
# Versions are uploaded oldest-first.
TEST_KEYS = [
    ("single.txt", [
        ("single-v1", "STANDARD"),
    ]),
    ("all-ok.txt", [
        ("all-ok-v1", "STANDARD"),
        ("all-ok-v2", "STANDARD"),
        ("all-ok-v3", "STANDARD"),
    ]),
    ("all-glacier.txt", [
        ("all-glacier-v1", "GLACIER"),
        ("all-glacier-v2", "GLACIER"),
        ("all-glacier-v3", "GLACIER"),
    ]),
    ("half-glacier.txt", [
        ("half-v1-ok", "STANDARD"),
        ("half-v2-glacier", "GLACIER"),
        ("half-v3-ok", "STANDARD"),
        ("half-v4-glacier", "GLACIER"),
    ]),
    ("mostly-glacier.txt", [
        ("mostly-glacier-v1-ok", "STANDARD"),
        ("mostly-glacier-v2", "GLACIER"),
        ("mostly-glacier-v3", "GLACIER"),
        ("mostly-glacier-v4", "GLACIER"),
    ]),
    ("mostly-ok.txt", [
        ("mostly-ok-v1", "STANDARD"),
        ("mostly-ok-v2", "STANDARD"),
        ("mostly-ok-v3-glacier", "GLACIER"),
        ("mostly-ok-v4", "STANDARD"),
    ]),
    # Keys with delete markers
    ("docs/report.txt", [
        ("report-v1", "STANDARD"),
        ("report-v2", "STANDARD"),
        ("report-v3", "STANDARD"),
    ]),
    ("docs/archive.txt", [
        ("archive-v1", "STANDARD"),
        ("archive-v2", "STANDARD"),
        ("archive-v3-glacier", "GLACIER"),
    ]),
]

# Keys that get a delete marker after all versions are uploaded
DELETE_MARKER_KEYS = ["docs/report.txt", "docs/archive.txt"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def deterministic_content(seed_str: str, size: int) -> bytes:
    """Generate deterministic content from a seed string."""
    seed = hashlib.sha256(seed_str.encode()).digest()
    pieces = []
    total  = 0
    piece  = seed
    while total < size:
        piece = hashlib.sha256(piece).digest()
        pieces.append(piece)
        total += len(piece)
    return b"".join(pieces)[:size]


def s3_client(endpoint: str, access_key: str, secret_key: str):
    return boto3.client(
        "s3",
        endpoint_url          = endpoint,
        aws_access_key_id     = access_key,
        aws_secret_access_key = secret_key,
        config                = Config(signature_version="s3v4"),
        region_name           = "us-east-1",
    )


def create_versioned_bucket(s3, bucket_name: str) -> None:
    """Create a bucket with versioning enabled (idempotent)."""
    try:
        s3.create_bucket(Bucket=bucket_name)
        print(f"  Created bucket '{bucket_name}'")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"  Bucket '{bucket_name}' already exists — OK")
        else:
            raise

    s3.put_bucket_versioning(
        Bucket=bucket_name,
        VersioningConfiguration={"Status": "Enabled"},
    )
    print(f"  Versioning enabled on '{bucket_name}'")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Preparing source (Moto :5555) and destination (MinIO :8000) ...\n")

    moto  = s3_client(MOTO_ENDPOINT, MOTO_ACCESS_KEY, MOTO_SECRET_KEY)
    minio = s3_client(MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY)

    # Source bucket on Moto (supports GLACIER)
    print("Source (Moto):")
    create_versioned_bucket(moto, SOURCE_BUCKET)

    # Destination buckets on MinIO
    print("\nDestination (MinIO):")
    create_versioned_bucket(minio, DEST_BUCKET)
    create_versioned_bucket(minio, PIT_BUCKET)

    # Count totals
    total_versions = sum(len(versions) for _, versions in TEST_KEYS)
    total_standard = sum(1 for _, versions in TEST_KEYS for _, sc in versions if sc == "STANDARD")
    total_glacier  = sum(1 for _, versions in TEST_KEYS for _, sc in versions if sc == "GLACIER")

    print(f"\nSeeding {len(TEST_KEYS)} keys, {total_versions} total versions "
          f"({total_standard} STANDARD + {total_glacier} GLACIER) ...\n")

    total_bytes = 0

    for key, versions in TEST_KEYS:
        for payload_seed, storage_class in versions:
            content = deterministic_content(payload_seed, FILE_SIZE)
            moto.put_object(
                Bucket=SOURCE_BUCKET,
                Key=key,
                Body=content,
                StorageClass=storage_class,
            )
            total_bytes += FILE_SIZE
            time.sleep(0.05)  # distinct timestamps for since: mode

        classes = [sc for _, sc in versions]
        class_summary = ", ".join(f"{classes.count(c)}x {c}" for c in dict.fromkeys(classes))
        print(f"  {key:<25}  {len(versions)} versions  ({class_summary})")

    # Record midpoint timestamp for point-in-time demo and write to file
    midpoint_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    midpoint_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "since-timestamp.txt")
    with open(midpoint_file, "w") as f:
        f.write(midpoint_time)

    # Create delete markers
    print(f"\nCreating delete markers for {len(DELETE_MARKER_KEYS)} keys ...")
    for key in DELETE_MARKER_KEYS:
        moto.delete_object(Bucket=SOURCE_BUCKET, Key=key)
        print(f"  Deleted {key} (delete marker created)")

    # Verify
    paginator = moto.get_paginator("list_object_versions")
    version_count = 0
    delete_marker_count = 0
    glacier_count = 0
    for page in paginator.paginate(Bucket=SOURCE_BUCKET):
        for v in page.get("Versions", []):
            version_count += 1
            if v.get("StorageClass") == "GLACIER":
                glacier_count += 1
        delete_marker_count += len(page.get("DeleteMarkers", []))

    print(f"\nSeed complete:")
    print(f"  Keys:             {len(TEST_KEYS)}")
    print(f"  Versions:         {version_count} ({version_count - glacier_count} STANDARD, {glacier_count} GLACIER)")
    print(f"  Delete markers:   {delete_marker_count}")
    print(f"  Total bytes:      {total_bytes / 1_048_576:.1f} MB")
    print(f"  Midpoint time:    {midpoint_time}")
    print(f"                    (use with --version-mode \"since:{midpoint_time}\")")
    print(f"\nExpected migration outcome:")
    print(f"  Copied:           {total_standard} STANDARD versions + {delete_marker_count} delete markers")
    print(f"  Skipped (glacier): {total_glacier} GLACIER versions")
    print(f"  Partial history:  3 keys (half-glacier, mostly-glacier, mostly-ok)")
    print(f"  Fully skipped:    1 key (all-glacier)")
    # ── Object Lock seed (both buckets on MinIO) ────────────────────────────
    seed_object_lock(minio)

    print(f"\nReady. Run to continue:")
    print(f"  bash scripts/migrate-versions.sh")


def seed_object_lock(minio) -> None:
    """Create Object Lock-enabled buckets on MinIO and seed test objects."""
    from datetime import datetime, timezone, timedelta

    print("\n── Object Lock Setup (MinIO → MinIO) ──────────────────────\n")

    # Create Object Lock-enabled buckets
    for bucket in [OL_SRC_BUCKET, OL_DST_BUCKET]:
        try:
            minio.create_bucket(
                Bucket=bucket,
                ObjectLockEnabledForBucket=True,
            )
            print(f"  Created bucket '{bucket}' (Object Lock enabled)")
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                print(f"  Bucket '{bucket}' already exists — OK")
            else:
                raise

        minio.put_bucket_versioning(
            Bucket=bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )

    # Retain-until date ~1 day in the future (GOVERNANCE can be bypassed)
    retain_until = datetime.now(timezone.utc) + timedelta(days=1)

    ol_objects = [
        # (key, payload, retention_mode, retain_until, legal_hold)
        ("governance-only.dat",       b"gov-data-v1",   "GOVERNANCE",  retain_until, False),
        ("compliance-and-hold.dat",   b"comp-data-v1",  "COMPLIANCE",  retain_until, True),
        ("legal-hold-only.dat",       b"hold-data-v1",  None,          None,         True),
        ("no-lock.dat",               b"plain-data-v1", None,          None,         False),
    ]

    print(f"\nSeeding {len(ol_objects)} Object Lock test objects ...\n")

    for key, payload, ret_mode, ret_until, legal_hold in ol_objects:
        resp = minio.put_object(Bucket=OL_SRC_BUCKET, Key=key, Body=payload)
        vid = resp.get("VersionId", "")

        if ret_mode and ret_until:
            minio.put_object_retention(
                Bucket=OL_SRC_BUCKET, Key=key, VersionId=vid,
                Retention={"Mode": ret_mode, "RetainUntilDate": ret_until},
            )

        if legal_hold:
            minio.put_object_legal_hold(
                Bucket=OL_SRC_BUCKET, Key=key, VersionId=vid,
                LegalHold={"Status": "ON"},
            )

        lock_desc = []
        if ret_mode:
            lock_desc.append(ret_mode)
        if legal_hold:
            lock_desc.append("LEGAL_HOLD")
        print(f"  {key:<30} lock=[{', '.join(lock_desc) or 'none'}]")

    print(f"\nObject Lock seed complete:")
    print(f"  Source bucket:      {OL_SRC_BUCKET} (MinIO :8000)")
    print(f"  Destination bucket: {OL_DST_BUCKET} (MinIO :8000)")
    print(f"  Objects:            {len(ol_objects)}")
    print(f"  GOVERNANCE:         1")
    print(f"  COMPLIANCE:         1")
    print(f"  Legal hold:         2")
    print(f"  No lock:            1")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print("Is the lab environment running?  docker compose -f infra/docker-compose.yml up -d",
              file=sys.stderr)
        sys.exit(1)
