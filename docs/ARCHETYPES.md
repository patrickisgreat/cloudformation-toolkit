# Archetypes: language → runtime shape → template

The list of languages people want to deploy is long and keeps growing. Building a
template per language would be a treadmill.

**Infrastructure cares about runtime shape, not source language.** Nearly every
language collapses into one of five shapes, and one well-built container
archetype covers most of them.

## The mapping

| Language / runtime | Packaging | Archetype |
|---|---|---|
| Go, Rust, C++ | static binary → distroless/scratch image | **container-service** |
| Java, Kotlin (JVM) | fat JAR → JRE image | **container-service** (raise the health-check grace period) |
| C#, .NET | self-contained publish → image | **container-service** |
| Node, TypeScript | image, or zip for functions | **container-service** or **serverless-function** |
| Python | image, or zip / container for functions | **container-service** or **serverless-function** |
| GraphQL (Apollo, gqlgen, Strawberry, Hot Chocolate) | image | **container-service**; managed alternative below |
| REST / gRPC APIs | image | **container-service** (gRPC needs `ProtocolVersion: GRPC`) |
| Python ML inference | image + GPU | **model-serving** |
| Static SPA / SSG | bundle | **static-site** *(not yet built)* |
| Swift (iOS), Kotlin (Android) | app bundle — **not server-deployed** | needs a *backend*, not a deployment |

## The five archetypes

### container-service — the 80% path

[`stacks/container-service`](../stacks/container-service), built on
[`containers/fargate-service`](../templates/containers/fargate-service).

Nine of the languages above land here. What changes between them is the image and
a handful of parameters, not the infrastructure.

Per-runtime notes that matter:

| Runtime | Watch |
|---|---|
| Go, Rust, C++ | Distroless or scratch images. Startup is fast, so the default 60s health-check grace is generous. |
| Java, Kotlin | **Raise `HealthCheckGracePeriodSeconds`.** A JVM with a large heap can take minutes, and too short a grace period gives an endless kill-and-restart loop that looks like a crash. Set heap from the container limit, not the host. |
| .NET | Self-contained publish with trimming. Similar startup profile to the JVM but usually faster. |
| Node, Python | Watch memory more than CPU. Set `StopTimeoutSeconds` above your longest request so deploys do not cut responses off. |
| gRPC | `ProtocolVersion: GRPC` switches health checking to gRPC status codes, so `HealthCheckPath` becomes a method like `/grpc.health.v1.Health/Check`. The ALB requires TLS for gRPC. |

### serverless-function

[`serverless/lambda-function`](../templates/serverless/lambda-function) +
[`serverless/http-api`](../templates/serverless/http-api).

Right when traffic is bursty or low, when scale-to-zero matters, or for glue
between AWS services. `provided.al2023` runs Rust and Go binaries; `PackageType:
Image` lifts every runtime restriction.

Wrong when you have a long-running process, a warm in-process cache, a
persistent connection, or a request that runs longer than 15 minutes.

### graphql

Two genuinely different answers:

- **A container running your GraphQL server** (Apollo, gqlgen, Strawberry, Hot
  Chocolate) on `container-service`. Resolvers are ordinary code you can run on a
  laptop.
- **[`serverless/appsync-graphql`](../templates/serverless/appsync-graphql)** for
  managed subscriptions over WebSockets and declarative per-field authorisation.

Choose AppSync for subscription-heavy, per-field-authorised APIs. Choose a
container when you want your resolvers to be code rather than configuration.

### model-serving

Two answers again, and the split is about who operates the GPU:

- **[`ml/sagemaker-endpoint`](../templates/ml/sagemaker-endpoint)** — managed.
  Serverless mode scales to zero for embeddings and classifiers; real-time mode
  handles GPU inference with autoscaling and rollback-on-error deployments.
- **[`ml/gpu-inference-service`](../templates/ml/gpu-inference-service)** —
  self-hosted vLLM or TGI on your own GPU fleet, serving an OpenAI-compatible
  API, with scale-to-zero. Cheaper per token at volume, and yours to operate.

### data-pipeline

[`data/kinesis-stream`](../templates/data/kinesis-stream) →
[`data/firehose-to-s3`](../templates/data/firehose-to-s3) →
[`data/s3-bucket`](../templates/data/s3-bucket) →
[`data/glue-etl`](../templates/data/glue-etl) →
[`data/athena-workgroup`](../templates/data/athena-workgroup).

Ingest, land partitioned and compressed, catalog, query. Batch instead of
streaming? Drop the stream and write to the bucket directly; everything
downstream is unchanged.

## The honest caveat on mobile

Swift/iOS and Kotlin/Android apps do not deploy to Fargate. What they need from
this repo is their **server side**: an API (`container-service` or
`serverless-api`), a database, object storage, and push delivery.

Calling an iOS app a "deployable workload" would be pretending. The archetype for
a mobile app is a backend plus an artifact distribution path, and the backend is
the part this library builds.
