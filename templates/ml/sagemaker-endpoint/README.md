# `ml/sagemaker-endpoint`

A SageMaker inference endpoint — real-time or serverless — with autoscaling on
the metric that actually matters, and a deployment that rolls back when the new
model starts erroring.

For self-hosted open-weight LLMs on your own GPU fleet, see
[`ml/gpu-inference-service`](../gpu-inference-service) instead.

## Usage

```bash
./bin/cfn deploy ml/sagemaker-endpoint --env dev \
  --param InferenceImageUri=<dlc-image> \
  --param HuggingFaceModelId=sentence-transformers/all-MiniLM-L6-v2
```

## `ServingMode`

**`SERVERLESS`** scales to zero and bills per request. The cost is a cold start
of tens of seconds on the first request after idle, and **no GPU support at
all**. Right for embeddings, classifiers, and anything with bursty low volume.

**`REALTIME`** provisions instances billed continuously, responds in
milliseconds, and supports GPU. Right for anything latency-sensitive or
GPU-bound.

`InitialInstanceCount` defaults to 1, which is fine for dev — but understand that
with one instance, every deployment and every instance failure is an outage.

## Scale on invocations, not CPU

`TargetInvocationsPerInstance` uses
`SageMakerVariantInvocationsPerInstance`, not CPU utilisation. This matters more
than it sounds: **GPU inference is frequently memory-bound with CPU near idle**,
so a CPU-based scaling policy simply never fires while the endpoint queues.

`MaxInstanceCount` is the parameter that decides whether a traffic spike on a
`ml.g5.12xlarge` costs tens of dollars or thousands. Set it as a budget.

## Deployments roll back

`DeploymentConfig` shifts traffic to the new fleet, then holds the old one for 10
minutes with `InvocationErrorAlarm` watching. If the new model version errors, it
rolls back automatically.

Without this, a model that loads successfully but answers badly has already
replaced the working one, and recovery means redeploying the previous artifact by
hand.

## Data capture is how you evaluate later

`DataCaptureS3Uri` records a sample of inputs and outputs to S3. This is what
makes drift monitoring, offline evaluation, and "why did it answer that in
March?" possible. Without it those requests are simply gone.

It is off by default because captured inference data is a copy of whatever your
users sent — treat the destination bucket accordingly.

## Container contract

The image must implement `/ping` and `/invocations`. SageMaker health-checks
`/ping` before sending any traffic; a container that starts but never answers it
fails the deployment with a timeout rather than an error, which reads as a
networking problem and is not one.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
