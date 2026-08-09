# Architecture

Three layers, and the reasoning behind the decisions that are easy to get wrong.

```
templates/<group>/<name>/      the library
  template.yaml                one job, done well
  metadata.yaml                catalog row
  README.md                    the decisions that matter + generated tables
  examples/basic/parameters.json
  tests/test_<name>.py         proof the defaults are what the README claims

stacks/<name>/                 archetypes — same shape, composed of the above
environments/<env>/            region, tags, naming, parameter sets
```

A consumer can enter at any layer: deploy one template, deploy a whole archetype,
or nest a template inside a stack of their own.

## Why primitives *and* compositions

A library of only primitives makes every consumer write the glue, and the glue is
where the mistakes live — a task security group open to the VPC instead of the
load balancer, an alias record pointing at its own zone.

A library of only archetypes cannot be adapted. The moment you need a second
queue or a different database, you fork it.

So: primitives stay boring and reusable, archetypes carry the opinions, and
**stacks contain no inline resources**. A resource defined only inside a
composition is one nobody can reuse and one no per-template test covers.
`tests/test_container_service.py` asserts that mechanically.

## Nested stacks, not one flat template

`stacks/*` use `AWS::CloudFormation::Stack` with relative `TemplateURL` paths;
`bin/cfn deploy` runs `aws cloudformation package` to upload the children and
rewrite the URLs.

The alternative — generating one flat template — would avoid the S3 bucket, but
it gives up the thing that makes this library a library: the child is the *same
file* that a consumer can deploy standalone, lint, and test. There is no build
step between what you read and what deploys.

Costs to be aware of:

- A nested stack failure rolls back the parent, so a bad DNS parameter can undo
  the VPC. Deploy foundational stacks separately once they matter.
- `describe-change-set` on the parent shows the child stack as one resource, not
  its contents. `cfn diff` reports what changed at the child level.
- Packaging needs `artifacts_bucket` set in the environment config.

## No `Export`s, deliberately

Templates output values. Nothing is `Export`ed, and nothing uses
`Fn::ImportValue`.

An export makes the producing stack **undeletable while any consumer exists**,
and un-updatable in the exported value. In practice that means the network stack
you most need to change is the one you cannot, and the failure arrives as
`Export cannot be updated as it is in use by ...` halfway through a deploy.

Values move two ways instead:

- **Within a stack** — a child's `Outputs` become a sibling's `Parameters` via
  `!GetAtt Child.Outputs.Name`. Explicit, visible in the template, no coupling
  outside it.
- **Between stacks** — `cfn outputs <target> --env dev` prints them, and
  environment parameter files record them. Manual, but the coupling stays where
  you can see it.

The trade is real: cross-stack references would be less typing. Deletability of
foundational stacks is worth more.

## Conditions are `count`

Terraform expresses optionality with `count` or `for_each`. CloudFormation has
`Conditions`, and every optional resource in this library carries one:

```yaml
Conditions:
  HasNat: !Not [!Equals [!Ref NatGatewayMode, none]]

Resources:
  NatGateway1:
    Condition: HasNat
```

For an optional *property*, `Fn::If` with `AWS::NoValue` removes it entirely —
which matters because many AWS APIs reject an empty value where they accept an
absent one (`SqsManagedSseEnabled: false` alongside a KMS key still errors).

An output that references a conditional resource must carry the same condition,
or the stack fails to create when the toggle is off. The per-template suites
check both.

## Where CloudFormation runs out

Honest limits this library works within rather than around:

**No loops.** `Fn::ForEach` exists in the `AWS::LanguageExtensions` transform,
but it expands server-side: cfn-lint cannot check the result and
`describe-change-set` shows the unexpanded form. So N-of-a-thing is N explicit
resources (the six VPC endpoints) or N fixed slots
(`fargate-service`'s four environment variables). Both are reviewable; a loop
only the service can evaluate is not.

**`Fn::If` cannot add or remove a map key**, only substitute a value. Lambda's
environment variables are a map, so unused slots appear as empty strings. Where
the whole map can be swapped instead — SageMaker's container environment — it is.

**4096-character parameter limit.** Anything larger comes from S3, which is why
`appsync-graphql` takes `SchemaS3Location` rather than a schema.

**No date arithmetic.** `AWS::AppSync::ApiKey` wants an absolute epoch second;
there is no way to express "30 days from deploy", so a relative parameter would
silently bake in the date of the first deploy.

## Where the safety lives

| Layer | Catches |
|-------|---------|
| `cfn-lint` | Schema violations: bad property names, wrong types, invalid enums, bad `GetAtt` targets |
| `tests/test_conventions.py` | Structure: missing README markers, an example that could not deploy, a template with no test suite |
| `tests/test_policy.py` | Security defaults across every template, with a justified-exemption ledger |
| `templates/*/*/tests/` | This template's own claims |
| `cfn diff` | What a deploy would actually change, before it changes it |

All of it runs offline. No AWS account, no credentials, no `validate-template`
round trip — which is what makes it run on every commit rather than occasionally.
