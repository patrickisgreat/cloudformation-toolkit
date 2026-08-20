# Roadmap

**Goal:** deploy any kind of application to AWS from a library of small,
well-documented, tested CloudFormation templates — containerised services in any
language, serverless APIs, GraphQL, data lakes and ETL, databases, and both
managed and self-hosted model inference.

Update this in the same PR that lands a milestone.

Legend: ✅ done · 🟡 partial · ⬜ not started

---

## Where this is (2026-08-20)

32 templates and 1 stack on `main`. `cfn-lint` clean, 1,630 offline tests
passing, docs and catalog generated and checked in CI.

| Area | State |
|------|-------|
| Toolchain (`bin/cfn`, generated docs, generated catalog) | ✅ |
| Test harness (conventions, security policy, per-template) | ✅ |
| Foundation — VPC, KMS, secrets, CI identity, Cognito | ✅ |
| IAM & accounts — roles, groups, users, account vending, Access Analyzer | 🟡 no OU/SCP modelling |
| Containers — ECR, cluster, ALB, Fargate service | ✅ |
| Serverless — Lambda, HTTP API, AppSync | 🟡 no Step Functions or EventBridge |
| Messaging — SQS, SNS | 🟡 no EventBridge bus/rule |
| Data — S3, Kinesis, Firehose, Glue, Athena | ✅ for the batch/stream-to-lake path |
| Databases — DynamoDB, Aurora Serverless v2 | 🟡 no cache, no search |
| ML — SageMaker endpoint, self-hosted GPU serving | 🟡 no training, no registry |
| Networking — ACM, Route 53, CloudFront | 🟡 no WAF |
| Observability — service alarms | 🟡 no dashboards |
| CI/CD templates | ⬜ |
| Stacks | 🟡 one of six |
| Release engineering | ⬜ **consumers cannot pin a version** |

Honest summary: the container path is complete end to end and the data path
nearly so. The composition layer has one archetype where it should have several,
and there is no versioning story at all — a consumer's only option today is a git
reference to a moving `main`, which is a shared folder rather than a library.

---

## Next: the gaps that block real use

### Release engineering ⬜

The largest gap, and it is not a template. Per-template tags
(`containers/fargate-service/v1.2.0`) so templates version independently, a
changelog driven off the conventional commits already enforced, and a
`docs/CONSUMING.md` covering how to pin, how to upgrade, and what
`BREAKING CHANGE:` means for a template interface.

### The remaining stacks 🟡

`container-service` proves the pattern. Five more make the library usable without
reading it:

- `serverless-api` — HTTP API + Lambda + DynamoDB + alarms
- `graphql-api` — AppSync + DynamoDB + Cognito
- `static-site` — S3 + CloudFront + ACM + Route 53
- `data-lake-etl` — Kinesis → Firehose → S3 → Glue → Athena, wired
- `llm-inference` — GPU serving + ALB + model artifact bucket + alarms

CloudFront and Cognito have since landed, which unblocks `static-site` and
`graphql-api`; EventBridge is the one template still missing.

### Missing templates, roughly in order of demand

| Template | Unblocks |
|----------|----------|
| `networking/waf-web-acl` | Hooks already exist on `containers/alb` and `networking/cloudfront-distribution` |
| `messaging/eventbridge-rule` | Scheduled jobs, event-driven ETL, S3 → Lambda without coupling |
| `serverless/step-functions` | Orchestrated ETL and long-running workflows |
| `database/elasticache-redis` | Sessions, caching, rate limiting |
| `cicd/codepipeline-ecs` | Build and deploy without GitHub Actions |
| `ml/model-registry` | Versioned model artifacts with promotion between environments |

---

## Deliberately not built

Saying no is part of the design.

- **A template per language.** Nine languages collapse into
  `containers/fargate-service`. See [ARCHETYPES.md](ARCHETYPES.md).
- **Cross-stack `Export`s.** They make the producing stack undeletable. See
  [ARCHITECTURE.md](ARCHITECTURE.md).
- **`AWS::LanguageExtensions` loops.** They expand server-side, so cfn-lint
  cannot check the result and change sets show the unexpanded form.
- **Multi-cloud.** This is a CloudFormation repo. GCP lives in `tf-tools`.
- **A template per AWS service.** Breadth for its own sake produces 200
  templates nobody has tested. Each one here exists because an archetype needs
  it.

---

## Quality work that runs alongside

- **`examples/complete/`** beside every `examples/basic/`, showing the
  fully-wired case.
- **A second policy engine.** `cfn-guard` or Checkov as a cross-check on the
  Python rules — a different tool catches different things.
- **`infracost` in PR comments.** Cost as review context, which NAT gateways and
  GPU instances make matter a great deal.
- **Deploy-time verification.** The offline suite cannot tell you the health
  check returns 200. A smoke-test target that deploys a stack into a scratch
  account, asserts, and tears down would close the loop.
- **A docs site** from the generated tables, with the archetype table as the
  entry point.

---

## Sequencing rationale

Release engineering comes first because everything after it is more templates on
a foundation nobody can pin. After that, stacks — the library's value is highest
at the composition layer, and each new stack surfaces the primitives it is
missing, which is a better way to choose what to build next than a list.
