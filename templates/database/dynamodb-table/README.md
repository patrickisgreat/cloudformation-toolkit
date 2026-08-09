# `database/dynamodb-table`

A DynamoDB table with point-in-time recovery on, encryption declared, and the
optional pieces — sort key, GSI, TTL, streams — behind parameters.

## Usage

```bash
./bin/cfn deploy database/dynamodb-table --env dev --param TableSuffix=orders
```

## Three things you cannot change later

DynamoDB is unusually unforgiving about create-time decisions. Each of these
means "create a new table and migrate" if you get it wrong:

1. **The key schema.** `PartitionKeyName` and `SortKeyName` are the only access
   pattern the base table supports. A sort key cannot be added afterwards, and it
   is what makes range queries, prefix queries, and single-table designs
   possible. Include one unless you are certain the table is pure key-value.
2. **Point-in-time recovery's window.** PITR gives you restore-to-any-second for
   the last 35 days, and the window **starts when you enable it**. Turning it on
   after a bad migration recovers nothing. It costs about 20% of table storage;
   the default here is on.
3. **Stream history.** Enabling a stream later starts it empty. Everything that
   changed in between is not in it.

## `BillingMode`

`PAY_PER_REQUEST` is the default: no capacity to manage, no throttling, bills per
read and write. `PROVISIONED` is cheaper only at high, steady, well-understood
traffic — and throttles when your prediction is wrong, which surfaces as latency
rather than as an error.

Start on-demand. Move to provisioned when you have a month of CloudWatch data
saying it would pay.

## The GSI is a second table

A global secondary index stores its own copy of the projected attributes and
consumes its own write capacity on **every write to the base table**.

`IndexProjection` defaults to `KEYS_ONLY` for that reason: project the keys, then
`GetItem` the base table for the rest. `ALL` roughly doubles storage and write
cost, and is worth it only when the follow-up read is on a hot path.

Index attributes are declared as type `S` here. Non-string index keys need the
template extended — a deliberate simplification, since string keys cover the
overwhelming majority of GSIs.

## TTL is free deletion

`TtlAttributeName` names an attribute holding a Unix epoch-second expiry.
DynamoDB deletes expired items within roughly 48 hours at no cost, and the
deletion appears in the change stream so downstream consumers see it. It is the
cheapest way to bound the size of a sessions or events table.

## IAM note

`TableArn` covers the table. Granting query access to an index also requires
`<TableArn>/index/*` — a policy with only the table ARN produces an
`AccessDeniedException` on `Query` that mentions the index and looks like a
missing index.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
