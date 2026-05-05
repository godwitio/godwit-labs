---
title: "Lab: GitHub Actions OIDC to AWS S3 with Godwit Sync"
github_issue: 84
---

# Lab: GitHub Actions OIDC to AWS S3 with Godwit Sync

Hands-on lab for the article:
**[AWS S3 Authentication Methods Compared: Static Keys, IAM Roles, STS, and OIDC](https://godwit.io/blog/aws-s3-authentication-methods)**

Wire a GitHub Actions workflow to a least-privileged AWS IAM role through OpenID Connect, then run Godwit Sync against S3 with zero long-lived keys in the repo secret store. The end state is the CI/CD pattern recommended in the article's [Decision Matrix](https://godwit.io/blog/aws-s3-authentication-methods#decision-matrix-pick-the-right-method-for-your-scenario) and the counter to the long-lived-keys anti-pattern it warns about.

## Lab Overview

Unlike the other labs in this repository, this one targets **real AWS and a real GitHub repository**. OIDC federation is a trust relationship between `token.actions.githubusercontent.com` and AWS IAM; it cannot be simulated with a local S3 emulator. Plan for 15 to 20 minutes and a few cents of AWS spend (one S3 bucket, a handful of PUT/GET calls).

You will:

1. Create an S3 bucket in your AWS account.
2. Register `token.actions.githubusercontent.com` as an IAM OIDC provider (one-time per account).
3. Create an IAM role whose trust policy pins a specific GitHub repository and branch.
4. Commit a GitHub Actions workflow that assumes that role via OIDC and invokes Godwit Sync.
5. Run the workflow, verify the sync, and inspect CloudTrail to confirm the call is attributed to the OIDC-assumed role.

## Why OIDC for CI/CD

The article ranks `assume-role` via OIDC above every other CI credential mechanism because the credentials minted inside the workflow are short-lived (default 1 hour, capped at the role's `MaxSessionDuration`), scoped to a specific repo/branch/environment, and impossible to reuse after the job exits. A leaked workflow log or a rogue third-party action cannot exfiltrate a long-lived key because no long-lived key ever exists.

## Prerequisites

- **AWS account** with permission to create IAM roles, OIDC providers, and S3 buckets.
- **AWS CLI v2** authenticated as an admin-capable principal (`aws sts get-caller-identity` should succeed).
- **GitHub repository** you own or have admin access to. A fresh private repo works fine.
- **Godwit Sync** — the example workflow installs it via the official Homebrew tap (`brew tap godwitio/packages` + `brew install godwit-sync`), matching the install path documented for Mac and Linux developers on the Godwit site. No other Godwit setup is required.
- Default region for this lab: `us-east-1`. Adjust `AWS_REGION` if you want a different one.

## Setup

All scripts are idempotent (rerunning will not double-create resources) and require admin AWS credentials in your shell.

### 1. Export required variables

```bash
export AWS_REGION=us-east-1
export LAB_PREFIX=godwit-oidc-lab
export GITHUB_REPO=your-org/your-repo      # e.g. acme/data-sync
export GITHUB_REF=refs/heads/main          # the branch the workflow runs on
```

`GITHUB_REPO` and `GITHUB_REF` are baked into the trust policy; only workflows in that repo, running on that ref, can assume the role.

### 2. Create the S3 bucket and seed it

```bash
./infra/setup-bucket.sh
```

Creates `s3://${LAB_PREFIX}-$(aws sts get-caller-identity --query Account --output text)` and uploads three small objects under `source/` so the workflow has something to sync.

### 3. Register the GitHub OIDC provider

```bash
./infra/setup-oidc.sh
```

This is a one-time per-account operation. If the provider already exists the script is a no-op.

### 4. Create the IAM role

```bash
./infra/setup-role.sh
```

Creates `${LAB_PREFIX}-role` with:

- **Trust policy** pinned to `${GITHUB_REPO}:ref:${GITHUB_REF}`. No other repo and no other branch can assume it. See the article's [STS AssumeRole for Cross-Account Access](https://godwit.io/blog/aws-s3-authentication-methods#sts-assumerole-for-cross-account-access) for what a trust policy does and why the external-ID pattern matters for third parties (OIDC is GitHub's equivalent of that mechanism, with the `sub` claim playing the role of the external ID).
- **Permissions policy** granting `s3:GetObject`, `s3:PutObject`, and `s3:ListBucket` only on the lab bucket.

The role ARN is printed at the end; note it down.

### 5. Commit the workflow to your repository

Copy `workflows/godwit-sync.yml` into your repo at `.github/workflows/godwit-sync.yml`. Set three repository variables (Settings → Secrets and variables → Actions → Variables):

| Variable       | Value                                                       |
| -------------- | ----------------------------------------------------------- |
| `AWS_ROLE_ARN` | Output from `setup-role.sh`                                 |
| `AWS_REGION`   | `us-east-1` (or whichever region you used)                  |
| `LAB_BUCKET`   | `${LAB_PREFIX}-<account-id>` (printed by `setup-bucket.sh`) |

Commit and push the workflow file to the branch matching `GITHUB_REF`.

### 6. Run the workflow

Trigger it manually from the Actions tab (`workflow_dispatch`) or push a commit to the branch. The run should:

1. Request an OIDC token from GitHub and call `sts:AssumeRoleWithWebIdentity` against your IAM role, exporting short-lived `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` into the job environment.
2. Print `aws sts get-caller-identity` to confirm the assumed role — the output shows the role ARN and session name, which is the first thing to check when debugging trust-policy failures.
3. Install Godwit Sync via the official Homebrew tap (`brew tap godwitio/packages` + `brew install godwit-sync`).
4. Run `godwit sync` with `--source-auth env` and `--destination-auth env` to mirror `s3://${LAB_BUCKET}/source/` into `s3://${LAB_BUCKET}/replica/`. The `env` mode picks up the short-lived variables the action exported without any Godwit-specific plumbing — see the article's [Environment Variables](https://godwit.io/blog/aws-s3-authentication-methods#environment-variables) section for why this composes cleanly with any secret-injection mechanism, not just OIDC.
5. List `s3://${LAB_BUCKET}/replica/` with `aws s3 ls` to confirm the three objects landed.

### 7. Verify

After the workflow finishes:

```bash
aws s3 ls s3://${LAB_PREFIX}-$(aws sts get-caller-identity --query Account --output text)/replica/
```

Three objects should appear under the `replica/` prefix.

Confirm the call used the OIDC-assumed role, not a human identity:

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity \
  --max-results 5 \
  --query 'Events[].{Time:EventTime,Principal:Username,Session:CloudTrailEvent}'
```

The most recent event should have `Principal` matching your role's session name and `userIdentity.type` of `WebIdentityUser` in the event JSON.

## What This Proves

| Claim in the article                                | How the lab demonstrates it                                                                                                                                         |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OIDC replaces long-lived keys in CI                 | No `AWS_ACCESS_KEY_ID` secret exists in the repo                                                                                                                    |
| Trust policy scopes the credential                  | Changing `GITHUB_REF` or committing from a different branch fails `sts:AssumeRoleWithWebIdentity` with `AccessDenied`                                               |
| Credentials are short-lived                         | The session expires after the role's `MaxSessionDuration`; the **Verify the role** step runs `aws sts get-caller-identity` immediately after assume-role to confirm the session is live |
| Godwit Sync picks up SDK credentials transparently  | `--source-auth env` and `--destination-auth env` read whatever `aws-actions/configure-aws-credentials` exported, no Godwit-specific auth plumbing                  |
| CloudTrail attributes calls to the role, not a user | `AssumeRoleWithWebIdentity` + subsequent `GetObject`/`PutObject` events show the role as `userIdentity.sessionContext.sessionIssuer`                                |

## Security Hardening Beyond the Basics

The lab's trust policy pins the repo and ref. For production consider:

- **Pin an environment** instead of (or in addition to) a branch: `repo:org/repo:environment:production`. Pair this with a protected GitHub environment requiring manual approval before the workflow can run.
- **Pin a specific workflow job**: `repo:org/repo:job_workflow_ref:org/repo/.github/workflows/godwit-sync.yml@refs/heads/main` prevents a new workflow file in the same repo from assuming the role.
- **Scope `s3:GetObject`/`PutObject` to a single prefix**, not the whole bucket.
- **Require a specific AWS session duration** with `sts:DurationSeconds` in the workflow call, shorter than the role's `MaxSessionDuration`.

All of these follow from the article's principle: every extra scope tightens the blast radius if the OIDC token or IAM role trust is ever misused.

## Why the Lab Uses `aws-actions/configure-aws-credentials` Instead of Godwit's Web-Identity Mode

Godwit has a native `--source-auth web-identity` mode that calls `AssumeRoleWithWebIdentity` directly from a JWT file. That mode is intentionally **not** used here. On GitHub-hosted runners the OIDC token is fetched from an HTTP endpoint (`ACTIONS_ID_TOKEN_REQUEST_URL`), not mounted as a file, and every CI platform has its own flavor of that endpoint. Godwit deliberately doesn't bake per-platform OIDC fetchers into the binary.

The canonical pattern for CI is: the platform's official credential action performs the OIDC exchange and exports env vars; Godwit consumes those env vars via `--source-auth env`. This lab follows that pattern.

`--source-auth web-identity` is the right mode when a platform (or your own tooling) writes a JWT to disk and sets `AWS_WEB_IDENTITY_TOKEN_FILE` — EKS IRSA, Kubernetes projected service-account tokens, custom workload-identity rigs. Those live outside this lab's scope.

## Related Pattern: Sync from EC2 (No OIDC Needed)

The workflow in this lab runs on a GitHub-hosted runner. If your sync job instead runs on an EC2 instance (cron, systemd timer, self-hosted runner, or a batch workload), Godwit supports a shorter path with no action and no OIDC at all:

```bash
godwit sync \
  --source s3://source-bucket \
  --destination s3://partner-bucket \
  --source-endpoint s3.amazonaws.com --source-region us-east-1 \
  --source-auth iam \
  --destination-endpoint s3.amazonaws.com --destination-region us-east-1 \
  --destination-auth assume-role \
  --destination-role-arn arn:aws:iam::333333333333:role/PartnerWriter \
  --destination-role-session migrate-$(hostname)-$(date +%Y-%m-%d)
```

The EC2 instance role reads the source directly, signs `sts:AssumeRole` against the partner role, and the returned session credentials write to the partner bucket. Zero long-lived keys, no external action. See the article's [STS AssumeRole for Cross-Account Access](https://godwit.io/blog/aws-s3-authentication-methods#sts-assumerole-for-cross-account-access) section for the trust-policy side of this setup.

## Troubleshooting

- **`Not authorized to perform sts:AssumeRoleWithWebIdentity`** -- the trust policy doesn't match the token's `sub` claim. Double-check `GITHUB_REPO` and `GITHUB_REF` and re-run `setup-role.sh`. Use the debug step in the workflow to print the token's `sub` field.
- **`Could not load credentials from any providers`** in the Godwit step -- `aws-actions/configure-aws-credentials` did not run or did not export to `GITHUB_ENV`. Make sure `permissions: id-token: write` is set at the job (or workflow) level.
- **`403 AccessDenied` on `GetObject`** -- the permissions policy is scoped to `${LAB_BUCKET}`. If you renamed the bucket after `setup-role.sh` ran, rerun it.

## Teardown

```bash
./infra/teardown.sh
```

Removes the role, the bucket (and its contents), and the inline policies. Leaves the OIDC provider in place (it is a shared account-level resource; delete it with `aws iam delete-open-id-connect-provider --open-id-connect-provider-arn ...` if this is a scratch account).

## Cross-References

- Article: [AWS S3 Authentication Methods: A Decision Guide](https://godwit.io/blog/aws-s3-authentication-methods)

### Canonical upstream documentation

The trust policy shape, the `aws-actions/configure-aws-credentials@v4` invocation, and the CLI calls in this lab are dictated by AWS and GitHub — there is no other correct form. These are the authoritative sources:

- [Configuring OpenID Connect in Amazon Web Services](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services) -- GitHub's official OIDC-to-AWS guide, including trust-policy `sub` claim formats and audience values.
- [`sts:AssumeRoleWithWebIdentity` API reference](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRoleWithWebIdentity.html) -- the STS call that exchanges the OIDC token for temporary credentials.
- [`aws-actions/configure-aws-credentials`](https://github.com/aws-actions/configure-aws-credentials) -- the GitHub Action used in the workflow; its README documents every supported input (`role-to-assume`, `role-session-name`, `aws-region`, `audience`, `role-duration-seconds`, and more).
- [Create a role for OpenID Connect federation (AWS IAM User Guide)](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html) -- AWS's reference for the OIDC provider + role setup this lab automates in `setup-oidc.sh` and `setup-role.sh`.

### Further reading

Both of these tutorials were reviewed while building this lab and are recommended if you want a second walkthrough of the OIDC-to-AWS pattern without the Godwit Sync layer:

- AWS Security blog, [Use IAM roles to connect GitHub Actions to actions in AWS](https://aws.amazon.com/blogs/security/use-iam-roles-to-connect-github-actions-to-actions-in-aws/) -- the official five-step walkthrough from the AWS Security team.
- DevOps Cube, [How to Configure GitHub Actions OIDC with AWS (Easy Tutorial)](https://devopscube.com/github-actions-oidc-aws/) -- community tutorial with additional examples for EC2 and EKS access.

<!-- Copyright (c) 2026 Godwit.io. Licensed under the MIT License. -->
