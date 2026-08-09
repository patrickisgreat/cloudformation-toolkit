# `messaging/sqs-queue`

An SQS queue and its dead-letter queue, wired together. You never get one without
the other from this template.

## Usage

```bash
./bin/cfn deploy messaging/sqs-queue --env dev --param QueueSuffix=orders
```

## The DLQ is not optional

A queue with no dead-letter queue retries a poison message until retention
expires — for four days by default — and then silently drops it. There is no
parameter here to turn the DLQ off, because a queue without one loses data by
design.

**Alarm on the DLQ's `ApproximateNumberOfMessagesVisible`.** A non-zero DLQ is
the single most useful signal a queue-backed system produces:
`observability/service-alarms` does this.

## The three settings that cause duplicate work

**`VisibilityTimeoutSeconds` (30).** Must exceed your worst-case processing time.
If processing outlives the timeout, a second consumer receives the same message
while the first is still working — the symptom is duplicate side effects that
look like a producer bug. For a Lambda consumer, AWS recommends at least 6× the
function timeout.

**`MaxReceiveCount` (5).** Too high and a poison message is retried for hours,
blocking its FIFO message group. Too low and a transient downstream failure sends
good messages to the DLQ.

**`MessageRetentionSeconds` (4 days).** The AWS default, kept here, but be aware:
an outage that spans a long weekend silently drops messages. Raise it to the
14-day maximum for anything you cannot afford to lose. The DLQ already uses 14
days, since it is what you inspect *after* the incident.

## Long polling

`ReceiveMessageWaitTimeSeconds` defaults to 20, the maximum. Short polling bills a
request per empty receive, so an idle consumer polling at 0 costs real money to
receive nothing, and adds latency by returning empty when messages exist on
another host.

## FIFO

`FifoQueue: true` gives strict ordering within a message group and exactly-once
processing, at lower throughput, and requires every producer to send a
`MessageGroupId`. The `.fifo` name suffix is applied automatically to both queues
— a FIFO queue with a standard DLQ is rejected with an error that does not
mention the suffix.

Most consumers should be idempotent regardless, in which case a standard queue is
simpler and faster.

## Encryption

SQS-managed SSE by default: free, no key policy. Supply `KmsKeyArn` for
cross-account consumers.

Note the properties are mutually exclusive in a way that surprises people:
`SqsManagedSseEnabled` and `KmsMasterKeyId` conflict, and setting the former to
`false` alongside a key **still errors**, because the check fires on the argument
being present at all. This template emits `AWS::NoValue` rather than `false`.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
