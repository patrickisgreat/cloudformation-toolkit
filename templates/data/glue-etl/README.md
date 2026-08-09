# `data/glue-etl`

The catalog and transform half of a data lake: a Glue database, a crawler that
discovers schema and partitions, and an optional Spark ETL job.

Pair it with [`data/firehose-to-s3`](../firehose-to-s3) for ingestion and
[`data/athena-workgroup`](../athena-workgroup) for query.

## Usage

```bash
./bin/cfn deploy data/glue-etl --env dev \
  --param SourceBucketArn=<lake-bucket-arn> --param SourcePrefix=raw/clickstream
```

## Point the crawler at the table root

`SourcePrefix` must be the directory *above* the partition folders:

```
raw/clickstream/          <- point here
  year=2026/month=08/...
```

A crawler pointed inside the partitions registers **each partition as a separate
table**, which produces a catalog with hundreds of one-day tables and no obvious
way back.

## Schema changes are logged, not applied

`UpdateBehavior: LOG` and `DeleteBehavior: LOG` are deliberate. The tempting
alternative, `UPDATE_IN_DATABASE`, silently rewrites the table definition when a
column's inferred type changes — and every query that relied on the old type
starts failing, or worse, silently coercing. `DEPRECATE_IN_DATABASE` on delete is
worse still: a lifecycle rule expiring old partitions looks to the crawler like a
table that should disappear.

You will see schema drift in the crawler's log and decide what to do about it.

## `RecrawlBehavior: CRAWL_NEW_FOLDERS_ONLY`

A full recrawl lists every object in the lake, which is slow and billed per
object. New-folders-only is what makes a daily crawl on a large lake affordable.
If you change the shape of existing data, run a full crawl once by hand.

## Job bookmarks

`--job-bookmark-option: job-bookmark-enable` makes a rerun process only data that
arrived since the last successful run. Without it, an hourly job reprocesses the
entire lake every hour — the single most common Glue cost surprise.

This is also why `MaxConcurrentRuns` defaults to 1: two concurrent runs with
bookmarks enabled will process overlapping data.

## `JobTimeoutMinutes`

Defaults to 60. Glue's own default is **2880 minutes — two days** — which on a
hung job is an expensive way to find out something is wrong.

## Cost

Glue bills per DPU-hour with a one-minute minimum. `G.1X` (4 vCPU / 16 GB) at 2
workers is the right starting point; scale up only after seeing the job actually
spill.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
