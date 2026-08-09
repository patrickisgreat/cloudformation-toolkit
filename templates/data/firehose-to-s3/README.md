# `data/firehose-to-s3`

The ingestion half of a data lake: Firehose reads a Kinesis stream (or accepts
direct writes) and lands compressed, Hive-partitioned objects in S3.

## Usage

```bash
./bin/cfn deploy data/firehose-to-s3 --env dev \
  --param SourceStreamArn=<stream-arn> --param DestinationBucketArn=<bucket-arn>
```

## The partition layout is the point

```
raw/clickstream/year=2026/month=08/day=09/hour=14/
```

Firehose's own default layout is bare numbers (`2026/08/09/14/`). Glue crawlers
and Athena's partition projection both expect **Hive-style `key=value`** segments
and will not recognise the default without a custom classifier — which is a
surprisingly expensive discovery to make after a month of data has landed.

`TablePrefix` should be named after the table it becomes:
`data/glue-etl` points a crawler at exactly this location.

## Errors land somewhere, and not in your table

`ErrorOutputPrefix` writes failed records under `errors/` — **outside** the table
prefix. An error object inside the partition tree is a malformed row in every
query against that table, which usually surfaces as a confusing Athena parse
error rather than as "delivery is failing".

## Buffering: file size versus freshness

| | Effect |
|---|---|
| `BufferSizeMb` (64) | Bigger buffers → bigger files. **Large files are what make Athena fast**: a lake of thousands of tiny objects spends most of its query time on S3 list and open calls, not on scanning. |
| `BufferIntervalSeconds` (300) | The freshness floor — data is queryable roughly this long after it was produced. |

Whichever limit is reached first triggers the flush. If your objects are coming
out small, it is the interval firing, not the size.

## Kinesis source or Direct PUT

With `SourceStreamArn` set, producers write to Kinesis and Firehose reads from
it. Leave it empty and producers call `PutRecord` on Firehose directly — simpler,
one less resource, and **no replay**: a record Firehose fails to deliver after
its retries is gone, whereas a Kinesis source can be re-read within its retention
window. Use Direct PUT for logs you can regenerate, Kinesis for events you
cannot.

## Encryption

`NoEncryptionConfig: NoEncryption` looks alarming and is correct: it means
Firehose adds no *second* layer, and the destination bucket's own default
encryption applies to every object. Setting a KMS key here as well would
double-encrypt and require the delivery role to hold key permissions it does not
otherwise need.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
