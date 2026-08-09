# CLAUDE.md

Operating guidance for Claude Code (and humans) working in
**cloudformation-toolkit**. Read this before making changes. For the reasoning
behind the structure see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); for
template-authoring detail see [docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## What this repo is

A library of reusable, parameterized CloudFormation templates, in three layers:

- `templates/<group>/<name>/` — the library. One template, one job. Standalone
  and nestable.
- `stacks/<name>/` — archetypes composed from library templates. **No inline
  resources.**
- `environments/<env>/` — region, tags, stack naming, and parameter sets.

## Commands

```bash
make install     # .venv with cfn-lint + pytest — the only setup step
make check       # lint + tests + docs + catalog freshness. What CI runs.
```

| Command | What it does |
|---------|--------------|
| `./bin/cfn lint` | cfn-lint every template against the resource-provider schemas |
| `./bin/cfn test [-k expr]` | The offline test suite |
| `./bin/cfn docs [--check]` | Regenerate the parameter/output tables in each README |
| `./bin/cfn catalog [--check]` | Regenerate the root README catalog |
| `./bin/cfn params <target>` | A template's parameters, grouped, required first |
| `./bin/cfn new <group>/<name>` | Scaffold a template that is born tested |
| `./bin/cfn diff <target> --env dev` | Change set preview, then discarded |
| `./bin/cfn deploy <target> --env dev` | Package if needed, create or update |

**Run `./bin/cfn check` before committing.** It is fast and entirely offline.

## Non-negotiables

These are the rules that the tests enforce, and the reasons they exist:

1. **Secure defaults, provably.** The default parameter set must produce the safe
   configuration, and `tests/test_policy.py` must agree. Rules resolve `Ref`s to
   parameter defaults, because that is the claim being tested.
2. **A rule needing many exemptions is a bad rule.** Fix the rule, not the
   ledger. Three rules were corrected during the initial build rather than
   exempted; `tests/policy_exemptions.yaml` is still empty.
3. **Anything with a recurring cost defaults to off.** Spot, interface endpoints,
   flow logs, enhanced fan-out, provisioned concurrency, Glue jobs. Free things
   (gateway endpoints, encryption, long polling) default on.
4. **No secrets through parameters.** Templates generate into Secrets Manager and
   pass ARNs. A value in a parameter is visible in the change set, the events,
   and CI logs — `NoEcho` masks the API response, not the change set.
5. **Stateful resources are `Retain`** (or `Snapshot` for Aurora). A rollback
   must never be able to delete data.
6. **Stacks contain no inline resources.** A resource that exists only inside a
   composition is one nobody can reuse and no per-template test covers.
7. **Generated tables are generated.** Never hand-edit between the
   `<!-- BEGIN_CFN_DOCS -->` or `<!-- BEGIN_CATALOG -->` markers.

## Adding a template

`./bin/cfn new <group>/<name>`, then follow
[docs/ADDING_A_TEMPLATE.md](docs/ADDING_A_TEMPLATE.md). The parts people skip:

- The example under `examples/basic/` must be a set that would **actually
  deploy** — the conventions suite checks it.
- Break the template on purpose and watch a test fail. An assertion that cannot
  fail reads as coverage and is worse than none.
- The README's hand-written section explains *which knobs matter and why* — the
  decision that costs money, the default that surprises people, the failure mode
  and what it looks like. The generated table already says what the parameters
  are.

## CloudFormation limits worth knowing before you fight one

- **No loops** without `AWS::LanguageExtensions`, which expands server-side and
  defeats cfn-lint and change-set review. Use N explicit resources or N fixed
  slots.
- **`Fn::If` cannot add or remove a map key**, only substitute a value. Swap the
  whole map where you can.
- **`AWS::NoValue` removes a property entirely**, which matters because many APIs
  reject an empty value where they accept an absent one.
- **`DependsOn` cannot be conditional.** Reference the resource inside an
  `Fn::If` instead — `containers/fargate-service` does this and explains it.
- **Parameters cap at 4096 characters.** Larger inputs come from S3.
- **An output referencing a conditional resource needs the same `Condition`.**

## Git workflow

`main` is always releasable and gated by CI. Branch per change,
`type/short-kebab-description`. One concern per PR; a template plus its example,
docs and tests is one coherent PR.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org)
and are linted on every PR:

```
feat(containers/fargate-service): add request-count autoscaling
fix(data/firehose-to-s3): drop RetryOptions, unsupported on S3 destinations
docs(testing): explain why policy rules resolve Refs to defaults
```

Scope is the template path or the area (`ci`, `docs`, `tests`). The PR title
becomes the squash-merge subject, so it follows the same format.

## Gotchas

- **`cfn-lint` has no `templates:` glob in `.cfnlintrc.yaml`** on purpose — a
  glob matching nothing is a hard error, so `bin/cfn lint` enumerates files with
  `find` instead.
- **Three lint rules are suppressed**, each with a written reason in
  `.cfnlintrc.yaml`. Do not add a fourth without one.
- **`bin/cfn` targets bash 3.2** (what macOS ships). No `mapfile`, no
  associative arrays.
- **Never commit** `.cfn-build/`, packaged templates, real account IDs, or a
  parameter file containing a secret.
