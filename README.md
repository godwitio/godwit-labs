# S3 Migration Labs with Docker (MinIO, RustFS, Garage, Moto)

**This repository provides reproducible S3 migration testing environments for [Godwit Sync](https://godwit.io).** It contains hands-on labs for simulating real-world S3 migrations locally using Docker, so you can rehearse, validate, and troubleshoot a migration end-to-end without any cloud credentials. Each lab is a self-contained Docker Compose stack that provisions source and target object storage, runs a real S3 migration workflow, and exposes the verification or observability tooling used to validate it.

## Who these labs are for

- **Platform and DevOps engineers** migrating data between S3, MinIO, RustFS, Garage, Moto, or other S3-compatible object stores.
- **SREs** adopting Prometheus and Grafana observability for long-running data transfers.
- **Backup, compliance, and data engineers** validating object counts, checksums, version history, and Object Lock state across a migration.

## What this repository provides

Six Docker-based labs covering the core surfaces of an S3 migration: transfer direction, version history, multi-bucket orchestration, real-time monitoring, post-migration verification, and S3 authentication. Each lab pairs with a long-form [S3 migration guide](https://godwit.io/blog) and is designed to run to completion on a developer laptop.

### Core S3 migration workflows

- **[S3 Migration Guide: Upload, Transfer, and Download S3 Data](./s3-migration-guide-lab/README.md)** — Run the three canonical migration directions (`fs → s3`, `s3 → s3`, `s3 → fs`) across MinIO and Garage. Demonstrates basic sync, plan-first transfers with `--plan-only` and `--resume`, and checksum verification.
- **[S3 Version History Migration](./s3-version-history-migration-lab/README.md)** — Migrate versioned S3 objects with mixed storage classes (STANDARD, GLACIER) and replicate Object Lock metadata using the `--version-mode` flag. Covers full history, point-in-time filtering, and Object Lock-protected buckets.
- **[Multi-Bucket Migration Orchestration](./multi-bucket-migration-lab/README.md)** — Migrate four S3 buckets in parallel between two RustFS clusters using a YAML runbook, a Python orchestrator, and a single Grafana dashboard that shows all pairs. One pair is pre-configured to fail so you can practice the retry workflow.

### Observability and verification

- **[Real-Time Migration Monitoring with Prometheus and Grafana](./godwit-grafana-dashboards-lab/README.md)** — Scrape Godwit Sync's built-in Prometheus metrics every 5 seconds and render them in a pre-provisioned 52-panel Grafana dashboard. Tracks throughput, latency, multipart uploads, retries, and verification across a multi-round, three-hop migration.
- **[Verifying S3 Migrations](./verifying-s3-migrations-lab/README.md)** — Walk through the `godwit plan` subcommands to list migration runs, inspect object counts and storage class distribution, surface failed or case-conflicting objects, and generate a compliance audit report from the state database.

### Authentication

- **[AWS S3 Authentication Methods Compared: Static Keys, IAM Roles, STS, and OIDC](./github-actions-oidc-lab/README.md)** — Compare AWS S3 authentication methods by leak blast radius, credential lifetime, and rotation cost. Decision matrix maps each deployment shape to the right auth mode.

## How the labs work

Each lab ships with a `docker-compose.yml` that provisions the object storage endpoints (MinIO, RustFS, Garage, or Moto), any supporting services (Prometheus, Grafana), and a seed step that populates the source buckets. A migration script or YAML runbook then invokes Godwit Sync against the local stack and writes results to a state database. All state lives in Docker volumes, so a lab can be reset to a clean slate and re-run.

## Supported S3-compatible environments

The labs exercise S3-compatible object stores that run locally under Docker:

- **MinIO** — primary test target with full S3 API coverage.
- **RustFS** — used for multi-cluster and multi-bucket scenarios.
- **Garage** — used as a cross-provider transfer target.
- **Moto** — used to emulate AWS S3 storage classes and Object Lock behavior.

## Disclaimer

These labs are provided **as-is** for educational and evaluation purposes. Use them at your own risk. The authors and Godwit.io assume no liability for any damage or data loss resulting from running these labs.

## License

The scripts, configuration files, and documentation in this repository are free to use, modify, and distribute under the [MIT License](./LICENSE).

**Note:** [Godwit Sync](https://godwit.io) itself is proprietary licensed software. These labs demonstrate its usage but do not grant any license to the Godwit Sync application. A valid Godwit Sync license is required for production use.
