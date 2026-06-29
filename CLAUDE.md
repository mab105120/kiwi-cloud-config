# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Common Commands

```bash
# Synthesize CloudFormation templates (validate CDK code)
cdk synth

# Deploy all stacks to dev (default)
cdk deploy --all

# Deploy targeting a specific environment
cdk deploy --all -c env=dev

# Diff before deploying
cdk diff --all

# Destroy stacks (careful — RDS uses RemovalPolicy.DESTROY)
cdk destroy --all
```

## Architecture

This is an **AWS CDK (Python)** project that provisions infrastructure for the Kiwi application. Target account is `453542520413`, region `us-east-2`.

### Stack layout

`app.py` is the CDK entry point. It reads an environment name from CDK context (`-c env=dev`, defaulting to `dev`) and instantiates three stacks:

1. **`CiCdStack`** (`stacks/cicd_stack.py`) — Stands alone (no VPC/DB dependency). Provisions GitHub Actions OIDC-based deployments:
   - Registers GitHub's OIDC provider (`token.actions.githubusercontent.com`) in the AWS account.
   - Creates an IAM role `github-actions-kiwi-deploy-{env}` that GitHub Actions assumes via `sts:AssumeRoleWithWebIdentity`.
   - In `prod`, the trust policy restricts to `refs/heads/main` only; in other envs any ref is allowed.
   - Grants the role broad permissions over CloudFormation, EC2, RDS, Secrets Manager, Lambda, IAM (scoped to CDK roles), S3 (CDK bootstrap bucket), ECR, SSM, and STS.
   - Outputs `GitHubActionsRoleArn` — set this as the `AWS_ROLE_ARN` secret in GitHub Actions.

2. **`VpcStack`** (`stacks/vpc_stack.py`) — Creates a VPC with public + private subnets across 2 AZs, 1 NAT gateway, and two security groups:
   - `db-sg`: restricts inbound to MySQL port 3306 from the Lambda SG only.
   - `lambda-sg`: attached to Lambda functions that need DB access; allow-all outbound.

3. **`DatabaseStack`** (`stacks/database_stack.py`) — Depends on `VpcStack`. Creates:
   - Two Secrets Manager secrets (master admin credentials + `kiwidbuser` app credentials).
   - An RDS MySQL 8.0.35 instance (`t4g.micro`) in private subnets, storage-encrypted, not publicly accessible.
   - A **custom resource** backed by `lambda/create_db_user/` that runs on stack deploy to create the `kiwidbuser` MySQL user and grant it `SELECT/INSERT/UPDATE/DELETE` on the database. The Lambda runs inside the VPC to reach the RDS instance.

### Lambda: `create_db_user`

Located in `lambda/create_db_user/`. Bundled via CDK's `BundlingOptions` using the Python 3.11 Lambda image (installs `pymysql` from `lambda/create_db_user/requirements.txt` into the asset). The handler is idempotent on `Create`/`Update` events and no-ops on `Delete`.

### Environment configuration

Environment-specific values live in `cdk.json` under the `context` key. Each environment entry can have `account`, `region`, `db_name`, and `github_repo`. Currently only `dev` is defined (`github_repo: mohdbourji/kiwi-cloud-config`).
