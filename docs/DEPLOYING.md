# Deploying

## Setup

```bash
make install                  # .venv with cfn-lint + pytest
brew install awscli           # or your platform's equivalent, AWS CLI v2
aws sts get-caller-identity   # confirm you are pointed where you think
```

Then edit `environments/dev/env.json`: set `region`, `profile` if you use one,
and `artifacts_bucket` (required for anything under `stacks/`, which uses nested
templates).

## The loop

```bash
./bin/cfn params containers/fargate-service     # what does it need?
./bin/cfn diff  foundation/vpc --env dev        # what would change?
./bin/cfn deploy foundation/vpc --env dev       # do it
./bin/cfn outputs foundation/vpc --env dev      # what did I get?
```

`cfn diff` is the closest CloudFormation gets to `terraform plan`: it builds a
change set with `--no-execute-changeset`, prints the actions and which resources
would be **replaced**, then deletes the change set. Nothing is applied.

Read the `Replacement` column. `True` on a database or a bucket means the
resource is destroyed and recreated — a rename of a physical name, or a change to
an immutable property, and often not what you intended.

## Targets and naming

A target resolves in this order: a literal path, then `stacks/<target>`, then
`templates/<target>`.

```bash
./bin/cfn deploy container-service --env dev       # stacks/container-service
./bin/cfn deploy foundation/vpc --env dev          # templates/foundation/vpc
```

The stack name is `<stack_prefix>-<slug>` — `dev-vpc`, `dev-container-service` —
so one account holds `dev-` and `prod-` copies without collision.

## Parameters

`environments/<env>/params/<slug>.json` is found automatically. `--param K=V`
overrides it, repeatably:

```bash
./bin/cfn deploy foundation/vpc --env dev --param NatGatewayMode=none
```

Overrides win over the file, so testing one value never means editing committed
config.

**No secrets in parameter files.** A value passed as a parameter is visible in
the change set, in `describe-stacks`, and in any CI log that prints them — even
with `NoEcho`, which only masks the API response. Templates that need a secret
generate it into Secrets Manager (`foundation/secret`,
`database/aurora-serverless-v2`) and pass the ARN.

## Order of operations

CloudFormation orders resources *within* a stack, not between them. For a
first-time environment:

1. `foundation/vpc` — nothing runs without a network.
2. `foundation/github-oidc-role` — so CI can take over from here.
3. `containers/ecr-repository` and a `data/s3-bucket` for artifacts.
4. Everything else, in whatever order its inputs become available.

`stacks/container-service` collapses steps 1–4 into one deploy, at the cost of
putting your network in the same stack as your service — see its README on when
to split.

## Deploying from CI

`foundation/github-oidc-role` creates a role GitHub Actions assumes over OIDC, so
there are no long-lived keys in repository secrets:

```yaml
permissions:
  id-token: write        # without this no token is minted and the step fails
  contents: read

steps:
  - uses: actions/checkout@v4
  - uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: arn:aws:iam::<account>:role/<prefix>-github-deploy
      aws-region: us-east-1
  - run: make install
  - run: ./bin/cfn check
  - run: ./bin/cfn deploy container-service --env dev --yes
```

`--yes` skips the confirmation prompt. Use it only in CI.

## When a deploy goes wrong

**Stuck in `CREATE_IN_PROGRESS`.** Usually a certificate waiting for DNS
validation that will never resolve — the hosted zone is not authoritative for the
domain. Check the nameservers.

**`ROLLBACK_COMPLETE`.** A create failed and rolled back. This state cannot be
updated; delete the stack and deploy again. Find the cause first:

```bash
./bin/cfn events container-service --env dev
```

The **oldest** `*_FAILED` event is the real cause; everything after it is
consequence.

**A nested stack failed.** The parent rolls back, so a bad DNS parameter can undo
the VPC. Resources carrying `DeletionPolicy: Retain` survive but become orphans
nothing manages. This is the main argument for splitting foundational stacks out
once an environment matters.

**An update failed and rolled back.** The stack is back where it was. Read the
events, fix, redeploy. If the rollback itself fails, `continue-update-rollback`
is the escape hatch, sometimes with `--resources-to-skip`.

## Deleting

```bash
./bin/cfn delete container-service --env dev
```

It asks first. Note what survives on purpose: S3 buckets, ECR repositories,
KMS keys, secrets, DynamoDB tables and log groups carry
`DeletionPolicy: Retain`, and Aurora clusters take a final snapshot. Deleting the
stack does not delete your data — you have to mean it.

## Drift

```bash
./bin/cfn drift container-service --env dev
```

Anything `MODIFIED` was changed outside CloudFormation. Reconcile it: either
bring the change into the template, or revert it. Drift that nobody reconciles is
how a template stops describing reality, and the next deploy is where you find
out.
