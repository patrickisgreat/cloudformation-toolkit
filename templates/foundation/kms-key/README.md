# `foundation/kms-key`

A customer-managed KMS key with rotation on, an alias, and a key policy built
from three optional principals.

## Usage

```bash
./bin/cfn deploy foundation/kms-key --env dev
```

## When you actually need this

Most templates in this library default to an **AWS-managed** key
(`alias/aws/s3`, `alias/aws/sns`, SQS-managed SSE). Those are free, need no
policy, and satisfy every "encrypted at rest" control. Reach for a
customer-managed key when you need one of:

- **Cross-account access** to encrypted data — an AWS-managed key cannot be
  shared.
- **Key-level audit** — CloudTrail shows which principal decrypted what.
- **Independent revocation** — disabling the key makes the data unreadable
  immediately, without touching IAM.
- **A compliance requirement** that names customer-managed keys specifically.

A CMK costs $1/month plus request charges. Do not create one per resource out of
habit; one per data domain (`-data`, `-logs`) is the usual granularity, which is
what `AliasSuffix` is for.

## The key policy

`KeyAdminArn` and `KeyUserArn` are separate on purpose. The value of a CMK comes
from the people who can *read* the data and the people who can *destroy the key*
being different sets. Collapsing them into one principal gives you the cost of a
CMK with the safety of an AWS-managed key.

The account-root statement is not optional and cannot be removed through
parameters. Without it, IAM policies in the account cannot grant access to the
key at all — the key becomes unmanageable and, in practice, permanently orphaned.
That is the single most common way to lose a CMK, so this template does not let
you do it.

`ServicePrincipal` grants an AWS service (`logs.amazonaws.com`,
`s3.amazonaws.com`, `delivery.logs.amazonaws.com`) usage of the key, scoped with
`aws:SourceAccount` so another account cannot name your key and have AWS honour
it. Only one is accepted; if you need several, deploy the key once per domain or
extend the template.

## Deletion is permanent

`DeletionPolicy: Retain` is set, and `PendingWindowInDays` defaults to the
maximum of 30. When a KMS key is deleted, every ciphertext encrypted under it
becomes unreadable — there is no recovery, no support ticket, no snapshot. The
pending window is your only chance to notice.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
