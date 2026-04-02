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
seed-data.py -- Generate deterministic test files in ./data/seed/ and create
MinIO buckets for the Grafana observability lab.

Creates:
  1. ./data/seed/ -- local files for the main round-trip migration
  2. demo-bucket -- standard bucket for the main 4 rounds (fs->s3->s3->fs)
  3. versioned-src / versioned-dst -- versioned buckets with multiple versions
     per key, for the version-history bonus round (--version-mode all)
  4. ol-src / ol-dst -- Object Lock-enabled buckets with retention and legal
     hold settings, for the Object Lock bonus round (--object-lock)
"""

import hashlib
import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# -- Configuration -----------------------------------------------------------

SEED_DIR         = os.path.join(os.path.dirname(__file__), "..", "data", "seed")
MINIO_ENDPOINT   = "http://localhost:8000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
BUCKET_NAME      = "demo-bucket"
WRITE_CHUNK      = 1_048_576  # 1 MB -- stream large files in chunks to limit memory

# Versioned-bucket config
VERSIONED_SRC = "versioned-src"
VERSIONED_DST = "versioned-dst"
VERSION_SIZE  = 65_536  # 64 KB per version

# Object Lock config
OL_SRC = "ol-src"
OL_DST = "ol-dst"

# (label, count, size_bytes)
FILE_SPEC = [
    ("small",  100,   65_536),          #  64 KB each  ->    6.25 MB total
    ("medium",  40,   10_485_760),      #  10 MB each  ->  400    MB total
    ("large",   40,  104_857_600),      # 100 MB each  -> 4000    MB total
]                                        #                 ~ 4.3 GB total

# Versioned test data: (key, num_versions)
# Mix of single-version and multi-version keys for interesting
# godwit_version_history_keys chart output.
VERSIONED_KEYS = [
    ("config.yaml",       3),
    ("readme.txt",        2),
    ("data/report.csv",   4),
    ("data/summary.json", 2),
    ("logs/app.log",      5),
    ("logs/error.log",    3),
    ("docs/guide.md",     1),
    ("docs/changelog.md", 3),
]
# Keys that get a delete marker after all versions are uploaded
VERSIONED_DELETE_KEYS = ["logs/app.log", "docs/changelog.md"]


# -- Helpers -----------------------------------------------------------------

def deterministic_chunk(path: str, chunk_index: int, size: int) -> bytes:
    """Generate up to `size` bytes of deterministic content for one chunk."""
    seed = hashlib.sha256(f"{path}:{chunk_index}".encode()).digest()
    pieces = []
    total  = 0
    piece  = seed
    while total < size:
        piece = hashlib.sha256(piece).digest()
        pieces.append(piece)
        total += len(piece)
    return b"".join(pieces)[:size]


def deterministic_content(seed_str: str, size: int) -> bytes:
    """Generate deterministic content from a seed string."""
    return deterministic_chunk(seed_str, 0, size)


def write_file_streaming(filepath: str, rel_path: str, size: int) -> None:
    """Write a file of `size` bytes using streaming chunks (memory-efficient)."""
    with open(filepath, "wb") as fh:
        written   = 0
        chunk_idx = 0
        while written < size:
            remaining = size - written
            chunk = deterministic_chunk(rel_path, chunk_idx, min(WRITE_CHUNK, remaining))
            fh.write(chunk)
            written   += len(chunk)
            chunk_idx += 1


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url          = MINIO_ENDPOINT,
        aws_access_key_id     = MINIO_ACCESS_KEY,
        aws_secret_access_key = MINIO_SECRET_KEY,
        config                = Config(signature_version="s3v4"),
        region_name           = "us-east-1",
    )


def create_bucket(s3, bucket: str) -> None:
    """Create a bucket (idempotent)."""
    try:
        s3.create_bucket(Bucket=bucket)
        print(f"  Created bucket '{bucket}'")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"  Bucket '{bucket}' already exists -- OK")
        else:
            raise


def create_versioned_bucket(s3, bucket: str) -> None:
    """Create a bucket with versioning enabled (idempotent)."""
    create_bucket(s3, bucket)
    s3.put_bucket_versioning(
        Bucket=bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )
    print(f"  Versioning enabled on '{bucket}'")


def create_object_lock_bucket(s3, bucket: str) -> None:
    """Create a bucket with Object Lock enabled (idempotent)."""
    try:
        s3.create_bucket(
            Bucket=bucket,
            ObjectLockEnabledForBucket=True,
        )
        print(f"  Created bucket '{bucket}' (Object Lock enabled)")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"  Bucket '{bucket}' already exists -- OK")
        else:
            raise
    s3.put_bucket_versioning(
        Bucket=bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )


# -- Generators --------------------------------------------------------------

def generate_files() -> list[str]:
    """Write seed files to SEED_DIR. Returns list of relative paths."""
    os.makedirs(SEED_DIR, exist_ok=True)
    paths = []
    total_bytes = 0

    for label, count, size in FILE_SPEC:
        subdir = os.path.join(SEED_DIR, label)
        os.makedirs(subdir, exist_ok=True)
        for i in range(1, count + 1):
            filename  = f"file-{i:03d}.bin"
            filepath  = os.path.join(subdir, filename)
            rel_path  = os.path.join(label, filename)
            write_file_streaming(filepath, rel_path, size)
            paths.append(filepath)
            total_bytes += size
            print(f"  created {rel_path:<32}  ({size:>12,} bytes)")

    print(f"\nSeed complete: {len(paths)} files, {total_bytes / 1_048_576:.1f} MB total")
    return paths


def seed_versioned_bucket(s3) -> None:
    """Create versioned buckets and upload objects with multiple versions."""
    print("\n── Versioned Bucket Setup ─────────────────────────────────\n")

    create_versioned_bucket(s3, VERSIONED_SRC)
    create_versioned_bucket(s3, VERSIONED_DST)

    total_versions = sum(n for _, n in VERSIONED_KEYS)
    print(f"\nSeeding {len(VERSIONED_KEYS)} keys, {total_versions} total versions ...\n")

    for key, num_versions in VERSIONED_KEYS:
        for v in range(1, num_versions + 1):
            content = deterministic_content(f"{key}:v{v}", VERSION_SIZE)
            s3.put_object(Bucket=VERSIONED_SRC, Key=key, Body=content)
            time.sleep(0.05)  # distinct timestamps
        print(f"  {key:<25}  {num_versions} versions")

    print(f"\nCreating delete markers for {len(VERSIONED_DELETE_KEYS)} keys ...")
    for key in VERSIONED_DELETE_KEYS:
        s3.delete_object(Bucket=VERSIONED_SRC, Key=key)
        print(f"  Deleted {key} (delete marker created)")

    print(f"\nVersioned seed complete:")
    print(f"  Source:      {VERSIONED_SRC} (MinIO :8000)")
    print(f"  Destination: {VERSIONED_DST} (MinIO :8000)")
    print(f"  Keys:        {len(VERSIONED_KEYS)}")
    print(f"  Versions:    {total_versions}")
    print(f"  Delete markers: {len(VERSIONED_DELETE_KEYS)}")


def seed_object_lock(s3) -> None:
    """Create Object Lock-enabled buckets and seed test objects."""
    from datetime import datetime, timezone, timedelta

    print("\n── Object Lock Setup ──────────────────────────────────────\n")

    create_object_lock_bucket(s3, OL_SRC)
    create_object_lock_bucket(s3, OL_DST)

    retain_until = datetime.now(timezone.utc) + timedelta(days=1)

    ol_objects = [
        # (key, payload, retention_mode, retain_until, legal_hold)
        ("governance-only.dat",       b"gov-data-v1",   "GOVERNANCE",  retain_until, False),
        ("compliance-and-hold.dat",   b"comp-data-v1",  "COMPLIANCE",  retain_until, True),
        ("legal-hold-only.dat",       b"hold-data-v1",  None,          None,         True),
        ("no-lock.dat",               b"plain-data-v1", None,          None,         False),
    ]

    print(f"Seeding {len(ol_objects)} Object Lock test objects ...\n")

    for key, payload, ret_mode, ret_until, legal_hold in ol_objects:
        resp = s3.put_object(Bucket=OL_SRC, Key=key, Body=payload)
        vid = resp.get("VersionId", "")

        if ret_mode and ret_until:
            s3.put_object_retention(
                Bucket=OL_SRC, Key=key, VersionId=vid,
                Retention={"Mode": ret_mode, "RetainUntilDate": ret_until},
            )

        if legal_hold:
            s3.put_object_legal_hold(
                Bucket=OL_SRC, Key=key, VersionId=vid,
                LegalHold={"Status": "ON"},
            )

        lock_desc = []
        if ret_mode:
            lock_desc.append(ret_mode)
        if legal_hold:
            lock_desc.append("LEGAL_HOLD")
        print(f"  {key:<30} lock=[{', '.join(lock_desc) or 'none'}]")

    print(f"\nObject Lock seed complete:")
    print(f"  Source:      {OL_SRC} (MinIO :8000)")
    print(f"  Destination: {OL_DST} (MinIO :8000)")
    print(f"  Objects:     {len(ol_objects)}")
    print(f"  GOVERNANCE:  1")
    print(f"  COMPLIANCE:  1")
    print(f"  Legal hold:  2")
    print(f"  No lock:     1")


# -- Main --------------------------------------------------------------------

def main() -> None:
    print("Generating seed data ...")
    print(f"  Output directory: {os.path.abspath(SEED_DIR)}\n")

    generate_files()

    print("\nPreparing MinIO ...")
    s3 = s3_client()

    create_bucket(s3, BUCKET_NAME)

    seed_versioned_bucket(s3)
    seed_object_lock(s3)

    print("\nReady. Run next:")
    print("  bash scripts/migrate.sh")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print("Is the lab environment running?  docker compose -f infra/docker-compose.yml up -d",
              file=sys.stderr)
        sys.exit(1)
