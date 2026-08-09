# `observability/service-alarms`

Six alarms that between them tell you the three things you need at 3am: is it
broken, is it slow, is it full.

## Usage

```bash
./bin/cfn deploy observability/service-alarms --env dev \
  --param AlarmTopicArn=<topic> \
  --param LoadBalancerFullName=<lb-full-name> \
  --param TargetGroupFullName=<tg-full-name>
```

Every group is optional: supply only the load balancer names and you get the
three request alarms; add the ECS names for saturation; add a DLQ name for the
queue alarm.

## What each one is for

| Alarm | Says |
|-------|------|
| `5xx` | Targets are returning server errors. Check the log group; if it started at a deploy, roll back. |
| `unhealthy-targets` | Targets are failing health checks — a failed deploy, a moved health path, or a grace period shorter than startup. |
| `latency` (p99) | Slow. Either saturated or waiting on a dependency. |
| `cpu` / `memory` | Full. With autoscaling configured, it means the ceiling has been reached. |
| `dlq` | Messages are being rejected. **Inspect before redriving** — whatever rejected them will reject them again. |

## p99, not average

`LatencyAlarm` uses `ExtendedStatistic: p99`. An average response time hides the
tail, and the tail is what users experience as "the site is slow". A service can
sit at a 120ms average with a 9-second p99 and look completely healthy on an
average-based alarm.

## Set CPU above your autoscaling target

`CpuThresholdPercent` defaults to 85 while `containers/fargate-service` targets
65. That gap is deliberate: alarming at the level the scaler is aiming to hold
pages you **every time autoscaling works correctly**, which is the fastest way to
teach a team to ignore an alarm.

## `TreatMissingData` is not the same for every alarm

This is the setting that decides whether an alarm is useful or is a 3am pager for
an idle dev environment:

- **5xx, latency, CPU, memory → `notBreaching`.** A service with no traffic emits
  no datapoints. Treating that as a breach pages you nightly for an environment
  nobody is using.
- **`unhealthy-targets` → `breaching`.** Here, no data means the target group is
  not reporting at all, which is itself the problem.

## Alarms only work if the topic does

`AlarmTopicArn` must have a **confirmed** subscription. An SNS email subscription
sits in "pending confirmation" until someone clicks the link, and CloudFormation
reports the stack as complete either way — so a full alarm set can be silent
while every dashboard looks green. See
[`messaging/sns-topic`](../../messaging/sns-topic) for the check.

`OKActions` are wired as well as `AlarmActions`, so recovery is announced too.
An alarm you are never told cleared is one you keep investigating.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
