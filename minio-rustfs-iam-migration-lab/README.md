# Lab: Migrate MinIO IAM to RustFS (Path B)

Hands-on companion for the article: **[Migrate MinIO IAM to RustFS](https://godwit.io/blog/minio-rustfs-iam-migration)**.

This lab reproduces **Path B**: a new-host migration where object data already moved (via `mc mirror` or [Godwit Sync](https://godwit.io/docs/quickstart)) and the IAM configuration does not come with it. You export users, groups, policies, and service accounts from MinIO and import them into a fresh RustFS instance, then verify a migrated identity authenticates and its policy is enforced.

The import step uses RustFS's `import-iam` admin endpoint, which is undocumented and pre-stable. This lab is the place to confirm whether it works on your RustFS version before you rely on it.

## Architecture

MinIO (source, `localhost:8000`) holds the seeded IAM. The export produces a zip, which is imported into RustFS (destination, `localhost:6000`). Only IAM moves in this lab; the demo bucket is created on RustFS to give the migrated policy a target.

This lab pins **RustFS 1.0.0-beta.6** (`rustfs/rustfs:1.0.0-beta.6`). The `import-iam` endpoint is version-sensitive, so behavior on other builds may differ.

## Prerequisites

- Docker and Docker Compose
- AWS CLI (used to verify migrated credentials)
- `curl` >= 7.75 (for the `--aws-sigv4` import fallback)
- `unzip` (to list the export contents)

## Setup

```bash
cd infra
docker compose up -d
cd ..
```

MinIO comes up on `localhost:8000` (console `8001`, `minioadmin` / `minioadmin`). RustFS comes up on `localhost:6000` (console `6001`, `rustfsadmin` / `rustfsadmin`).

> If RustFS exits on first start with a data-directory permission error, run `docker compose down -v` and `docker compose up -d` again. RustFS runs as UID 10001 and initializes the named volume on a clean start.

## Step 1: Seed IAM on MinIO

```bash
bash scripts/seed-iam.sh
```

Creates a read-only policy (`readonly-demo`), a user (`appuser`), a group (`developers`), a service account, and a `demo-bucket` with one object. This is the access-control state a real deployment would have.

## Step 2: Export IAM from MinIO

```bash
bash scripts/export-iam.sh
```

Runs `mc admin cluster iam export` and copies the resulting zip to `./iam-export.zip`. The script lists its contents (`users.json`, `policies`, `groups.json`, `svcaccts.json`, mappings).

## Step 3: Import IAM into RustFS

```bash
bash scripts/import-iam.sh
```

Imports the zip with a direct SigV4 `curl` PUT to `/rustfs/admin/v3/import-iam` and reports the HTTP status. (`mc admin cluster iam import` is deliberately not used: it targets MinIO's admin namespace and reports success against RustFS without actually importing.) On RustFS 1.0.0-beta.6 a successful import returns HTTP 200 with a JSON summary of what was added. If the import does not succeed on your RustFS version, the exported zip still holds the full configuration to recreate manually.

## Step 4: Verify

```bash
bash scripts/verify-iam.sh
```

Authenticates to RustFS with the migrated `appuser` key and checks two things:

1. Listing `demo-bucket` succeeds (the user and its read permission transferred).
2. A write is denied with `AccessDenied` (the read-only policy is enforced, not just the identity).

A pass on both confirms the credential and its policy migrated. A failure on Test 1 means the import did not transfer the user on your RustFS build.

## Teardown

```bash
bash scripts/cleanup.sh
```

Stops both containers, removes their volumes, and deletes the exported zip.

## What this lab does not cover

- **LDAP / OIDC identities.** They live in the external provider and never migrate; only policy mappings move.
- **Path A (binary swap).** That path carries IAM in place with no export or import, so there is nothing to reproduce here.
- **Lifecycle rules and bucket notifications.** Out of scope; recreate them manually.

<!-- Copyright (c) 2026 Godwit.io. Licensed under the MIT License. -->
