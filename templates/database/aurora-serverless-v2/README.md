# `database/aurora-serverless-v2`

An Aurora Serverless v2 cluster (PostgreSQL or MySQL) that is private,
encrypted, and whose master password never passes through CloudFormation.

## Usage

```bash
./bin/cfn deploy database/aurora-serverless-v2 --env dev \
  --param VpcId=vpc-abc --param SubnetIds=subnet-a,subnet-b \
  --param ClientSecurityGroupId=<task-security-group>
```

Then give the application the credentials without ever handling them — pass
`MasterSecretArn` to `containers/fargate-service`:

```
Secret1Name = DB_PASSWORD
Secret1Arn  = <MasterSecretArn>
Secret1JsonKey = password
```

## There is no password parameter

Secrets Manager generates the password, and the cluster reads it through a
`{{resolve:secretsmanager:...}}` dynamic reference at deploy time. The value
never appears in the template, the change set, the stack events, or a CI log.

The generated password excludes `"@/\'`$&;|<>()[]{}` — RDS rejects some of those
in a master password outright, and the rest break connection strings.

## Capacity is the cost dial

Aurora Serverless v2 bills per **ACU-hour** (~$0.12); one ACU is roughly 2 GiB of
memory with matching CPU.

- `MinCapacityAcu: 0` lets the cluster **pause entirely when idle** — excellent
  for dev, at the cost of a several-second cold start on the first query after a
  pause.
- `MinCapacityAcu: 0.5` is the lowest always-on setting.
- `MaxCapacityAcu` is your ceiling. At 16 ACUs sustained that is roughly
  $1,400/month, so pick it as a budget, not as a guess at peak.

## `ReaderCount` is really about failover

`0` readers is fine for dev. But a single-instance cluster **has no failover
target**: Aurora recovers by creating a new instance, which takes minutes. One
reader gives you a read endpoint and a standby that can be promoted in under a
minute.

`ReaderEndpoint` is safe to use unconditionally — with no readers it resolves to
the writer.

## `db.serverless` is the whole trick

`DBInstanceClass: db.serverless` is what makes an instance serverless. Any other
class silently gives you a **provisioned instance billed by the hour**, in a
cluster that otherwise looks correctly configured. This template hardcodes it.

## Deletion behaviour

`DeletionPolicy: Snapshot` on the cluster: deleting the stack takes a final
snapshot rather than either destroying the data or leaving an orphan you keep
paying for. The instances are `Delete` — they hold no data of their own, and
retaining them would leave you paying for compute attached to nothing.

## Network posture

Ingress is granted to `ClientSecurityGroupId`, not to a CIDR, so access follows
the workload rather than an address range. `PubliclyAccessible` is hardcoded
`false` on every instance.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
