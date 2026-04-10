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

"""setup-lab.py -- Set up and manage the multi-bucket migration lab environment.

Seeds test data into RustFS source and target instances, injects a
failure condition for the retry demo, and provides a fix command.

Usage:
    python3 scripts/setup-lab.py seed              Create buckets and upload test objects
    python3 scripts/setup-lab.py fix-logs-archive   Recreate deleted target bucket (fix failure)

Prerequisites:
    - RustFS source on localhost:7000, target on localhost:7001
    - Python 3 with boto3: pip install boto3
"""

import hashlib
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# -- Configuration -----------------------------------------------------------

SOURCE_ENDPOINT   = "http://localhost:7000"
TARGET_ENDPOINT   = "http://localhost:7001"
ACCESS_KEY        = "rustfsadmin"
SECRET_KEY        = "rustfsadmin"

BUCKETS = ["app-data", "ml-models", "logs-archive", "user-uploads"]

# (bucket, object_count, size_bytes_or_range)
# When size is a tuple, each object gets a random-but-deterministic size in that range.
BUCKET_SPEC = [
    ("app-data",      100,  65_536),                  #  64 KB each
    ("ml-models",      50,  1_048_576),               #   1 MB each
    ("logs-archive",   80,  131_072),                 # 128 KB each
    ("user-uploads",  120,  (65_536, 524_288)),       #  64-512 KB each
]


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


def deterministic_size(seed_str: str, min_size: int, max_size: int) -> int:
    """Pick a deterministic size in [min_size, max_size] based on a seed string."""
    h = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16)
    return min_size + (h % (max_size - min_size + 1))


def make_s3_client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url          = endpoint,
        aws_access_key_id     = ACCESS_KEY,
        aws_secret_access_key = SECRET_KEY,
        config                = Config(signature_version="s3v4"),
        region_name           = "us-east-1",
    )


def create_bucket(s3, bucket: str, label: str) -> None:
    """Create a bucket (idempotent)."""
    try:
        s3.create_bucket(Bucket=bucket)
        print(f"  Created bucket '{bucket}' on {label}")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"  Bucket '{bucket}' already exists on {label} -- OK")
        else:
            raise


def upload_objects(s3, bucket: str, count: int, size_spec) -> int:
    """Upload deterministic objects to a bucket. Returns total bytes uploaded."""
    total_bytes = 0
    for i in range(1, count + 1):
        key = f"object-{i:04d}.bin"
        seed_str = f"{bucket}/{key}"

        if isinstance(size_spec, tuple):
            size = deterministic_size(seed_str, size_spec[0], size_spec[1])
        else:
            size = size_spec

        content = deterministic_content(seed_str, size)
        s3.put_object(Bucket=bucket, Key=key, Body=content)
        total_bytes += size

    return total_bytes


# -- Commands ----------------------------------------------------------------

def cmd_seed() -> None:
    """Create buckets, upload test objects, and inject the logs-archive failure."""
    print("Multi-Bucket Migration Lab -- Seed Data")
    print("=" * 50)

    source_s3 = make_s3_client(SOURCE_ENDPOINT)
    target_s3 = make_s3_client(TARGET_ENDPOINT)

    # Create buckets on both instances
    print("\nCreating buckets ...")
    for bucket in BUCKETS:
        create_bucket(source_s3, bucket, "source")
        create_bucket(target_s3, bucket, "target")

    # Upload objects to source
    print("\nUploading objects to source ...")
    grand_total_objects = 0
    grand_total_bytes   = 0

    for bucket, count, size_spec in BUCKET_SPEC:
        print(f"\n  {bucket}:")
        total_bytes = upload_objects(source_s3, bucket, count, size_spec)
        grand_total_objects += count
        grand_total_bytes   += total_bytes

        if isinstance(size_spec, tuple):
            size_label = f"{size_spec[0] // 1024}-{size_spec[1] // 1024} KB (mixed)"
        else:
            size_label = f"{size_spec // 1024} KB"

        print(f"    {count} objects x {size_label} = {total_bytes / 1_048_576:.1f} MB")

    # Inject failure: delete the target logs-archive bucket
    print("\nInjecting failure condition ...")
    target_s3.delete_bucket(Bucket="logs-archive")
    print("  Deleted target logs-archive bucket (failure injection)")

    # Summary
    print("\n" + "=" * 50)
    print("Seed complete.")
    print(f"  Total objects: {grand_total_objects}")
    print(f"  Total size:    {grand_total_bytes / 1_048_576:.1f} MB")
    print(f"  Source:        {SOURCE_ENDPOINT}")
    print(f"  Target:        {TARGET_ENDPOINT}")
    print("")
    print("Buckets seeded on source:")
    for bucket, count, _ in BUCKET_SPEC:
        print(f"  {bucket:<20} {count} objects")
    print("")
    print("Failure injection:")
    print("  logs-archive bucket deleted from target.")
    print("  The migration will fail for this pair (NoSuchBucket).")


def cmd_fix_logs_archive() -> None:
    """Recreate the target logs-archive bucket to fix the injected failure."""
    print()
    print("==> Recreating logs-archive bucket on target ...")

    s3 = make_s3_client(TARGET_ENDPOINT)
    create_bucket(s3, "logs-archive", "target")


# -- Dispatch ----------------------------------------------------------------

COMMANDS = {
    "seed": cmd_seed,
    "fix-logs-archive": cmd_fix_logs_archive,
}


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "help"

    if command in ("help", "--help", "-h"):
        print("Usage: python3 scripts/setup-lab.py {seed|fix-logs-archive}")
        print()
        print("Commands:")
        print("  seed              Create buckets and upload test objects")
        print("  fix-logs-archive  Recreate deleted target bucket (fix failure)")
        return

    if command not in COMMANDS:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    try:
        COMMANDS[command]()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print("Is the lab environment running?  docker compose -f infra/docker-compose.yml up -d",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
