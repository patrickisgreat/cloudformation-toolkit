# `containers/alb`

An Application Load Balancer that routes nothing until a service asks it to.

## Usage

```bash
./bin/cfn deploy containers/alb --env dev \
  --param VpcId=vpc-abc --param SubnetIds=subnet-a,subnet-b
```

Then wire a service to it — `containers/fargate-service` takes `ListenerArn` and
attaches its own rule:

```yaml
Service:
  Type: AWS::CloudFormation::Stack
  Properties:
    TemplateURL: ../../templates/containers/fargate-service/template.yaml
    Parameters:
      ListenerArn: !GetAtt Alb.Outputs.ListenerArn
      AlbSecurityGroupId: !GetAtt Alb.Outputs.SecurityGroupId
```

## The default action is a 404, on purpose

Both listeners default to a fixed `404`, not a forward. This is the main design
decision in the template.

A load balancer whose default action forwards to some service means **every**
unmatched request lands there: scanner traffic, requests for hostnames you no
longer serve, and requests for a service you deleted last month. Services attach
a `ListenerRule` with a host or path condition, so routing is explicit and
removing a service actually removes its route.

Use the `ListenerArn` output rather than `HttpsListenerArn` or `HttpListenerArn`
— it resolves to whichever listener exists, so a service does not need to know
whether TLS is configured.

## TLS

`CertificateArn` empty means **plain HTTP only**. That is fine for a scratch
environment and wrong for anything that handles a cookie, a token, or a
credential. With a certificate:

- port 443 serves, using `SslPolicy` (default: TLS 1.3 and 1.2 only),
- port 80 issues a `301` preserving host, path, and query.

Get a certificate from `networking/acm-certificate` — DNS-validated, so it
renews without anyone touching it.

## `IdleTimeoutSeconds` is the one that bites

The 60-second default is shorter than a slow endpoint. A streaming LLM response,
a large report, or a slow upload that exceeds it surfaces as a **504 with no
corresponding backend error**, which is a genuinely confusing hour of debugging.
If you serve long responses, raise this and set your server's keep-alive timeout
*higher* than the ALB's — if the backend closes first, the ALB reports a 502.

## Access logs

`AccessLogsBucket` expects a bucket whose policy already allows ELB log
delivery. In regions created after August 2022, that means granting the
`logdelivery.elasticloadbalancing.amazonaws.com` service principal
`s3:PutObject`; older regions require the region's ELB account ID as the
principal. `data/s3-bucket` has an `AccessLogDelivery` bucket-policy mode that
sets this up.

## Egress is not restricted

The security group declares ingress only. CloudFormation removes the default
allow-all egress rule as soon as `SecurityGroupEgress` is present, and the ALB
must reach targets on whatever port they listen on — which this template does not
know. Restriction belongs on the target's security group, and
`containers/fargate-service` scopes its ingress to this group specifically.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
