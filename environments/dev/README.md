# environments/dev

The composition layer. `env.json` says *where* and *how* to deploy; the files in
`params/` say *what* to deploy with.

## Layout

```
environments/dev/
├── env.json                    region, profile, stack naming, tags, capabilities
└── params/
    ├── vpc.json                -> templates/foundation/vpc
    └── ecr-repository.json     -> templates/containers/ecr-repository
```

A parameter file's **name is its target**. `bin/cfn deploy <target>` looks for
`params/<target-slug>.json`, and the slug is the last path segment of the
template directory. `params/vpc.json` therefore applies to
`templates/foundation/vpc`. A file whose name matches nothing is a silent
fallback to template defaults, which is why `tests/test_conventions.py` fails the
build on one.

## Deploying

```bash
./bin/cfn deploy foundation/vpc --env dev          # uses params/vpc.json
./bin/cfn diff   foundation/vpc --env dev          # change set preview, discarded
./bin/cfn deploy foundation/vpc --env dev --param NatGatewayMode=none
```

`--param` overrides win over the file, so testing one value does not mean editing
committed config.

## `env.json`

| Key | Meaning |
|-----|---------|
| `region` | Region every command targets |
| `profile` | AWS CLI profile; empty uses the default credential chain |
| `stack_prefix` | Stack names become `<prefix>-<target>`, e.g. `dev-vpc` |
| `artifacts_bucket` | **Required for stacks with nested templates.** `bin/cfn` runs `aws cloudformation package` to upload children here |
| `capabilities` | `CAPABILITY_IAM` / `CAPABILITY_NAMED_IAM` for templates creating roles; `CAPABILITY_AUTO_EXPAND` for nested stacks |
| `tags` | Applied to every stack. CloudFormation propagates them to every resource type that supports tagging, which is why templates rarely tag inline |

`artifacts_bucket` is empty here because it must be a bucket you own. Create one
(`data/s3-bucket` with `BucketSuffix=artifacts` works) and fill it in before
deploying anything under `stacks/`.

## Adding an environment

Copy the directory and change three things:

```bash
cp -r environments/dev environments/prod
# 1. env.json: stack_prefix -> "prod", region if different, its own artifacts bucket
# 2. params/*.json: Environment -> "prod", and the values that should differ
# 3. commit
```

Values worth differing in prod, and why:

| Parameter | dev | prod |
|-----------|-----|------|
| `NatGatewayMode` | `single` | `per-az` — egress survives an AZ failure |
| `AvailabilityZoneCount` | `2` | `3` — losing one AZ costs a third, not a half |
| `EnableDeletionProtection` | `false` | `true` |
| `MinCapacity` | `1`–`2` | at least `2` |
| `LogRetentionDays` | `30` | `90`+ |
| `EnableFlowLogs` | `false` | `true` |

## What is not here

**No state file and no `--parameter-overrides` for secrets.** CloudFormation
holds the state, and secrets are generated into Secrets Manager by the templates
that need them (`foundation/secret`,
`database/aurora-serverless-v2`) rather than passed in. A value that goes through
a parameter file is a value in git.
