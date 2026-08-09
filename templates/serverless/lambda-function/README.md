# `serverless/lambda-function`

A Lambda function packaged as a zip or a container image, with an execution role,
a log group whose retention is actually bounded, and the concurrency controls that
protect whatever it calls.

## Usage

```bash
./bin/cfn deploy serverless/lambda-function --env dev \
  --param CodeS3Bucket=my-artifacts --param CodeS3Key=webhook/abc1234.zip
```

## Any language

`PackageType: Zip` with `Runtime: provided.al2023` runs a compiled binary — Rust,
Go, C++, anything with a `bootstrap` entry point. `PackageType: Image` takes an
ECR image and lifts every runtime restriction, which is what you want for a
Python function with heavy native dependencies that will not fit in the 250 MB
unzipped zip limit.

**Put a commit SHA in `CodeS3Key`.** Lambda caches by bucket and key, so
overwriting the same key does not reliably update the running code — a deploy
that appears to succeed and changes nothing.

## `MemorySize` is the CPU dial

Lambda allocates CPU in proportion to memory. A CPU-bound function is frequently
*cheaper* at 1024 MB than at 512, because it finishes more than twice as fast.
Tune it by measuring duration at several sizes, not by guessing at memory
footprint.

`Architecture` defaults to `arm64` — roughly 20% cheaper per GB-second and
usually faster. Switch to `x86_64` only when a dependency has no arm64 build.

## `ReservedConcurrency` is a circuit breaker

Default `-1` (unreserved). Set it whenever the function talks to a database:
Lambda will happily scale to a thousand concurrent executions, and a thousand
connections is how a Lambda takes down the RDS instance it was reading from.

Note `0` does not mean "unlimited" — it disables the function entirely.

## The log group is declared, not inherited

Lambda creates `/aws/lambda/<name>` implicitly on first invocation, with
**infinite retention**, and that group is not owned by your stack. This template
declares it (30-day default, `Retain`) and orders the function after it. Without
that ordering you can end up with an unmanaged group and a stack that fails on
the next update with "log group already exists".

## VPC attachment is opt-in

Leave `SubnetIds` empty unless the function must reach something inside the VPC.
A VPC-attached function reaches AWS APIs only through a NAT gateway or an
interface endpoint, so attaching one "for security" usually just adds cost and a
new failure mode.

When you do attach, the execution role automatically swaps to
`AWSLambdaVPCAccessExecutionRole`. Without those ENI permissions the function
fails to create its network interface and every invocation times out **with no
log output at all** — one of the more confusing failures Lambda produces.

## Failure destinations

`FailureDestinationArn` sends the payload of an asynchronous invocation that
exhausted its retries to an SQS queue or SNS topic. Without one, the event is
gone: a log line is all that remains of it. For anything triggered by S3,
EventBridge, or SNS, this is the difference between a recoverable incident and a
silent one.

## Known limitation: environment variable slots

CloudFormation's `Fn::If` can substitute a *value* in a map but cannot add or
remove a *key*. Unused `EnvVarN` slots therefore appear as empty strings rather
than disappearing. Read configuration from SSM Parameter Store at startup if you
need many variables.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
