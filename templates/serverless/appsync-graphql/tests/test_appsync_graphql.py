"""Assertions for serverless/appsync-graphql."""

from __future__ import annotations


def test_schema_is_loaded_from_s3_not_a_parameter(template) -> None:
    """CloudFormation parameters cap at 4096 characters.

    Any real GraphQL schema exceeds that, so an inline schema parameter would
    work in the example and fail on the first real API.
    """
    assert "SchemaS3Location" in template.required_parameters
    assert template.prop("Schema", "DefinitionS3Location") == {"Ref": "SchemaS3Location"}
    assert not template.has_prop("Schema", "Definition")


def test_cognito_default_action_denies(template) -> None:
    config = template.prop("Api", "UserPoolConfig")["Fn::If"][1]
    assert config["DefaultAction"] == "DENY", (
        "ALLOW would pass a request with a valid token through to a field the "
        "schema does not authorise, unauthenticated."
    )


def test_auth_config_blocks_are_mutually_exclusive(template) -> None:
    """Supplying both a user pool and an OIDC issuer config is rejected."""
    assert template.prop("Api", "UserPoolConfig")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert template.prop("Api", "OpenIDConnectConfig")["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_resolvers_wait_for_the_schema(template) -> None:
    """A resolver attached before the schema exists fails with "No field named X"."""
    for resolver in ("QueryResolver", "MutationResolver"):
        assert template.resource(resolver).get("DependsOn") == "Schema"


def test_resolvers_require_both_a_data_source_and_a_field_name(template) -> None:
    for condition in ("HasQueryResolver", "HasMutationResolver"):
        assert "Fn::And" in template.conditions[condition], (
            f"{condition} must require the Lambda ARN as well as the field name; "
            "a resolver with no data source is rejected at deploy time."
        )


def test_data_source_role_can_only_invoke_the_one_function(template) -> None:
    statement = template.prop("DataSourceRole", "Policies.0.PolicyDocument.Statement.0")
    assert statement["Action"] == "lambda:InvokeFunction"
    assert statement["Resource"] == {"Ref": "LambdaFunctionArn"}


def test_service_roles_are_scoped_to_this_account(template) -> None:
    for role in ("LoggingRole", "DataSourceRole"):
        condition = template.prop(role, "AssumeRolePolicyDocument.Statement.0.Condition")
        assert condition["StringEquals"]["aws:SourceAccount"] == {"Ref": "AWS::AccountId"}


def test_field_logging_defaults_to_errors_only(template) -> None:
    assert template.default("FieldLogLevel") == "ERROR", (
        "ALL logs every request and response including field values — expensive "
        "and PII-laden in production."
    )
    assert template.prop("Api", "LogConfig.ExcludeVerboseContent") is True


def test_log_group_matches_the_path_appsync_actually_writes_to(template) -> None:
    """A group at any other path receives nothing, and AppSync creates its own
    with infinite retention."""
    assert template.prop("LogGroup", "LogGroupName") == {
        "Fn::Sub": "/aws/appsync/apis/${Api.ApiId}"
    }
    assert template.prop("LogGroup", "RetentionInDays") == {"Ref": "LogRetentionDays"}


def test_tracing_is_on(template) -> None:
    assert template.prop("Api", "XrayEnabled") is True
