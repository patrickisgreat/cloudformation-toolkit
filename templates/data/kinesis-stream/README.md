# `data/kinesis-stream`

A Kinesis Data Stream: encrypted, retention-configured, and by default in
on-demand capacity mode so nobody has to predict a shard count.

## Usage

```bash
./bin/cfn deploy data/kinesis-stream --env dev --param StreamSuffix=clickstream
```

Feed it into a lake with [`data/firehose-to-s3`](../firehose-to-s3), or attach a
Lambda event source mapping to process records directly.

## `CapacityMode` is the cost decision

**`ON_DEMAND`** (default) scales automatically and bills per GB written and read.
No shard management, no resharding, no throughput exceptions. For spiky or
unknown load it is both simpler and cheaper.

**`PROVISIONED`** bills per shard-hour and becomes cheaper only above roughly a
sustained 1 MB/s per shard — but you have to predict the shard count, and being
wrong produces `ProvisionedThroughputExceededException` on the producer side.
Most SDKs retry that transparently, so the symptom is not an error: it is a
growing backlog and rising write latency that nobody attributes to sharding.

Each shard takes 1 MB/s or 1000 records/s in, and 2 MB/s out shared across all
standard consumers.

## `RetentionHours` is your recovery window

24 hours (the AWS default) is how long you have to notice and fix a broken
consumer before the unread data is gone. 168 hours (7 days) costs extra and turns
a weekend outage into a replay rather than an incident report. Anything you
cannot reconstruct from a source of truth deserves the longer window.

## Enhanced fan-out

Standard consumers **share** the stream's 2 MB/s per shard read capacity. Two or
three consumers are fine; beyond that they start starving each other and
propagation delay climbs.

`EnhancedFanOutConsumerName` registers a consumer with its own dedicated 2 MB/s
per shard, billed hourly per shard. Add it when you have a consumer whose latency
matters and others competing with it.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
