# `foundation/secret`

A Secrets Manager secret whose value is **generated at create time**, so it never
exists in a template, a parameter file, a terminal, or CloudTrail.

## Usage

```bash
./bin/cfn deploy foundation/secret --env dev --param SecretSuffix=db
```

Consume it from an ECS task definition — the container receives the value as an
environment variable, and the value never appears in the task definition itself:

```yaml
Secrets:
  - Name: DB_PASSWORD
    ValueFrom: !Sub "${SecretArn}:password::"
```

Or from another template at deploy time, with a dynamic reference:

```yaml
MasterUserPassword: !Sub "{{resolve:secretsmanager:${SecretArn}:SecretString:password}}"
```

## There is no `SecretString` parameter, on purpose

You cannot pass a value into this template. That is the design.

A secret supplied as a CloudFormation parameter is visible in the change set, in
`describe-stacks`, in the stack events, and in every CI log that prints the
deploy — even with `NoEcho`, which only masks the API response, not the change
set you reviewed. A secret that has been through a parameter is a secret you
should rotate.

For values you did not generate (an API key a vendor issued you), set
`GenerateSecret=false` to create the empty container, then populate it out of
band:

```bash
aws secretsmanager put-secret-value \
  --secret-id dev/example-app/vendor-key \
  --secret-string "$(read -rs KEY && echo "$KEY")"
```

## The generated value

`SecretStringTemplate` + `GenerateStringKey` produce JSON like
`{"username":"appuser","password":"<generated>"}`, which is the shape RDS,
Aurora, and DocumentDB expect and what their managed rotation understands. Leave
`SecretStringTemplate` empty to store a bare string instead.

`ExcludeCharacters` defaults to the set that breaks shell quoting, JDBC
connection URLs, and RDS master passwords: `"@/\'`$&;|<>()[]{}`. A slightly
smaller alphabet at 32 characters is not a meaningful loss of entropy; a
password that breaks your connection string at 3am is a meaningful outage.

## Encryption

The default is the free AWS-managed `aws/secretsmanager` key. You need a
customer-managed key (`KmsKeyId`, from `foundation/kms-key`) for exactly one
thing: **cross-account access**. AWS-managed keys cannot be shared, so a resource
policy granting another account will authorise and then fail at decrypt.

## Deletion

`DeletionPolicy: Retain`, and `RecoveryWindowInDays` defaults to 30. AWS removed
the zero-day option from this API because deleting a database password by
accident turned out to be common. Deleting the stack leaves the secret behind;
delete it deliberately when you mean to.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
