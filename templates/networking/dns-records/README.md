# `networking/dns-records`

A Route 53 record pointing a hostname at an AWS resource — as an alias where
possible.

## Usage

```bash
./bin/cfn deploy networking/dns-records --env dev \
  --param RecordName=api.example.com \
  --param AliasTargetDnsName=<alb-dns-name> \
  --param AliasTargetHostedZoneId=<alb-canonical-zone-id>
```

Both alias values come from `containers/alb`'s outputs
(`LoadBalancerDnsName` and `LoadBalancerHostedZoneId`).

## Prefer an alias

An alias record is free to resolve, works **at a zone apex** where a CNAME
cannot, and follows the target when its address changes. Use one for anything
AWS-hosted: ALB, NLB, CloudFront, API Gateway, S3 website.

`AliasTargetHostedZoneId` is the **target's** canonical zone ID, not the zone the
record lives in. This trips people up constantly, because both parameters are
zone IDs and only one of them is yours. Every aliasable AWS resource exposes its
own: for an ALB it is `CanonicalHostedZoneID`; for CloudFront it is always
`Z2FDTNDATAQYW2`.

Using the wrong one produces a record that resolves to nothing, with no error at
deploy time.

## `RecordName` must be fully qualified

Route 53 appends the zone name to a name that is not fully qualified, which is
how you end up with `api.example.com.example.com`. The `AllowedPattern` here
requires at least one dot and a TLD, which catches the common case of passing a
bare label.

## TTL and cutovers

`TtlSeconds` applies to plain records only — an alias record inherits its
target's TTL, and CloudFormation rejects a `TTL` on one.

If you are planning a cutover, **lower the TTL days in advance**. Resolvers cache
for the *old* TTL, so dropping it to 60 on the morning of the migration does
nothing for anyone who already resolved the name.

## Health checks

`EnableHealthCheck` creates an HTTPS health check against the record. On a single
record it observes without changing anything — it is only useful as part of a
failover or weighted routing setup.

If you enable it, note that Route 53 health checkers come from published AWS
ranges **worldwide**. A security group that only admits your own CIDRs marks the
endpoint unhealthy from every checker at once, which looks exactly like an
outage.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
