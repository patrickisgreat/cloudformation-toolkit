"""Assertions for serverless/lambda-function."""

from __future__ import annotations


def test_log_group_is_declared_and_ordered_before_the_function(template) -> None:
    """Lambda creates /aws/lambda/<name> implicitly with infinite retention.

    That implicit group is not owned by the stack, so a later attempt to declare
    it fails with "log group already exists". Declaring it and pointing the
    function at it avoids both the unbounded cost and the conflict — and the Ref
    in LoggingConfig is what orders the two, so no DependsOn is needed.
    """
    assert template.prop("LogGroup", "LogGroupName") == {
        "Fn::Sub": "/aws/lambda/${NamePrefix}-${Environment}-${FunctionSuffix}"
    }
    assert template.prop("LogGroup", "RetentionInDays") == {"Ref": "LogRetentionDays"}
    assert template.prop("Function", "LoggingConfig.LogGroup") == {"Ref": "LogGroup"}
    assert template.deletion_policy("LogGroup") == "Retain"


def test_vpc_attachment_swaps_in_the_eni_capable_managed_policy(template) -> None:
    """Without ENI permissions a VPC-attached function times out with no logs."""
    policies = template.prop("ExecutionRole", "ManagedPolicyArns")
    assert policies[0] == {
        "Fn::If": [
            "HasVpcConfig",
            {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"},
            {"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"},
        ]
    }


def test_vpc_config_is_absent_by_default(template) -> None:
    assert template.prop("Function", "VpcConfig")["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_zip_only_properties_disappear_for_image_packages(template) -> None:
    """Runtime and Handler on an Image package are rejected at deploy time."""
    for prop in ("Runtime", "Handler"):
        assert template.prop("Function", prop)["Fn::If"][1] == {"Ref": "AWS::NoValue"}
    code = template.prop("Function", "Code")
    assert code["Fn::If"][1] == {"ImageUri": {"Ref": "ImageUri"}}
    assert code["Fn::If"][2] == {"S3Bucket": {"Ref": "CodeS3Bucket"}, "S3Key": {"Ref": "CodeS3Key"}}


def test_reserved_concurrency_sentinel_is_minus_one_not_zero(template) -> None:
    """Zero is a real value that disables the function, so it cannot mean unset."""
    assert template.default("ReservedConcurrency") == -1
    assert template.param("ReservedConcurrency")["MinValue"] == -1
    assert template.prop("Function", "ReservedConcurrentExecutions") == {
        "Fn::If": ["HasReservedConcurrency", {"Ref": "ReservedConcurrency"}, {"Ref": "AWS::NoValue"}]
    }


def test_arm64_is_the_default_architecture(template) -> None:
    assert template.default("Architecture") == "arm64", (
        "Graviton is ~20% cheaper per GB-second and usually faster; x86_64 is "
        "the fallback for dependencies with no arm64 build."
    )


def test_failure_destination_grants_are_scoped_to_that_destination(template) -> None:
    statement = template.prop("ExecutionRole", "Policies.0.PolicyDocument.Statement.1")["Fn::If"][1]
    assert statement["Resource"] == {"Ref": "FailureDestinationArn"}
    assert set(statement["Action"]) == {"sqs:SendMessage", "sns:Publish"}


def test_async_retries_are_bounded_and_land_somewhere(template) -> None:
    assert template.prop("AsyncConfig", "MaximumRetryAttempts") == 2
    assert template.prop("AsyncConfig", "DestinationConfig.OnFailure.Destination") == {
        "Ref": "FailureDestinationArn"
    }, (
        "Without a destination, an async invocation that exhausts its retries is "
        "gone — a log line is all that remains of the event."
    )


def test_tracing_is_on_by_default(template) -> None:
    assert template.default("TracingMode") == "Active"


def test_environment_always_carries_the_environment_name(template) -> None:
    variables = template.prop("Function", "Environment.Variables")
    assert variables["ENVIRONMENT"] == {"Ref": "Environment"}
