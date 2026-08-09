# `foundation/github-oidc-role`

An IAM role GitHub Actions assumes over OIDC, scoped to one repository and a
chosen set of refs. This is how you delete the `AWS_SECRET_ACCESS_KEY` from your
repository secrets.

## Usage

```bash
./bin/cfn deploy foundation/github-oidc-role --env dev \
  --param GitHubOrg=your-org --param GitHubRepo=your-repo
```

Then in the workflow:

```yaml
permissions:
  id-token: write      # without this, no OIDC token is minted and the step fails
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<account>:role/<NamePrefix>-github-deploy
          aws-region: us-east-1
      - run: ./bin/cfn deploy container-service --env dev --yes
```

`permissions: id-token: write` is the step everyone forgets. Without it the
runner never receives a token, and `configure-aws-credentials` fails with a
message about a missing `ACTIONS_ID_TOKEN_REQUEST_URL`.

## The trust policy is the whole security model

Two conditions do the work, and both are mandatory:

- **`aud` = `sts.amazonaws.com`** — stops a token minted for some other relying
  party from being replayed against STS.
- **`sub` matches your repo and ref** — stops *every other repository on GitHub*
  from assuming the role. A trust policy with only the audience check is a
  well-known catastrophic misconfiguration: GitHub is the issuer for every public
  repository in the world.

The subject is scoped from strongest to weakest:

| Setting | Subject matched | Notes |
|---------|-----------------|-------|
| `AllowedEnvironment` | `repo:org/repo:environment:production` | Strongest. A GitHub Environment can require manual approval before the job runs. |
| `AllowedBranch` (default `main`) | `repo:org/repo:ref:refs/heads/main` | Supports a trailing wildcard, e.g. `release/*`. |
| `AllowPullRequests` | `repo:org/repo:pull_request` | **Off by default.** A PR from a fork runs code its author controls, and this role can deploy. |

For production, prefer `AllowedEnvironment` with a required reviewer over a
branch match. A branch match is only as strong as your branch protection.

## One provider per account

`AWS::IAM::OIDCProvider` for `token.actions.githubusercontent.com` is a
singleton per AWS account. The first stack creates it; every stack after that
sets `CreateOidcProvider=false` and passes `ExistingOidcProviderArn`. Creating a
second one fails with `EntityAlreadyExists` partway through the deploy.

## What the role can do

`GrantCloudFormationDeploy` attaches an inline policy for driving stacks —
change sets, updates, describes — scoped to stacks named `<Environment>-*`, which
matches the naming `bin/cfn` uses. It deliberately does **not** grant permission
to create the underlying resources. Give it those separately via
`ManagedPolicyArn`, so the deploy permission and the resource permission are two
reviewable decisions rather than one.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
