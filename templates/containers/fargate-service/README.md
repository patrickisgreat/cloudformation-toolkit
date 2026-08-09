# `containers/fargate-service`

A Fargate service: task definition, two IAM roles, log group, optional load
balancer attachment, and target-tracking autoscaling.

This is the template that covers most of what people mean by "deploy my app".
Go, Rust, C++, Java, Kotlin, C#/.NET, Node, TypeScript, Python, GraphQL servers,
REST APIs, and gRPC services all collapse into the same runtime shape — a
container that listens on a port. **Infrastructure cares about runtime shape, not
source language.** See [docs/ARCHETYPES.md](../../../docs/ARCHETYPES.md) for the
full mapping and the per-language image notes.

## Usage

```bash
./bin/cfn deploy containers/fargate-service --env dev \
  --param ImageUri=<account>.dkr.ecr.us-east-1.amazonaws.com/app/api:abc1234
```

Usually you want [`stacks/container-service`](../../../stacks/container-service)
instead, which wires the VPC, registry, cluster, load balancer, DNS, and this
service together from one parameter set.

## It runs workers too

Leave `ListenerArn` empty and the target group, listener rule, health checks, and
load balancer registration all disappear. What is left is a task running on a
schedule of its own — a queue consumer, a stream processor, a background worker.
The same template, one parameter apart.

## Two IAM roles, and why they are not one

| Role | Belongs to | Used for |
|------|-----------|----------|
| `ExecutionRole` | the ECS agent | Pulling the image, fetching injected secrets, creating log streams — **before** your code runs |
| `TaskRole` | your application | The AWS APIs your code calls: its tables, buckets, queues |

Merging them hands your application permission to read every secret the task
definition references, which is precisely what secret injection exists to
prevent. Grant application permissions through `TaskRoleManagedPolicyArn`; leave
the execution role alone.

## Secrets are injected, never templated

```
Secret1Name    = DB_PASSWORD
Secret1Arn     = arn:aws:secretsmanager:us-east-1:1234:secret:dev/app/db-AbCdEf
Secret1JsonKey = password
```

The container sees `DB_PASSWORD`. The task definition contains only the ARN, the
value is resolved by the ECS agent at task start, and the execution role is
granted read access to **exactly that ARN** — not to every secret in the account.

The ARN and the JSON key are separate parameters because ECS's `ValueFrom` wants
`<arn>:password::` while IAM wants the bare `<arn>`. Passing the suffixed string
to IAM matches nothing, and the failure is a task that will not start with an
`AccessDeniedException` naming a resource that looks correct.

## Four environment variable slots

`ENVIRONMENT` and `PORT` are always injected. Beyond that there are four
`EnvVarNName`/`EnvVarNValue` pairs.

This is a real limitation and worth being honest about: CloudFormation cannot map
over a list to build N container environment entries without the
`AWS::LanguageExtensions` transform, and that transform expands server-side —
cfn-lint cannot check the result and `describe-change-set` shows you the
unexpanded form. Four checkable slots beat an unbounded list nobody can review.

If you need more than four, the options in order of preference are: bake settings
into the image, read them from SSM Parameter Store or AppConfig at startup, or
fork this template and add slots.

## Scaling

Three target-tracking policies, and the interesting question is which signal to
scale on.

| Signal | Default | Use it when |
|--------|---------|-------------|
| `TargetCpuUtilization` | **65** | Always on. Good general proxy for load. |
| `TargetRequestsPerTask` | 0 (off) | **Best signal for a latency-sensitive HTTP service** — it reacts to load itself rather than to the symptom. Needs `ListenerArn` and `LoadBalancerFullName`. |
| `TargetMemoryUtilization` | 0 (off) | Rarely. A garbage-collected runtime (JVM, Go, .NET) holds memory at a high-water mark that adding tasks never reduces, so memory scaling on those ratchets up and never comes down. |

`ScaleInCooldownSeconds` (300) is deliberately five times
`ScaleOutCooldownSeconds` (60). Scaling out too eagerly costs money; scaling in
too eagerly costs availability.

`MinCapacity` defaults to 2 — the smallest number that survives a task
replacement or an AZ event without reaching zero capacity. `MaxCapacity` is your
cost cap and your blast-radius limit when a retry storm arrives.

## The two settings that cause mysterious failures

**`HealthCheckGracePeriodSeconds` (default 60).** How long after a task starts
before ECS trusts the load balancer's verdict. Too short and you get an infinite
kill-and-restart loop that looks exactly like a crash: the task is killed as
unhealthy while it is still warming up, replaced, and killed again. A JVM with a
large heap, or anything that loads a model at startup, needs several minutes.

**`StopTimeoutSeconds` (default 30).** Time between `SIGTERM` and `SIGKILL`. Set
it above your longest in-flight request or every deploy cuts responses off
mid-flight. Pair it with `DeregistrationDelaySeconds` (default 30, down from
AWS's 300) — that one only affects how long deploys take.

## gRPC

Set `ProtocolVersion: GRPC`. The target group then health-checks with gRPC status
codes rather than HTTP ones, so `HealthCheckPath` becomes a fully qualified
method such as `/grpc.health.v1.Health/Check`. The ALB requires TLS for gRPC, so
the listener must have a certificate.

## Deployment safety

The deployment circuit breaker is on with rollback. Without it, a broken image
rolls forward: ECS keeps replacing tasks that crash on start, the deploy hangs
for hours, and capacity drains as healthy old tasks are stopped to make room.

`MinimumHealthyPercent: 100` / `MaximumPercent: 200` means a deploy starts the
new task set before stopping any of the old one — no capacity dip, at the cost of
briefly running double.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
