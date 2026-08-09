"""Assertions for data/firehose-to-s3."""

from __future__ import annotations


def _s3(template) -> dict:
    return template.prop("DeliveryStream", "ExtendedS3DestinationConfiguration")


def test_partitions_are_hive_style(template) -> None:
    """Glue crawlers and Athena partition projection need key=value segments.

    Firehose's own default layout is bare numbers, which neither recognises
    without a custom classifier — an expensive thing to discover after a month
    of data has landed.
    """
    prefix = _s3(template)["Prefix"]["Fn::Sub"]
    for segment in ("year=!{timestamp:yyyy}", "month=!{timestamp:MM}", "day=!{timestamp:dd}"):
        assert segment in prefix, f"partition prefix must contain {segment}"
    assert prefix.endswith("/"), "a prefix without a trailing slash concatenates into the key"


def test_errors_land_outside_the_table_prefix(template) -> None:
    """An error object inside the partition tree is a malformed row in every
    query against that table."""
    error_prefix = _s3(template)["ErrorOutputPrefix"]["Fn::Sub"]
    assert error_prefix.startswith("errors/")
    assert "!{firehose:error-output-type}" in error_prefix, (
        "splitting by error type is what lets you tell a delivery failure from a "
        "transformation failure"
    )


def test_delivery_errors_are_logged(template) -> None:
    logging = _s3(template)["CloudWatchLoggingOptions"]
    assert logging["Enabled"] is True, (
        "Without this, a delivery stream that is failing every record looks "
        "identical to one receiving no traffic."
    )
    assert logging["LogGroupName"] == {"Ref": "LogGroup"}


def test_kinesis_permissions_appear_only_with_a_kinesis_source(template) -> None:
    statement = template.prop("DeliveryRole", "Policies.0.PolicyDocument.Statement.2")
    assert statement["Fn::If"][0] == "HasKinesisSource"
    assert statement["Fn::If"][1]["Resource"] == {"Ref": "SourceStreamArn"}
    assert statement["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_source_configuration_matches_the_stream_type(template) -> None:
    assert template.prop("DeliveryStream", "DeliveryStreamType") == {
        "Fn::If": ["HasKinesisSource", "KinesisStreamAsSource", "DirectPut"]
    }
    assert template.prop("DeliveryStream", "KinesisStreamSourceConfiguration")["Fn::If"][2] == {
        "Ref": "AWS::NoValue"
    }, "a source configuration on a DirectPut stream is rejected"


def test_s3_permissions_cover_bucket_and_objects(template) -> None:
    statement = template.prop("DeliveryRole", "Policies.0.PolicyDocument.Statement.0")
    assert statement["Resource"] == [
        {"Ref": "DestinationBucketArn"},
        {"Fn::Sub": "${DestinationBucketArn}/*"},
    ], (
        "Firehose needs the bucket ARN for ListBucket and the object ARN for "
        "PutObject; one without the other fails at delivery, not at deploy."
    )
    assert "s3:AbortMultipartUpload" in statement["Action"]


def test_assume_role_uses_an_external_id(template) -> None:
    condition = template.prop("DeliveryRole", "AssumeRolePolicyDocument.Statement.0.Condition")
    assert condition["StringEquals"]["sts:ExternalId"] == {"Ref": "AWS::AccountId"}


def test_compression_defaults_to_a_format_athena_can_split(template) -> None:
    assert template.default("CompressionFormat") == "GZIP"
    assert _s3(template)["CompressionFormat"] == {"Ref": "CompressionFormat"}


def test_buffering_defaults_favour_queryable_file_sizes(template) -> None:
    assert template.default("BufferSizeMb") == 64, (
        "A lake of thousands of tiny objects spends most of its query time on S3 "
        "list and open calls rather than scanning."
    )
    assert template.default("BufferIntervalSeconds") == 300
