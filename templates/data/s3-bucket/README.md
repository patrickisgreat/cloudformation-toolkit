# `data/s3-bucket`

An S3 bucket that is private, encrypted, TLS-only, versioned, and does not grow
without bound.

## Usage

```bash
./bin/cfn deploy data/s3-bucket --env dev --param BucketSuffix=uploads
```

## The name includes your account and region

`<NamePrefix>-<Environment>-<BucketSuffix>-<account>-<region>`

Bucket names are globally unique **across every AWS customer**, not per account.
`example-app-dev-data` was taken years ago. Appending the account and region
makes the name deterministic and available, which matters because you cannot
rename a bucket — only create a new one and copy.

## Four things are not negotiable

These have no parameters, because there is no configuration of them that is
correct:

1. **All four public access blocks on.** The account-level setting is not
   guaranteed, so every bucket sets its own.
2. **ACLs disabled** (`BucketOwnerEnforced`). Essentially every "public S3
   bucket" incident of the last decade went through an ACL, not a policy.
3. **A TLS-only bucket policy.** Encryption at rest does nothing for a request
   made over plain HTTP; this statement closes that gap.
4. **`DeletionPolicy: Retain`.** A stack rollback must not be able to delete
   your data.

## Lifecycle rules are cost control

| Rule | Default | Why |
|------|---------|-----|
| Abort incomplete multipart uploads | 7 days | Orphaned parts are billed as storage and **do not appear in the console object listing**. This is the classic mystery line item. |
| Expire noncurrent versions | 30 days | Without it, versioning is unbounded storage growth nobody notices until the bill. |
| Expire current objects | off | Right for scratch space, wrong for a data lake — so it is opt-in. |

Storage class transitions (`TransitionToInfrequentAccessDays`,
`TransitionToGlacierDays`) are off by default. STANDARD_IA has a **30-day minimum
billing duration** and a per-GB retrieval charge: moving objects that turn out to
be read regularly costs *more* than leaving them in Standard. Only transition
data you are confident is cold.

## Encryption

Default is SSE-S3 (AES256) — free, and satisfies every encryption-at-rest
control. Supply `KmsKeyArn` when you need cross-account access, key-level audit,
or independent revocation.

When you do, `BucketKeyEnabled` is switched on automatically. It uses one data
key per bucket rather than one per object, which on a write-heavy bucket is the
difference between a negligible KMS bill and a startling one.

## Events

`EnableEventBridge` publishes object-created and object-removed events to the
default event bus. Prefer it over the bucket's direct Lambda/SQS notification
config: the bucket stays unaware of its consumers, so adding a second ETL trigger
later does not mean modifying the bucket.

## Log delivery modes

`LogDeliveryMode` adds the bucket policy statement an AWS service needs to write
here:

- `alb` — grants `logdelivery.elasticloadbalancing.amazonaws.com`, for
  `containers/alb`'s `AccessLogsBucket`.
- `waf-firehose` — grants `delivery.logs.amazonaws.com`, used by WAF logging and
  VPC flow log delivery.

Both are scoped with `aws:SourceAccount` so another account cannot name your
bucket as its log destination.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
