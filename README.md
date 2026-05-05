# Godwit Sync Labs

Hands-on Docker labs for [Godwit Sync](https://godwit.io). Each lab is a self-contained environment you can clone and run locally.

## Labs

| Lab                                                                                                                       | Description                                                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [AWS S3 Authentication Methods Compared: Static Keys, IAM Roles, STS, and OIDC](./github-actions-oidc-lab/README.md)      | Compare AWS S3 authentication methods by leak blast radius, credential lifetime, and rotation cost. Decision matrix maps each deployment shape to the right auth mode.                                                  |
| [Monitor S3 Migrations in Real Time with Godwit Sync, Prometheus, and Grafana](./godwit-grafana-dashboards-lab/README.md) | Track S3 migration progress, throughput, latency, multipart uploads, retries, and verification in real time with Godwit Sync's built-in Prometheus metrics and a pre-built Grafana dashboard.                           |
| [Migrate Multiple S3 Buckets in Parallel](./multi-bucket-migration-lab/README.md)                                         | Migrate multiple S3 buckets in parallel using one Godwit config file per pair, a short orchestrator script, and a single Grafana dashboard showing all runs.                                                            |
| [S3 Migration Guide: How to Upload, Transfer, and Download S3 Data](./s3-migration-guide-lab/README.md)                   | Step-by-step S3 migration guide covering uploads to S3, S3-to-S3 transfers between providers, and downloading S3 buckets to local disk. Includes resumable transfers, checksum verification, and a hands-on Docker lab. |
| [S3 Version History Migration: Step-by-Step with Godwit Sync](./s3-version-history-migration-lab/README.md)               | Migrate every S3 version: current, noncurrent, and delete markers with Godwit Sync's --version-mode flag. Includes full history, point-in-time filtering, Object Lock buckets, and a hands-on Docker lab.               |
| [How to Verify S3 Migrations with Godwit Sync](./verifying-s3-migrations-lab/README.md)                                   | Verify S3 migrations, list failed objects, inspect runs, and validate checksums with Godwit Sync. Build an audit trail for every object.                                                                                |

## Disclaimer

These labs are provided **as-is** for educational and evaluation purposes. Use them at your own risk. The authors and Godwit.io assume no liability for any damage or data loss resulting from running these labs.

## License

The scripts, configuration files, and documentation in this repository are free to use, modify, and distribute under the [MIT License](./LICENSE).

**Note:** [Godwit Sync](https://godwit.io) itself is proprietary licensed software. These labs demonstrate its usage but do not grant any license to the Godwit Sync application. A valid Godwit Sync license is required for production use.
