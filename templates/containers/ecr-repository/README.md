# `containers/ecr-repository`

An ECR repository with immutable tags, scan on push, and a lifecycle policy
generated from two knobs — plus a raw-JSON escape hatch for the rules those knobs
cannot express.

## Usage

```bash
./bin/cfn deploy containers/ecr-repository --env dev --param RepositorySuffix=api
```

Push to it:

```bash
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

docker build -t example-app/api:$(git rev-parse --short HEAD) .
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/example-app/api:$(git rev-parse --short HEAD)
```

## Immutable tags, and what they cost you

`IMMUTABLE` is the default. A tag, once pushed, always resolves to the same
digest. This is what makes "the image we tested is the image that is running" a
fact rather than a hope — with mutable tags, a redeploy of the same task
definition can pull different bytes.

The cost is that you cannot push `:latest` twice. **Tag with the commit SHA**,
and treat `:latest` as something you do not use. If you have a workflow that
genuinely needs a moving tag, `MUTABLE` is there, but understand that you have
given up reproducible deploys to get it.

## One repository per image, not per environment

This is the only template in the library with **no `Environment` parameter**, and
the omission is the point. The intended flow is:

1. CI builds `example-app/api:abc1234` once.
2. That exact digest is deployed to dev, then staging, then prod.

Building a separate image per environment means prod runs bytes that were never
tested anywhere — a different build, from a different machine, at a different
time. The repository is shared; what changes per environment is which tag the
service points at.

## Lifecycle policy

Without one, every image you ever built is stored forever at $0.10/GB-month. For
a service with a busy CI pipeline this is usually the largest ECR line item by an
order of magnitude.

The generated policy has two rules, and their order is load-bearing — ECR
requires the `tagStatus: any` rule to carry the highest `rulePriority`:

| Priority | Rule | Default |
|----------|------|---------|
| 1 | Expire untagged images older than N days | 14 days |
| 2 | Keep only the last N images | 30 |

**Set `KeepLastNImages` above your rollback depth.** Expiring an image you might
need to roll back to converts a bad deploy into an outage.

For rules the knobs cannot express — keeping tagged releases forever while
expiring feature branches after a week — set `LifecyclePolicyText` to raw JSON.
It replaces the generated policy entirely.

## Cross-account pull

`CrossAccountPullAccountIds` grants **pull only**: `GetDownloadUrlForLayer`,
`BatchGetImage`, `BatchCheckLayerAvailability`, `DescribeImages`. It deliberately
does not include `ecr:PutImage`, so a consuming account cannot overwrite the tag
it is about to deploy.

Consumers also need the S3 gateway endpoint (or NAT) to fetch layers — ECR stores
image layers in S3 and the pull will hang without it.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
