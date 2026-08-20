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

## Persistent storage is opt-in EFS

Fargate ephemeral storage vanishes with the task. Set `EfsFileSystemId` (from
[`data/efs-filesystem`](../../data/efs-filesystem)) to mount a persistent
volume at `EfsMountPath`, and pass `EfsAccessPointId` to mount through an
access point with IAM authorization — the recommended posture, which also
grants the task role client access scoped to exactly that access point. The
mount is always TLS; `data/efs-filesystem`'s file system policy denies
plaintext clients. Remember to allow the task security group NFS access on the
file system side (`ClientSecurityGroupId` over there takes
`TaskSecurityGroupId` from here).

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
<!-- Generated by `./bin/cfn docs`. Do not edit between these markers. -->

### Parameters

| Parameter | Description | Type | Default |
|-----------|-------------|------|---------|
| `NamePrefix` | Prefix for every resource this stack names. | `String` | **required** |
| `Environment` | Environment this service runs in. Injected as the ENVIRONMENT variable.<br>Allowed: `dev`, `staging`, `prod` | `String` | `dev` |
| `ServiceSuffix` | Distinguishes services under one prefix, e.g. "api" or "worker". | `String` | `app` |
| `ClusterName` | ECS cluster name, from containers/ecs-cluster. | `String` | **required** |
| `VpcId` | VPC the tasks and target group live in. | `AWS::EC2::VPC::Id` | **required** |
| `SubnetIds` | Subnets to place tasks in. Use private subnets; the load balancer is what lives in public ones. | `List<AWS::EC2::Subnet::Id>` | **required** |
| `AssignPublicIp` | Give each task a public IP. Only needed when tasks run in public subnets with no NAT gateway - a task in a private subnet with no route out cannot pull its image, and this is the wrong fix for that.<br>Allowed: `ENABLED`, `DISABLED` | `String` | `DISABLED` |
| `UseClusterCapacityProviderStrategy` | Inherit the cluster's Fargate/Spot mix. Set to false to pin this service to on-demand Fargate regardless of the cluster default - the right choice for a service that cannot tolerate a two-minute reclamation notice.<br>Allowed: `true`, `false` | `String` | `true` |
| `ImageUri` | Full image URI including tag or digest, e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/app/api:abc1234. Prefer a digest or a commit-SHA tag; ":latest" makes a deploy unreproducible. | `String` | **required** |
| `ContainerPort` | Port the container listens on. Injected as the PORT variable. | `Number` | `8080` |
| `Cpu` | Fargate CPU units (1024 = 1 vCPU). Memory must be a legal pairing for the chosen CPU; the console rejects invalid combinations at deploy time.<br>Allowed: `256`, `512`, `1024`, `2048`, `4096`, `8192`, `16384` | `String` | `512` |
| `Memory` | Memory in MiB. Legal ranges per CPU size: 256 -> 512-2048; 512 -> 1024-4096; 1024 -> 2048-8192; 2048 -> 4096-16384; 4096 -> 8192-30720. | `String` | `1024` |
| `Command` | Override the image's CMD, as comma-separated arguments. Leave empty to use the image default. | `CommaDelimitedList` | `""` |
| `StopTimeoutSeconds` | Grace period between SIGTERM and SIGKILL. Must exceed your longest in-flight request, or a deploy cuts responses off mid-flight. | `Number` | `30` |
| `EnvVar1Name` | Name of an additional environment variable. Leave empty to skip. | `String` | `""` |
| `EnvVar1Value` | Value for EnvVar1Name. Never put a credential here - use the secret slots. | `String` | `""` |
| `EnvVar2Name` | Name of an additional environment variable. Leave empty to skip. | `String` | `""` |
| `EnvVar2Value` | Value for EnvVar2Name. | `String` | `""` |
| `EnvVar3Name` | Name of an additional environment variable. Leave empty to skip. | `String` | `""` |
| `EnvVar3Value` | Value for EnvVar3Name. | `String` | `""` |
| `EnvVar4Name` | Name of an additional environment variable. Leave empty to skip. | `String` | `""` |
| `EnvVar4Value` | Value for EnvVar4Name. | `String` | `""` |
| `Secret1Name` | Environment variable name to inject a secret into. The value never appears in the task definition - ECS resolves it at task start, and it is not visible in describe-task-definition. | `String` | `""` |
| `Secret1Arn` | Secrets Manager secret ARN or SSM Parameter ARN supplying Secret1Name. Pass the plain ARN; the JSON key goes in Secret1JsonKey. The execution role is granted read access to exactly this ARN. | `String` | `""` |
| `Secret1JsonKey` | Key to extract when the secret holds JSON, e.g. "password" for a secret shaped {"username":...,"password":...}. Leave empty to inject the whole value. | `String` | `""` |
| `Secret2Name` | Environment variable name for a second injected secret. | `String` | `""` |
| `Secret2Arn` | Secrets Manager or SSM ARN supplying Secret2Name. | `String` | `""` |
| `Secret2JsonKey` | Key to extract when the second secret holds JSON. | `String` | `""` |
| `ListenerArn` | ALB listener to attach to, from containers/alb's ListenerArn output. Leave empty for a service with no inbound traffic - a queue consumer or scheduled worker - which skips the target group, rule, and health checks entirely. | `String` | `""` |
| `LoadBalancerFullName` | The load balancer's full name (app/<name>/<id>), from containers/alb. Required for request-count autoscaling; leave empty to scale on CPU and memory only. | `String` | `""` |
| `AlbSecurityGroupId` | Security group of the load balancer. The task security group admits traffic from this group only, so tasks are unreachable except through the ALB. | `String` | `""` |
| `ListenerRulePriority` | Priority of this service's listener rule. Must be unique per listener - two services sharing a priority is a deploy failure, so allocate them deliberately (100, 200, 300...). | `Number` | `100` |
| `HostHeader` | Host header this service answers for, e.g. api.example.com. Leave empty to match any host and route on path alone. | `String` | `""` |
| `PathPattern` | Path pattern this service answers for. | `String` | `/*` |
| `ProtocolVersion` | Backend protocol. HTTP1 for a normal REST or GraphQL service, HTTP2 for h2c, GRPC for a gRPC service - which also switches health checking to gRPC status codes.<br>Allowed: `HTTP1`, `HTTP2`, `GRPC` | `String` | `HTTP1` |
| `DeregistrationDelaySeconds` | How long the ALB waits for in-flight requests before removing a target. The 300s default makes every deploy five minutes longer than it needs to be; 30s is right for a normal API. | `Number` | `30` |
| `HealthCheckPath` | Health check path. For GRPC this is a fully qualified method, e.g. /grpc.health.v1.Health/Check. | `String` | `/healthz` |
| `HealthCheckMatcher` | Success codes for HTTP health checks. Ignored for GRPC, which matches gRPC status 0. | `String` | `200` |
| `HealthCheckIntervalSeconds` | Seconds between health checks. | `Number` | `15` |
| `HealthyThresholdCount` | Consecutive successes before a target receives traffic. | `Number` | `2` |
| `UnhealthyThresholdCount` | Consecutive failures before a target is removed. | `Number` | `3` |
| `HealthCheckGracePeriodSeconds` | How long after a task starts before ECS trusts the load balancer's health verdict. Set it above your worst-case cold start - a JVM or a model load can take minutes, and too short a grace period produces an infinite kill-and-restart loop that looks like a crash. | `Number` | `60` |
| `DesiredCount` | Task count at deploy. Autoscaling takes over afterwards, so this is only the starting point. | `Number` | `2` |
| `MinCapacity` | Floor for autoscaling. Two is the smallest number that survives a task replacement or an AZ event without dropping to zero capacity. | `Number` | `2` |
| `MaxCapacity` | Ceiling for autoscaling. This is your cost cap and your blast-radius limit under a traffic spike or a retry storm. | `Number` | `10` |
| `TargetCpuUtilization` | Average CPU percentage the scaler aims to hold. Lower reacts sooner and costs more; above about 80 there is no headroom left to absorb a spike while new tasks start. | `Number` | `65` |
| `TargetMemoryUtilization` | Average memory percentage to hold. Set to 0 to disable memory scaling, which is usually right for a runtime with a garbage collector - the JVM and Go both hold memory at a high-water mark that scaling out never reduces. | `Number` | `0` |
| `TargetRequestsPerTask` | Requests per task per minute to hold. This is the best signal for a latency-sensitive HTTP service, because it reacts to load rather than to the symptom of load. Requires ListenerArn and LoadBalancerFullName; set to 0 to disable. | `Number` | `0` |
| `ScaleOutCooldownSeconds` | Seconds to wait after scaling out before scaling out again. | `Number` | `60` |
| `ScaleInCooldownSeconds` | Seconds to wait after scaling in before scaling in again. Deliberately longer than the scale-out cooldown: scaling out too eagerly costs money, scaling in too eagerly costs availability. | `Number` | `300` |
| `LogRetentionDays` | Retention for the container log group.<br>Allowed: `1`, `3`, `5`, `7`, `14`, `30`, `60`, `90`, `120`, `150`, `180`, `365`, `400`, `545`, `731`, `1827`, `3653` | `Number` | `30` |
| `EnableExecuteCommand` | Allow ECS Exec into running tasks. Sessions are recorded when the cluster has exec logging on.<br>Allowed: `true`, `false` | `String` | `true` |
| `EfsFileSystemId` | EFS file system to mount into the container (from data/efs-filesystem). Leave empty for no persistent volume — Fargate ephemeral storage vanishes with the task. | `String` | `""` |
| `EfsAccessPointId` | EFS access point to mount through. When set, the mount authorizes via IAM and the task role is granted client access scoped to this access point — the recommended posture. Requires EfsFileSystemId. | `String` | `""` |
| `EfsMountPath` | Path inside the container where the EFS volume mounts. | `String` | `/data` |
| `TaskRoleManagedPolicyArn` | Managed policy granting the application the AWS access it needs - its tables, buckets, queues. Leave empty for a service that calls no AWS APIs. | `String` | `""` |

### Outputs

| Output | Description | Exported as |
|--------|-------------|-------------|
| `ServiceName` | ECS service name. | — |
| `ServiceArn` | ECS service ARN. | — |
| `TaskDefinitionArn` | ARN of the task definition revision this stack deployed. | — |
| `TaskRoleArn` | Task role ARN - the identity the application runs as. Grant access to tables, buckets and queues here. | — |
| `ExecutionRoleArn` | Execution role ARN, used by the ECS agent to pull images and fetch secrets. | — |
| `TaskSecurityGroupId` | Security group the tasks run with. Databases and caches should admit this group rather than a CIDR. | — |
| `LogGroupName` | Log group the container writes to. | — |
| `TargetGroupArn` | Target group ARN, when attached to a load balancer. | — |
| `TargetGroupFullName` | Target group full name, for autoscaling resource labels and alarms. | — |

### Resources

| Logical ID | Type | Created when |
|------------|------|--------------|
| `LogGroup` | `AWS::Logs::LogGroup` | always |
| `ExecutionRole` | `AWS::IAM::Role` | always |
| `TaskRole` | `AWS::IAM::Role` | always |
| `TaskSecurityGroup` | `AWS::EC2::SecurityGroup` | always |
| `TaskDefinition` | `AWS::ECS::TaskDefinition` | always |
| `TargetGroup` | `AWS::ElasticLoadBalancingV2::TargetGroup` | `AttachedToLoadBalancer` |
| `ListenerRule` | `AWS::ElasticLoadBalancingV2::ListenerRule` | `AttachedToLoadBalancer` |
| `Service` | `AWS::ECS::Service` | always |
| `ScalableTarget` | `AWS::ApplicationAutoScaling::ScalableTarget` | always |
| `CpuScalingPolicy` | `AWS::ApplicationAutoScaling::ScalingPolicy` | always |
| `MemoryScalingPolicy` | `AWS::ApplicationAutoScaling::ScalingPolicy` | `ScalesOnMemory` |
| `RequestScalingPolicy` | `AWS::ApplicationAutoScaling::ScalingPolicy` | `ScalesOnRequests` |
<!-- END_CFN_DOCS -->
