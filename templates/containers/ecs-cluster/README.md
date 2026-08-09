# `containers/ecs-cluster`

An ECS cluster with both Fargate capacity providers registered, Container
Insights on, and ECS Exec sessions written to an audit log group.

An ECS cluster is a cheap, almost-empty object — it costs nothing on its own. One
cluster per environment is the normal granularity; you do not need one per
service.

## Usage

```bash
./bin/cfn deploy containers/ecs-cluster --env dev
```

## The capacity strategy is the interesting part

Three numbers decide how much you pay and how much interruption you accept:

| Parameter | Meaning |
|-----------|---------|
| `OnDemandBaseCount` | Tasks placed on on-demand **before weights apply at all** |
| `OnDemandWeight` | Share of the remainder on on-demand |
| `SpotWeight` | Share of the remainder on Spot |

`OnDemandBaseCount` is your interruption floor, and it is the parameter people
get wrong. With `Base: 1, OnDemandWeight: 1, SpotWeight: 3`, a service running 9
tasks places 1 on-demand, then splits the remaining 8 one-to-three — 2 more
on-demand and 6 Spot. One task is guaranteed to survive a Spot reclamation event.

**Fargate Spot is ~70% cheaper and can be reclaimed with a two-minute warning.**
That is a good trade for a stateless HTTP service behind a load balancer, which
drains and reschedules. It is a bad trade for:

- a queue consumer partway through a long batch,
- anything holding a long-lived connection (WebSocket, gRPC stream, SSE),
- a job with no checkpointing.

`SpotWeight` defaults to `0` — Spot is opt-in, because the failure it introduces
is invisible until the day capacity gets tight.

Both capacity providers are registered even when `SpotWeight` is 0, so moving a
service onto Spot later is a parameter change rather than a cluster rebuild.

## ECS Exec is a shell in production

`EnableExecuteCommandLogging` defaults to on, writing every session to
`/<env>/<prefix>/ecs-exec` with a 90-day retention and `DeletionPolicy: Retain`.
ECS Exec gives an operator an interactive shell inside a running production
container; without this log group there is no record of what was typed.

Note that the cluster only makes logging *possible*. Each service must also set
`EnableExecuteCommand: true`, and its task role needs the `ssmmessages`
permissions — `containers/fargate-service` wires both.

## Service Connect vs a load balancer

`CreateServiceConnectNamespace` creates a Cloud Map namespace so services address
each other as `http://orders/` with client-side retries, per-call metrics, and no
load balancer in the path. It requires `VpcId`.

Off by default: for a single service there is nothing to connect to, and the
namespace becomes an unused resource that blocks VPC deletion.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
