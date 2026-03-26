# Lab: How to Verify S3 Migrations with Godwit Sync

Hands-on lab for the article:
**[How to Verify S3 Migrations with Godwit Sync](https://godwit.io/blog/verifying-s3-migrations)**

## What You Will Do

Run a complete S3 migration validation workflow using the `godwit plan` subcommands. Starting from a populated state database, you will list migration runs, inspect transfer details, find failed objects, detect filesystem compatibility issues, and generate a compliance audit report.

| Step | Command                                    | What you learn                                                          |
| ---- | ------------------------------------------ | ----------------------------------------------------------------------- |
| 1    | `godwit plan list`                         | View all migration runs and their status                                |
| 2    | `godwit plan inspect`                      | Drill into object counts, byte totals, and storage class distribution   |
| 3    | `godwit plan list objects`                 | Find failed, pending, or excluded objects with per-object error details |
| 4    | `godwit plan list objects --case-conflict` | Surface filesystem compatibility issues                                 |
| 5    | Append `--json` to any command             | Export machine-readable output for CI pipelines or compliance reports   |

## Prerequisites

- **Godwit Sync** binary on `PATH` -- `godwit version`

If `godwit version` fails, install Godwit Sync from the [Quickstart guide](https://godwit.io/docs/quickstart).

## State Database

This lab includes a pre-built `godwit.state.db` file that contains upload, transfer, and download runs from the [S3 Migration Guide lab](../s3-migration-guide-lab/README.md). You can use it directly instead of running the migration lab first.

If you prefer to generate your own state database, complete the [S3 Migration Guide lab](../s3-migration-guide-lab/README.md) and copy the resulting `godwit.state.db` into this directory.

## Quick Start

### 1. List all migration runs

`godwit plan list` shows every run in the state database. Each row includes the run ID, status, start time, object count, bytes transferred, duration, and failure count. This is the starting point for any S3 migration report.

```bash
godwit plan list \
  --state-path ./godwit.state.db
```

Expected output:

```
RUN-ID    STATUS     STARTED              OBJECTS  BYTES   DURATION  FAILURES
──────    ──────     ────                 ───────  ─────   ────────  ────────
download  completed  2026-03-26 17:18:13  360      4.3 GB  28s       0
transfer  completed  2026-03-26 17:17:17  360      4.3 GB  56s       0
upload    completed  2026-03-26 17:16:10  180      4.3 GB  1m 5s     0
```

Filter by status:

```bash
godwit plan list \
  --state-path ./godwit.state.db \
  --status completed
```

### 2. Inspect the transfer run in detail

`godwit plan inspect` shows a detailed breakdown for a single run: status, timing, object counts by state, data volumes, and storage class distribution.

```bash
godwit plan inspect \
  --run-id transfer \
  --state-path ./godwit.state.db
```

Expected output:

```
Plan Summary for Run: transfer
─────────────────────────────────────
Status:            completed
Started At:        2026-03-26 17:17:17
Finished At:       2026-03-26 17:18:13

Objects:
  Total:           360
  Pending:         0
  Running:         0
  Finished:        180
  Skipped:         0
  Failed:          0
  Excluded:        180

Data:
  Transferred:     4.3 GB
  Left:            0 B
  Total:           4.3 GB
  Excluded:        5.6 KB

Storage classes detected:
  STANDARD:            100.0%   360 objects   4.3 GB

Version History:
  Complete History:      180 keys
  Partial History:       0 keys
  Fully Skipped:         0 keys
```

Reading the output:

In this lab, all objects show as `Finished` with zero failures -- the transfer completed successfully. The [article](https://godwit.io/blog/verifying-s3-migrations) explains each field in detail.

### 3. List failed and pending objects

`godwit plan list objects` lists individual objects from a run, filtered by status. The first argument after `objects` is the status filter. Valid values: `all`, `pending`, `running`, `finished`, `skipped`, `failed`, `excluded`, `glacier`, `unsupported_key`.

See all finished objects:

```bash
godwit plan list objects finished \
  --run-id transfer \
  --state-path ./godwit.state.db
```

Combine statuses with `+` to see everything that still needs work:

```bash
godwit plan list objects pending+failed \
  --run-id transfer \
  --state-path ./godwit.state.db
```

### 4. Generate a compliance audit report as JSON

Export each validation layer as JSON for CI pipelines or compliance audits:

```bash
# Run history
godwit plan list --state-path ./godwit.state.db --json > runs.json

# Per-run summary with storage class breakdown
godwit plan inspect --run-id transfer --state-path ./godwit.state.db --json > summary.json

# Per-object manifest with status, timestamps, and checksums
godwit plan list objects all --run-id transfer --state-path ./godwit.state.db --json > objects.json
```

Together, `runs.json`, `summary.json`, and `objects.json` form a complete S3 migration audit report that auditors can review without access to the source or destination systems.

<!-- Copyright (c) 2026 Godwit.io. Licensed under the MIT License. -->
