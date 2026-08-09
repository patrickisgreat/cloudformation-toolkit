# `serverless/appsync-graphql`

A managed GraphQL API: schema from S3, direct-Lambda resolvers, Cognito
authentication, field-level logging, and X-Ray.

**Status: beta.** The template is correct and lints clean, but AppSync's resolver
model does not fit a fixed-shape template as cleanly as the other services here
— see "The resolver limitation" below before adopting it.

## Usage

```bash
aws s3 cp schema.graphql s3://my-artifacts/graphql/schema-$(git rev-parse --short HEAD).graphql

./bin/cfn deploy serverless/appsync-graphql --env dev \
  --param SchemaS3Location=s3://my-artifacts/graphql/schema-abc1234.graphql \
  --param UserPoolId=us-east-1_aBcDeFgHi
```

## AppSync or a container?

| | AppSync | GraphQL server on `containers/fargate-service` |
|---|---|---|
| Subscriptions | Managed WebSockets, no state to run | You operate the pub/sub |
| Per-field authorisation | Declarative, in the schema | Your code |
| Resolver logic | Per field, in Lambda or VTL | One process, ordinary code |
| Local development | Hard | `docker run` |
| Portability | AWS-specific | Any container platform |

Choose AppSync for subscription-heavy, per-field-authorised APIs. Choose a
container running Apollo, gqlgen, Strawberry, or Hot Chocolate when you want your
resolvers to be ordinary code you can run on a laptop.

## The schema comes from S3

CloudFormation parameters cap at **4096 characters**, which any real schema
exceeds almost immediately. So `SchemaS3Location` takes an `s3://` URI; upload
the schema as part of your build and pass a versioned key.

## The resolver limitation

This template wires **one Query field and one Mutation field** to a Lambda data
source. That is not a design preference — CloudFormation cannot loop, so a
resolver per field means a resource per field, and a 40-field schema cannot be
expressed as a fixed template.

Realistic options for a full API:

- Point every field at one Lambda and route inside it (fewest resources, loses
  per-field metrics).
- Generate the resolver resources from your schema at build time and deploy the
  generated template.
- Use this template for the API, schema, auth, and logging, and manage resolvers
  with a nested stack per domain.

The template is honest about this rather than pretending a two-resolver API is
the general case.

## Authentication

`AMAZON_COGNITO_USER_POOLS` is the default and `DefaultAction` is `DENY` — a
valid token for a field the schema does not authorise is rejected, not passed
through unauthenticated.

`API_KEY` is **development only**: the key is a bearer token with no user
identity behind it, so nothing in your resolver can tell one caller from another.

Note there is no expiry parameter for the API key. `Expires` takes an absolute
epoch second, and CloudFormation has no date arithmetic — a relative "30 days"
parameter would silently bake in the date of the first deploy and then expire
without anyone touching the stack. Rotation is an out-of-band operation.

## Logging costs

`FieldLogLevel: ALL` logs every request and response, **including field values**.
That is genuinely useful while developing a schema and is both expensive and
PII-laden in production, which is why the default is `ERROR`.

The log group is declared at `/aws/appsync/apis/<apiId>` — the exact path AppSync
writes to — so retention is bounded. Left implicit, AppSync creates it with
infinite retention.

See [`examples/basic`](examples/basic) for a parameter set you can deploy as-is.

<!-- BEGIN_CFN_DOCS -->
<!-- END_CFN_DOCS -->
