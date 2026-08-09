# Adding a template

## 1. Scaffold

```bash
./bin/cfn new data/redshift-serverless
```

This copies `templates/_template/`, which is deliberately not empty: it has a
working template with a conditional resource, a real example, and a test suite
that passes. A template scaffolded this way is born tested.

## 2. Write the template

Follow [CONVENTIONS.md](CONVENTIONS.md). The order that works:

1. **Parameters first.** They are the interface, and getting them right is most
   of the design. Start with `NamePrefix` and `Environment` (already there), then
   ask what a caller genuinely has to decide. Every parameter needs a
   `Description` written for someone who has not read the AWS docs.
2. **Conditions.** One per optional feature. Name them as predicates.
3. **Resources.** Secure defaults, `AWS::NoValue` for optional properties,
   `DeletionPolicy: Retain` (or `Snapshot`) on anything holding data.
4. **Outputs.** What does a consumer need to wire this to something else? Include
   both halves of anything that comes in pairs.
5. **Parameter groups** in `Metadata.AWS::CloudFormation::Interface`. If a
   parameter fits no group, it usually belongs in a different template.

Lint as you go — cfn-lint is fast and catches most mistakes immediately:

```bash
./bin/cfn lint templates/data/redshift-serverless/template.yaml
```

## 3. Write the example

`examples/basic/parameters.json` must be a set that would **actually deploy**:
every required parameter, no unknown ones, values that satisfy every
`AllowedValues` and `AllowedPattern`. The conventions suite checks all of that.

Use obviously-fake but well-formed placeholders — `vpc-0123456789abcdef0`,
`123456789012` — so nobody deploys someone else's account ID by accident.

## 4. Write the tests

Aim for 6–10 assertions across the four categories in
[TESTING.md](TESTING.md): secure defaults, conditional wiring, pass-through,
interface. Three is the enforced minimum; three is rarely enough.

Then **break the template on purpose** and confirm the suite goes red with a
message that explains what broke. An assertion that cannot fail is worse than no
assertion.

## 5. Fill in the metadata and README

`metadata.yaml` — `group` must match the directory, `summary` one line under 110
characters, `status` per the criteria in CONVENTIONS.md. Start at `beta` if there
is a known limitation, and say what it is in the README.

`README.md` — replace the scaffold's placeholder text. The generated tables cover
*what* the parameters are; your job is *which ones matter*:

- The decision that costs money.
- The default that will surprise someone, and why it was chosen.
- The failure mode and what it looks like when it happens.
- The escape hatch for the case the defaults do not cover.

The template READMEs in this repo are the reference; `foundation/vpc` and
`containers/fargate-service` are the fullest examples.

## 6. Regenerate and check

```bash
./bin/cfn docs        # parameter/output/resource tables
./bin/cfn catalog     # the root README catalog
./bin/cfn check       # lint + tests + docs + catalog freshness
```

## 7. Open a PR

One template per PR. Conventional Commit title (`feat(data/redshift-serverless):
add Redshift Serverless workgroup`), since it becomes the squash-merge subject.

### Checklist

- [ ] `./bin/cfn check` passes
- [ ] The test suite covers secure defaults, conditional wiring and pass-through
- [ ] You broke the template on purpose and watched a test fail
- [ ] `examples/basic/parameters.json` would deploy as written
- [ ] The README explains the decisions, not just the parameters
- [ ] `metadata.yaml` is accurate and `./bin/cfn docs && ./bin/cfn catalog` re-run
- [ ] No account IDs, no real hostnames, no secrets in parameter files
- [ ] Anything with a recurring cost defaults to off

## Adding a stack

Same shape, in `stacks/<name>/`, with two extra rules:

- **No inline resources.** Every resource is an
  `AWS::CloudFormation::Stack` pointing at a library template by relative path.
  If a stack needs something the library does not have, add the template first.
- **Test the wiring.** A stack's job is connecting outputs to inputs, so its
  tests assert exactly that — the child paths resolve, and each `!GetAtt
  Child.Outputs.X` lands on the right parameter. A mistyped one fails 15 minutes
  into a deploy.

`stacks/container-service/tests/` is the reference.
