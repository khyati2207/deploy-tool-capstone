# Deploy Tool Capstone

A Python CLI that builds Create React App or Vite projects in Docker, provisions an S3 static website with Terraform, and deploys it with boto3. The first implementation focuses on the core deploy path; monitoring is intentionally excluded.

## Requirements

- Python 3.10+
- Docker Desktop (for isolated builds)
- Terraform 1.5+
- An AWS account and credentials configured through the standard AWS CLI credential chain
- Node/npm or Yarn lockfile in the React project

## Install the CLI

From this repository:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
```

## Deploy a React app

Run these commands from the root of the CRA or Vite project:

```bash
deploy-tool init
deploy-tool config
deploy-tool config --environment staging
deploy-tool deploy
deploy-tool status
deploy-tool rollback
```

`deploy-tool init` creates `deploy-tool.json`. Set the AWS region and, if needed, an AWS profile there. The tool detects CRA/Vite and npm/yarn/pnpm lockfiles. Set `project.build_command` and `project.output_dir` to customize nonstandard projects. Build environment variables can come from the React project's `.env.production` file or the CI environment; do not commit secrets.

## Commands

| Command | Purpose |
|---|---|
| `deploy-tool init` | Create project configuration without overwriting existing config |
| `deploy-tool config` | Display configuration |
| `deploy-tool config --environment staging` | Select development, staging, or production |
| `deploy-tool deploy` | Build, provision S3, upload a release, and print the URL |
| `deploy-tool status` | Show bucket, current release, and URL |
| `deploy-tool rollback` | Restore the previous release from its S3 archive |

## Architecture and scope

The CLI detects CRA/Vite, builds in a Node Docker container with a reusable npm package cache, asks Terraform to create a versioned S3 bucket configured for static website hosting, and uses boto3 to publish files. Each release is archived in S3 so the CLI can restore the previous release. A GitHub Actions starter is in `templates/github-actions.yml`; update the CLI install path to match how your team shares the tool. GitLab CI can invoke the same CLI. EC2 and the monitoring stack are out of scope for this static-site MVP.

## AWS permissions

The configured identity needs the permissions required by Terraform to create and manage the S3 bucket, website configuration, bucket policy, public-access block, versioning, and lifecycle rule. It also needs STS `GetCallerIdentity`, S3 object upload/read/list/copy permissions, and bucket inspection. For a real team deployment, provision a dedicated least-privilege role rather than using an administrator key.

## Important security note

This MVP uses the S3 website endpoint, which serves site objects publicly over HTTP. Do not upload private content or secrets. For production HTTPS, use a private S3 bucket behind CloudFront with Origin Access Control and a TLS certificate.

## Current limitations

- Terraform state uses the local default backend; configure a shared remote state backend before team use.
- The CLI provisions one bucket per project/environment and uses public S3 website hosting.
- Build variables are inherited from the process environment; no secret manager integration is included yet.
- No monitoring stack, EC2 hosting, webhook server, or automated CI workflow is provisioned by this initial MVP.
