# `data/athena-workgroup`

The query half of a data lake, with the two guardrails that stop Athena being a
surprise on the bill.

## Usage

```bash
./bin/cfn deploy data/athena-workgroup --env dev \
  --param ResultsBucketArn=<lake-bucket-arn>

aws athena start-query-execution --work-group example-app-dev-analytics \
  --query-string "SELECT count(*) FROM raw.clickstream WHERE year='2026'"
```

**Queries run outside the workgroup get none of these controls.** Pass
`--work-group` on the CLI, and set it in the JDBC/ODBC driver properties.

## `BytesScannedCutoffPerQuery` — 10 GB by default

Athena bills **per terabyte scanned**. One `SELECT *` over an unpartitioned lake
is a genuine invoice, and it is the single most common way an analytics
environment surprises someone. This cancels any query that exceeds the cutoff.

10 GB is roughly $0.05. Raise it deliberately once you know a query needs more —
the point is that exceeding it is a decision, not an accident.

The cheapest query is one that scans less: partition your tables (see
[`data/firehose-to-s3`](../firehose-to-s3) for the Hive layout) and convert to
Parquet.

## `EnforceWorkGroupConfiguration: true`

Without it, a client can override the result location and the scan cutoff from
its own settings, which makes both of them suggestions rather than controls. With
it, the workgroup's configuration wins.

## Result objects are a copy of your data

Every query writes its full result set to `ResultsBucketArn`, and that object
carries **none of the source table's access controls**. Two consequences:

- Put a short lifecycle expiry on the results prefix
  ([`data/s3-bucket`](../s3-bucket)'s `ExpireObjectsAfterDays`). Results
  accumulate forever otherwise.
- If queries return restricted data, use `ResultsKmsKeyArn` so the copies are
  protected by a key you control.

## `RecursiveDeleteOption`

Set to `true`, because deleting a workgroup that contains saved queries otherwise
fails — turning a routine stack teardown into manual cleanup in the console.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
