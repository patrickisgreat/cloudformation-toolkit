# `messaging/sns-topic`

An SNS topic that is encrypted, optionally FIFO, and can fan out to an SQS queue
with a message filter.

## Usage

```bash
./bin/cfn deploy messaging/sns-topic --env dev \
  --param TopicSuffix=alarms --param EmailEndpoint=oncall@example.com
```

## Email subscriptions lie about being ready

An `email` subscription sits in **pending confirmation** until the recipient
clicks the link in the confirmation mail. CloudFormation reports the stack as
`CREATE_COMPLETE` either way.

The practical consequence: an alarm topic can look completely healthy and deliver
nothing at all. After deploying an alarm topic, confirm the subscription and then
verify with:

```bash
aws sns list-subscriptions-by-topic --topic-arn <arn> \
  --query 'Subscriptions[?SubscriptionArn==`PendingConfirmation`]'
```

Anything returned there is a notification path that does not work.

## Raw message delivery is on for SQS

Without it, the consumer receives the SNS envelope with your payload embedded as
a JSON *string* inside it, so every consumer has to parse twice. This template
sets `RawMessageDelivery: true` so the queue receives what the publisher sent.

The SQS subscription is a separate `AWS::SNS::Subscription` resource rather than
an inline entry on the topic, because inline subscriptions support neither
`FilterPolicy` nor `RawMessageDelivery`.

## Filter at the topic, not in the consumer

`FilterPolicy` takes a JSON message-attribute filter:

```json
{"eventType": ["order.created", "order.cancelled"]}
```

Messages that do not match are never delivered. Filtering here is cheaper than
delivering everything and discarding in the consumer, and it means adding a
consumer for a new event type does not require touching the existing ones.

## Scoped cross-service publishing

`AllowPublishFromService` grants a service principal (`s3.amazonaws.com`,
`cloudwatch.amazonaws.com`) permission to publish. It requires
`AllowPublishFromSourceArn`, and that is not a convenience — a service grant
without an `aws:SourceArn` condition lets **any** bucket or alarm, in any
account, publish to your topic.

## FIFO topics are more restrictive than they look

A FIFO topic can only be subscribed by FIFO SQS queues. No email, no HTTPS, no
Lambda, no mobile push. Choose it only when a FIFO queue is the only consumer you
will ever have.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
