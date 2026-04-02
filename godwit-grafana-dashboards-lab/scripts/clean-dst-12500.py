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
clean-dst-12500.py -- Delete all object versions from the MinIO 2 many-dst
bucket and remove the local state DB so migrate-12500.py can run again
cleanly.

Object Lock objects with GOVERNANCE retention are deleted using the
bypass-governance header.
"""

import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

LAB_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_DB = os.path.join(LAB_ROOT, "many.state.db")

# MinIO 2 (destination) -- port 8002
MINIO2_ENDPOINT = "http://localhost:8002"
MINIO2_AK       = "minioadmin"
MINIO2_SK       = "minioadmin"

MANY_DST = "many-dst"


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url          = MINIO2_ENDPOINT,
        aws_access_key_id     = MINIO2_AK,
        aws_secret_access_key = MINIO2_SK,
        config                = Config(signature_version="s3v4"),
        region_name           = "us-east-1",
    )


def delete_all_versions(s3) -> int:
    """Delete every version and delete marker from many-dst. Returns count."""
    deleted = 0
    kwargs = {"Bucket": MANY_DST}
    while True:
        resp = s3.list_object_versions(**kwargs)
        objects = []
        for v in resp.get("Versions", []):
            objects.append({"Key": v["Key"], "VersionId": v["VersionId"]})
        for dm in resp.get("DeleteMarkers", []):
            objects.append({"Key": dm["Key"], "VersionId": dm["VersionId"]})

        if objects:
            # BypassGovernanceRetention lets us delete GOVERNANCE-locked objects
            s3.delete_objects(
                Bucket=MANY_DST,
                Delete={"Objects": objects, "Quiet": True},
                BypassGovernanceRetention=True,
            )
            deleted += len(objects)
            print(f"\r    deleted {deleted} versions ...", end="", flush=True)

        if not resp.get("IsTruncated"):
            break
        kwargs["KeyMarker"] = resp.get("NextKeyMarker", "")
        kwargs["VersionIdMarker"] = resp.get("NextVersionIdMarker", "")

    if deleted:
        print()
    return deleted


def main() -> None:
    s3 = s3_client()

    # -- Clear MinIO 2 many-dst bucket -----------------------------------------
    print("==> Deleting all versions from MinIO 2 'many-dst' ...")
    try:
        s3.head_bucket(Bucket=MANY_DST)
    except ClientError:
        print("    Bucket 'many-dst' not found -- nothing to clean.")
    else:
        count = delete_all_versions(s3)
        print(f"    Removed {count} versions from '{MANY_DST}'.")

    # -- Remove state DB -------------------------------------------------------
    print("==> Removing state database ...")
    for suffix in ("", "-wal", "-shm"):
        path = STATE_DB + suffix
        if os.path.exists(path):
            os.remove(path)
            print(f"    removed: {path}")

    print("\n==> Clean. Ready to run:")
    print("  python3 scripts/migrate-12500.py")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
