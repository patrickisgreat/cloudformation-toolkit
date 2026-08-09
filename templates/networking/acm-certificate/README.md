# `networking/acm-certificate`

A DNS-validated ACM certificate. CloudFormation writes the validation record into
your hosted zone and waits for it to resolve.

## Usage

```bash
./bin/cfn deploy networking/acm-certificate --env dev \
  --param DomainName=api.example.com --param HostedZoneId=Z0123456789ABC
```

## DNS validation, not email

`ValidationMethod` is hardcoded to `DNS`. Email validation requires a human to
click a link every 13 months, and when nobody does, the certificate **silently
expires** — the first symptom is a browser warning in production. A DNS-validated
certificate renews itself indefinitely, as long as the validation record stays in
the zone.

Do not delete the `_<hash>.<domain>` CNAME after issuance. It is what makes
renewal automatic.

## The stack will hang if the zone is wrong

`CREATE_IN_PROGRESS` on this stack means "waiting for the validation record to
resolve". If `HostedZoneId` is not authoritative for `DomainName` — a delegation
that was never completed, or the wrong zone in a multi-account setup — the record
is written and never resolves, and the stack sits there until it times out.

If a deploy is stuck here for more than a few minutes, check that the domain's
nameservers actually point at that zone.

## Region matters, and differently per service

| Consumer | Certificate must be in |
|----------|------------------------|
| CloudFront | **`us-east-1`**, regardless of where it serves from |
| Application Load Balancer | the load balancer's own region |
| API Gateway (regional) | the API's own region |

A certificate in the wrong region does not fail at deploy — it fails when the
consumer references it, with an error that reads like the ARN is invalid.

## Wildcards match one label

`*.example.com` covers `api.example.com` but **not** `a.b.example.com`. If you
need both, add the second level explicitly as `AdditionalDomainName`.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
