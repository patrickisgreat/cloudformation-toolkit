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
<!-- Generated by `./bin/cfn docs`. Do not edit between these markers. -->

### Parameters

| Parameter | Description | Type | Default |
|-----------|-------------|------|---------|
| `NamePrefix` | Prefix for every resource this stack names. | `String` | **required** |
| `Environment` | Environment this service runs in.<br>Allowed: `dev`, `staging`, `prod` | `String` | `dev` |
| `ServiceSuffix` | Distinguishes model services, e.g. "llama" or "embeddings". | `String` | `llm` |
| `ClusterName` | Existing ECS cluster from containers/ecs-cluster. Read the README before deploying - attaching a capacity provider replaces the cluster's entire provider list, including FARGATE and FARGATE_SPOT. | `String` | **required** |
| `VpcId` | VPC the instances and target group live in. | `AWS::EC2::VPC::Id` | **required** |
| `SubnetIds` | Private subnets for the GPU instances. GPU capacity is not evenly distributed across AZs; spanning three materially improves the chance of getting an instance at all. | `List<AWS::EC2::Subnet::Id>` | **required** |
| `AlbSecurityGroupId` | Load balancer security group. Instances admit traffic from this group only. | `String` | **required** |
| `ListenerArn` | ALB listener to attach to, from containers/alb. | `String` | **required** |
| `ListenerRulePriority` | Priority of this service's listener rule; unique per listener. | `Number` | `300` |
| `PathPattern` | Path this service answers for. vLLM serves an OpenAI-compatible /v1 API. | `String` | `/v1/*` |
| `InstanceType` | GPU instance type. g5.xlarge (1x A10G, 24 GB) runs a 7-8B model in 16-bit or a 13B quantised. g5.12xlarge (4x A10G) or g6e are needed above that. This choice dominates the bill: a single on-demand g5.12xlarge is roughly $4,000/month if left running.<br>Allowed: `g5.xlarge`, `g5.2xlarge`, `g5.4xlarge`, `g5.12xlarge`, `g5.48xlarge`, `g6.xlarge`, `g6e.xlarge`, `p4d.24xlarge` | `String` | `g5.xlarge` |
| `MinInstanceCount` | Floor for the GPU fleet. 0 means scale to zero when idle - the difference between a dev environment costing $30/month and $700. The cost is a cold start of several minutes: instance launch, image pull, then model load. | `Number` | `0` |
| `MaxInstanceCount` | Ceiling for the GPU fleet, and your hard cost cap. | `Number` | `2` |
| `UseSpotInstances` | Run the fleet on Spot, at roughly 60-70% off, with a two-minute interruption notice. Reasonable for batch and for dev. For interactive serving, understand that reclamation means a multi-minute model reload before the replacement can serve.<br>Allowed: `true`, `false` | `String` | `false` |
| `RootVolumeSizeGb` | Root volume size. Model weights land here, and they are large - a 7B model in 16-bit is ~15 GB, a 70B is ~140 GB. Too small a volume fails the pull after several minutes with a disk-space error. | `Number` | `200` |
| `ServingImageUri` | Model server image, e.g. vllm/vllm-openai:latest or a Text Generation Inference image. Mirror it into your own ECR rather than pulling from Docker Hub on every instance launch - the rate limit will find you. | `String` | `vllm/vllm-openai:latest` |
| `ModelId` | Hugging Face model to serve, e.g. "meta-llama/Llama-3.1-8B-Instruct" or "mistralai/Mistral-7B-Instruct-v0.3". Gated models additionally need HuggingFaceTokenSecretArn. | `String` | `mistralai/Mistral-7B-Instruct-v0.3` |
| `ServedModelName` | Name clients use in the OpenAI-compatible "model" field. Keeping it stable means swapping the underlying weights does not break every caller. | `String` | `default` |
| `MaxModelLength` | Maximum context length. vLLM pre-allocates KV cache for this, so setting it to a model's full 128k context on a 24 GB card fails at startup with an out-of-memory error that names KV cache rather than the parameter. | `Number` | `8192` |
| `GpuMemoryUtilization` | Fraction of GPU memory vLLM may claim. 0.90 leaves headroom for CUDA context and fragmentation; 0.95+ raises throughput and the chance of an out-of-memory kill mid-request. | `String` | `0.90` |
| `ContainerPort` | Port the model server listens on. vLLM's OpenAI server defaults to 8000. | `Number` | `8000` |
| `HuggingFaceTokenSecretArn` | Secrets Manager ARN holding a Hugging Face token, for gated models such as Llama. Injected as HUGGING_FACE_HUB_TOKEN. Leave empty for open models. | `String` | `""` |
| `TaskCpu` | CPU units reserved for the task. Leave headroom below the instance total - a task requesting the whole instance never places, and the failure appears as a service stuck at 0 running tasks with no error. | `Number` | `3584` |
| `TaskMemoryMb` | Memory reserved. Same caution: request less than the instance has, or the task never places. | `Number` | `14336` |
| `GpuCount` | GPUs the task reserves. Must match the instance type - asking for 4 on a g5.xlarge leaves the task permanently pending. | `Number` | `1` |
| `HealthCheckPath` | Health endpoint. vLLM exposes /health. | `String` | `/health` |
| `HealthCheckGracePeriodSeconds` | Seconds before the load balancer's verdict is trusted. Model load is the long pole: downloading and loading a 7B model takes minutes, and too short a grace period produces an endless kill-and-restart loop that looks like a crash. | `Number` | `900` |
| `LogRetentionDays` | Retention for the model server log group.<br>Allowed: `1`, `3`, `5`, `7`, `14`, `30`, `60`, `90`, `120`, `150`, `180`, `365`, `400`, `545`, `731`, `1827`, `3653` | `Number` | `30` |

### Outputs

| Output | Description | Exported as |
|--------|-------------|-------------|
| `ServiceName` | ECS service name. | — |
| `TargetGroupArn` | Target group the model server registers with. | — |
| `CapacityProviderName` | GPU capacity provider. Other services on this cluster can target it by name to run on the same fleet. | — |
| `AutoScalingGroupName` | GPU Auto Scaling group, for manual capacity changes and alarms. | — |
| `InstanceSecurityGroupId` | Security group of the GPU instances. | — |
| `LogGroupName` | Log group holding model server output. Model load progress and CUDA out-of-memory errors both appear here. | — |
| `ApiPathPattern` | Path this service answers on, e.g. /v1/* for the OpenAI-compatible API. | — |

### Resources

| Logical ID | Type | Created when |
|------------|------|--------------|
| `LogGroup` | `AWS::Logs::LogGroup` | always |
| `InstanceSecurityGroup` | `AWS::EC2::SecurityGroup` | always |
| `InstanceRole` | `AWS::IAM::Role` | always |
| `InstanceProfile` | `AWS::IAM::InstanceProfile` | always |
| `LaunchTemplate` | `AWS::EC2::LaunchTemplate` | always |
| `AutoScalingGroup` | `AWS::AutoScaling::AutoScalingGroup` | always |
| `CapacityProvider` | `AWS::ECS::CapacityProvider` | always |
| `ClusterProviders` | `AWS::ECS::ClusterCapacityProviderAssociations` | always |
| `ExecutionRole` | `AWS::IAM::Role` | always |
| `TaskRole` | `AWS::IAM::Role` | always |
| `TaskDefinition` | `AWS::ECS::TaskDefinition` | always |
| `TargetGroup` | `AWS::ElasticLoadBalancingV2::TargetGroup` | always |
| `ListenerRule` | `AWS::ElasticLoadBalancingV2::ListenerRule` | always |
| `Service` | `AWS::ECS::Service` | always |
<!-- END_CFN_DOCS -->
