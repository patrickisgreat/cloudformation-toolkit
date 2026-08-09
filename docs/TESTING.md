# Testing CloudFormation templates

`aws cloudformation validate-template` checks that the JSON parses. It does not
check that a template produces the resources it claims, that its "secure
defaults" are secure, or that an optional resource actually disappears when you
turn it off.

Terraform closed that gap with `terraform test` and `mock_provider`.
CloudFormation has no equivalent, so this repo builds one.

```bash
make test                          # everything
./bin/cfn test -k fargate          # one template
./bin/cfn test -k S3_ENCRYPTION    # one policy rule, across every template
./bin/cfn check                    # lint + tests + docs + catalog, what CI runs
```

Everything runs **offline**: no AWS account, no credentials, no API calls. That
is the property that makes it run on every commit.

## How it works

`tests/cfn_loader.py` teaches PyYAML CloudFormation's intrinsic tags — `!Ref`,
`!GetAtt`, `!Sub` and the rest are not YAML, and a stock parser rejects them. It
normalises short forms to long (`!Ref X` → `{"Ref": "X"}`), so a test never has
to care which spelling the author used, and it **rejects duplicate mapping keys**
— stock YAML silently keeps the last, which in a template means a repeated
logical ID quietly deletes the first one.

The result is wrapped in a `Template` class with a query API:

```python
template.prop("Bucket", "PublicAccessBlockConfiguration.BlockPublicAcls")
template.condition_on("NatGateway2")
template.default("NatGatewayMode")
template.deletion_policy("Cluster")
```

`prop()` raises on a missing path rather than returning `None`, so a typo in a
test fails as a typo instead of silently comparing against nothing.

## Three layers

### 1. Conventions (`tests/test_conventions.py`)

Repo-wide structure, run against every template *and* stack: required files, a
valid `metadata.yaml`, README markers, every parameter and output documented,
parameters grouped for the console, `NamePrefix` present with a pattern, logical
IDs alphanumeric, CloudFormation's own limits respected.

Two of these do more work than they look:

- **The example must actually deploy** — every required parameter supplied, no
  unknown ones, values satisfying `AllowedValues` and `AllowedPattern`. This
  catches the most common rot in a template library: a parameter gets renamed and
  every example silently stops working, because nothing deploys them.
- **Every environment parameter file must target a real template.** `bin/cfn`
  resolves `params/<slug>.json` by the target's slug; a typo there means the
  deploy silently falls back to template defaults.

### 2. Security policy (`tests/test_policy.py`)

~20 rules swept across every template. Each rule is a function returning
findings, and each carries a `why` that is printed on failure — because the
person who just tripped it needs to know whether to fix the template or write an
exemption.

**Rules resolve `Ref`s to parameter defaults.** The claim being tested is *the
defaults are safe*: a caller who deliberately passes an unsafe value is making an
informed choice; a caller who passes nothing must land somewhere defensible.
`resolves_true()` also follows both branches of an `Fn::If`, so a value is only
"safe" if it is safe whichever way the condition goes.

**Exemptions carry justifications.** An entry in `tests/policy_exemptions.yaml`
needs a real reason — the loader rejects a placeholder — and
`test_every_exemption_is_still_needed` fails when an entry stops matching
anything. Without that, a rule can be silently defanged by an exemption written
for a template that has since been fixed.

**A rule needing many exemptions is a bad rule.** Fix the rule. The ledger is
currently empty, and three rules were corrected during the initial build rather
than exempted:

- `SECRET_PARAM_NOECHO` matched `SecretSuffix` and `SecretStringTemplate`. It now
  anchors on the head noun, so `DatabasePassword` matches and `SecretDescription`
  does not.
- `IAM_NO_UNSCOPED_WILDCARD` flagged a KMS key policy, where `Resource: "*"`
  means *this key* and is the only value AWS accepts.
- `SG_RULE_DESCRIPTION` could not see through an `Fn::If`-wrapped rule list,
  which is most of them.

### 3. Per-template suites (`templates/*/*/tests/`)

The direct analog of a `terraform test` suite. The `template` fixture resolves
`../template.yaml` automatically, so a test never spells out its own path.

Four categories, in rough order of value:

1. **Secure defaults.** The *default* configuration is the safe one. This is the
   category that earns the suite its keep: conventions claim secure-by-default;
   these assertions make the claim true rather than aspirational.
2. **Conditional wiring.** Optional resources appear and disappear with their
   toggle, and optional properties resolve to `AWS::NoValue` rather than an empty
   value. Many AWS APIs reject an empty value where they accept an absent one.
3. **Pass-through.** A supplied value reaches the resource unchanged, and
   physical names derive from `NamePrefix`.
4. **Interface.** The parameters and outputs consumers depend on still exist.
   Renaming one is a breaking change.

## Write the message for whoever just broke it

```python
assert template.default("NatGatewayMode") == "single", (
    "Defaulting to per-az triples the monthly floor for every dev environment "
    "someone spins up; defaulting to none breaks any workload that talks to "
    "the public internet. Single is the cheapest thing that works."
)
```

"Must be single" is useless. The message above tells someone what they are about
to change and why it was chosen — which is the difference between a test that
gets fixed and a test that gets deleted.

## Verify the test can fail

An assertion that cannot fail is worse than none, because it reads as coverage.
When you add one, break the template on purpose:

```bash
# flip a default in template.yaml, then:
./bin/cfn test -k <your_template>     # must go red, with a message that explains
git checkout template.yaml
```

## What this cannot catch

Be clear about the boundary. The harness reasons about the template, not about
AWS:

- **Runtime behaviour.** That the health check path returns 200, that the model
  fits in GPU memory, that the IAM policy grants enough. Only a deploy tells you.
- **Cross-resource semantics the schema does not encode.** cfn-lint catches many
  of these; some only appear at deploy time.
- **Quota and capacity.** No GPU capacity in your AZ is not a template problem.
- **Drift.** `cfn drift` covers that, and it needs an account.

The layer above this is `cfn diff` — a real change set against a real account,
showing what would change before it changes. Use it. The offline suite makes the
change set boring; it does not replace it.
