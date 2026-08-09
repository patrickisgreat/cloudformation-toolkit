# `foundation/vpc`

A multi-AZ VPC with public and private subnets, a NAT posture you choose
explicitly, gateway and interface endpoints, and optional flow logs. Nothing else
in this library runs until this exists.

## Usage

```bash
./bin/cfn deploy foundation/vpc --env dev
```

Nested inside a stack:

```yaml
Network:
  Type: AWS::CloudFormation::Stack
  Properties:
    TemplateURL: ../../templates/foundation/vpc/template.yaml
    Parameters:
      NamePrefix: !Ref NamePrefix
      Environment: !Ref Environment
      NatGatewayMode: single
```

## The three decisions

Everything else has a defensible default. These do not.

### 1. `NatGatewayMode` — this is the cost decision

A NAT gateway is about **$32/month plus $0.045/GB processed**, and it is the
single most common surprise on an AWS bill for a small workload.

| Mode | Monthly floor | Survives an AZ failure | Use when |
|------|---------------|------------------------|----------|
| `none` | $0 | n/a — no egress at all | Workloads that only call AWS APIs. Pair with the endpoint toggles below. |
| `single` | ~$32 | No — private egress dies with the AZ | Dev and staging, and prod workloads that tolerate an egress outage. |
| `per-az` | ~$32 × AZs | Yes | Prod workloads that call the public internet on the request path. |

`single` is the default because it is the cheapest thing that works, and because
the failure it exposes (egress down in an AZ outage) is one you should choose
deliberately rather than pay for by accident.

### 2. `AvailabilityZoneCount` — 2 or 3

Two is the minimum an ALB and Multi-AZ RDS will accept. Three is what you want in
prod: losing one AZ costs a third of capacity instead of half, so the remaining
zones do not need 2× headroom.

Subnets are carved from `VpcCidr` with `Fn::Cidr` — six equal blocks, public
first, private second. There are no per-subnet CIDR parameters on purpose: six
CIDR parameters is six chances to write an overlapping range, and the failure
shows up as a routing mystery weeks later.

### 3. Endpoints — how you make `NatGatewayMode: none` work

Gateway endpoints (`EnableS3Endpoint`, `EnableDynamoDbEndpoint`) are **free** and
on by default. They also route S3 and DynamoDB traffic off the NAT gateway, so
they reduce the bill even when NAT is on.

Interface endpoints cost roughly **$7/month each per AZ**. The set that makes a
Fargate service run with no NAT at all:

| Toggle | Gives you |
|--------|-----------|
| `EnableS3Endpoint` (default on) | Image layer download — ECR stores layers in S3 |
| `EnableEcrEndpoints` | `ecr.api` + `ecr.dkr` — image manifest pull and auth |
| `EnableLogsEndpoint` | `awslogs` driver can ship container logs |
| `EnableSecretsManagerEndpoint` | Task definition secret injection |
| `EnableSsmEndpoints` | `ssm` + `ssmmessages` — ECS Exec and Session Manager |

With three AZs, ECR + Logs + Secrets is about $63/month — more than one NAT
gateway. The endpoints win when you are running several AZs' worth of traffic
through NAT, or when you need the private-only network posture regardless of
cost. Below that, `single` NAT is cheaper. Do the arithmetic for your case rather
than assuming endpoints are the frugal option.

## What it does not do

- **No exports.** Outputs are plain outputs, not `Export`ed values. A
  cross-stack `Fn::ImportValue` makes the producing stack undeletable while any
  consumer exists, which is exactly the wrong coupling for a network you may need
  to rebuild. Stacks pass these outputs down as nested-stack parameters instead;
  for manual wiring, `./bin/cfn outputs foundation/vpc --env dev`.
- **No IPv6, no Transit Gateway, no peering.** Those are per-organization
  decisions that belong in a stack, not in the primitive.
- **Flow logs are off by default.** On a busy VPC they are a real line item. Turn
  them on in prod, and anywhere you need to answer "did this actually talk to
  that".

## Interaction with other templates

Every compute template in this library takes `VpcId` and a subnet list. The
normal wiring:

| Consumer | Subnets to pass |
|----------|-----------------|
| `containers/alb` (internet-facing) | `PublicSubnetIds` |
| `containers/fargate-service` | `PrivateSubnetIds` |
| `serverless/lambda-function` (VPC-attached) | `PrivateSubnetIds` |
| `database/*` | `PrivateSubnetIds` |

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
