# `serverless/http-api`

An API Gateway HTTP API in front of a Lambda function: throttled, access-logged,
optionally authenticated with JWT, optionally on your own domain.

HTTP APIs are roughly 70% cheaper than REST APIs and lower latency. Choose a REST
API only when you specifically need API keys and usage plans, request/response
transformation, WAF attachment, or a private endpoint.

## Usage

```bash
./bin/cfn deploy serverless/http-api --env dev \
  --param LambdaFunctionArn=arn:aws:lambda:us-east-1:123:function:my-handler
```

## One catch-all route

The API declares a single `$default` route, so **routing happens inside your
function**. This is what FastAPI, Express, Gin, Axum, and every other framework
with a Lambda adapter expect — you keep one router rather than mirroring your
routes into infrastructure where they will drift.

## The permission everyone forgets

`AWS::Lambda::Permission` is what allows API Gateway to invoke the function.
Without it every request returns **500 "Internal Server Error" with nothing in
the function's logs**, because the function was never invoked. It is the single
most common HTTP API misconfiguration, and it is unconditional here.

## Throttling is a cost control

`ThrottlingRateLimit` (100 rps) and `ThrottlingBurstLimit` (200) apply to the
whole stage. An HTTP API with no throttle forwards a scraper's traffic straight
to your function and bills you per invocation. This turns a runaway client into a
429 instead of an invoice.

## JWT authorizer

`JwtIssuer` empty means **every route is public**. When you set it, `JwtAudience`
is effectively mandatory: an authorizer that validates the issuer but not the
audience accepts any token that issuer ever minted, for any application
registered with it.

## `IntegrationTimeoutMillis`

Must be at least the function's own timeout. If the gateway gives up first, the
client gets a 504 while the function keeps running — and keeps billing. Note the
API Gateway ceiling is 30 seconds; a function that legitimately runs longer needs
an async pattern, not a bigger number.

## CORS

Empty `CorsAllowOrigin` means no CORS configuration, which is correct for a
server-to-server API. When set, `AllowCredentials` is on — which is why the
parameter takes a concrete origin: browsers reject credentialed requests against
a `*` origin, so the wildcard silently breaks the case you enabled CORS for.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
