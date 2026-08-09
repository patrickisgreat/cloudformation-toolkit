# `ml/gpu-inference-service`

Run an open-weight model on your own GPUs: a GPU EC2 Auto Scaling group joined to
an ECS cluster as a capacity provider, serving vLLM's OpenAI-compatible API
behind a load balancer, with scale-to-zero when idle.

**Status: beta.** Every resource is schema-valid and the wiring is right, but GPU
serving has a lot of moving parts and this has not been exercised across every
instance family. Read the failure modes below before running it in production.

## Usage

```bash
./bin/cfn deploy ml/gpu-inference-service --env dev \
  --param ClusterName=<cluster> --param ListenerArn=<alb-listener> \
  --param ModelId=mistralai/Mistral-7B-Instruct-v0.3
```

Once running, it is an OpenAI-compatible endpoint:

```bash
curl https://<alb-domain>/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"default","messages":[{"role":"user","content":"hello"}]}'
```

`ServedModelName` defaults to `default` so swapping the underlying weights does
not break every caller.

## Read this before you deploy: the capacity provider is authoritative

`AWS::ECS::ClusterCapacityProviderAssociations` **replaces the cluster's entire
capacity provider list**. This template re-lists `FARGATE` and `FARGATE_SPOT`
alongside the GPU provider for exactly that reason.

If you have customised your cluster's providers, reconcile them here first.
Omitting a provider silently detaches every service using it from its capacity —
the services keep reporting healthy and stop being able to place new tasks.

## Cost

The GPU fleet *is* the cost. Rough on-demand figures:

| Instance | GPU | ~$/hour | ~$/month if always on |
|----------|-----|---------|----------------------|
| `g5.xlarge` | 1× A10G 24 GB | $1.00 | $730 |
| `g5.12xlarge` | 4× A10G 96 GB | $5.70 | $4,100 |
| `p4d.24xlarge` | 8× A100 40 GB | $32.77 | $23,600 |

**`MinInstanceCount: 0` is the default and it matters.** Scale-to-zero is the
difference between a dev environment costing $30/month and $730. The cost is a
cold start of several minutes — instance launch, image pull, then model load.

`MaxInstanceCount` is a hard cost cap. Set it before you need it.

`UseSpotInstances` saves 60–70%. Reasonable for batch and dev; for interactive
serving, understand that a reclamation means a multi-minute model reload before
the replacement can answer.

## Sizing the model to the card

`MaxModelLength` (8192) is the parameter people get wrong. vLLM **pre-allocates
KV cache** for the full context length, so pointing a 128k-context model at a
24 GB card fails at startup with an out-of-memory error that names KV cache
rather than the parameter you need to change.

Rough guide for a 24 GB A10G:

| Model | Precision | Fits? |
|-------|-----------|-------|
| 7–8B | 16-bit | Yes, ~8k context |
| 13B | 8-bit / AWQ | Yes |
| 13B | 16-bit | No |
| 70B | any | No — needs `g5.12xlarge` or larger |

`GpuMemoryUtilization` (0.90) leaves headroom for CUDA context and
fragmentation. 0.95+ raises throughput and the chance of an OOM kill
mid-request.

## The failure modes, and what they look like

| Symptom | Cause |
|---------|-------|
| Service stuck at 0 running tasks, no error | `TaskCpu`/`TaskMemoryMb`/`GpuCount` exceed what the instance has. Nothing can place. |
| Endless kill-and-restart that looks like a crash | `HealthCheckGracePeriodSeconds` shorter than model load. Default here is **900s** for that reason. |
| Task killed a few minutes into first start | Image pull plus model download exceeded the ECS start timeout. The agent config raises both to 15 minutes. |
| Startup OOM naming KV cache | `MaxModelLength` too large for the card. |
| Crash on startup in a CUDA allocator | Shared memory. `SharedMemorySize: 8192` is set because model servers allocate large pinned host buffers and fail on the 64 MB default. |
| Docker Hub rate limit at scale-out | Mirror `ServingImageUri` into your own ECR. |

## Design notes

- **`NetworkMode: bridge`, not `awsvpc`.** An awsvpc task consumes an ENI per
  task, and GPU instance types have low ENI limits.
- **One task per instance** (`spread` by `instanceId`). Two model servers on one
  GPU means both fail to allocate KV cache.
- **`MinimumHealthyPercent: 0`.** GPU capacity is scarce and expensive: the usual
  100/200 deployment would need double the fleet, and may simply not be
  available.
- **`ManagedTerminationProtection: ENABLED`.** Without it a scale-in can
  terminate an instance mid-generation.
- **No SSH, no key pair, no port 22.** Debugging a stuck model load is common;
  the instance role carries `AmazonSSMManagedInstanceCore` so you use Session
  Manager instead.
- **The AMI is resolved from SSM at deploy time.** Hardcoding an ID pins you to
  one region and to whatever NVIDIA driver was current that day.
- **`HF_HOME` on the instance volume**, so a task restart on the same instance
  reuses the weights instead of re-downloading tens of gigabytes.

## Gated models

Llama and similar require accepting a licence. Put a Hugging Face token in
Secrets Manager (`foundation/secret`) and pass `HuggingFaceTokenSecretArn`; it is
injected as `HUGGING_FACE_HUB_TOKEN` and the execution role is granted read
access to exactly that secret.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
