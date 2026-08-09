"""Assertions for data/kinesis-stream."""

from __future__ import annotations


def test_on_demand_is_the_default_capacity_mode(template) -> None:
    assert template.default("CapacityMode") == "ON_DEMAND", (
        "Provisioned mode requires predicting a shard count, and being wrong "
        "produces ProvisionedThroughputExceededException — which SDKs retry "
        "transparently, so the symptom is a growing backlog rather than an error."
    )


def test_shard_count_disappears_in_on_demand_mode(template) -> None:
    """ShardCount and ON_DEMAND are mutually exclusive; supplying both fails."""
    assert template.prop("Stream", "ShardCount") == {
        "Fn::If": ["IsProvisioned", {"Ref": "ShardCount"}, {"Ref": "AWS::NoValue"}]
    }
    assert template.prop("Stream", "StreamModeDetails.StreamMode") == {"Ref": "CapacityMode"}


def test_encryption_is_unconditional(template) -> None:
    encryption = template.prop("Stream", "StreamEncryption")
    assert encryption["EncryptionType"] == "KMS"
    assert template.default("KmsKeyId") == "alias/aws/kinesis", (
        "The AWS-managed key is free, so there is no reason to offer an "
        "unencrypted stream."
    )


def test_stream_survives_a_rollback(template) -> None:
    assert template.deletion_policy("Stream") == "Retain", (
        "A stream holds records no consumer has read yet."
    )


def test_retention_floor_matches_the_service(template) -> None:
    assert template.default("RetentionHours") == 24
    assert template.param("RetentionHours")["MinValue"] == 24, (
        "24 hours is the Kinesis minimum; a lower value is rejected at deploy."
    )
    assert template.param("RetentionHours")["MaxValue"] == 8760


def test_enhanced_fan_out_is_opt_in(template) -> None:
    assert template.condition_on("Consumer") == "HasEnhancedFanOut", (
        "Enhanced fan-out is billed hourly per shard, so it must be a deliberate "
        "choice rather than a default."
    )
    assert template.prop("Consumer", "StreamARN") == {"Fn::GetAtt": ["Stream", "Arn"]}


def test_outputs_serve_firehose_and_alarms(template) -> None:
    assert template.outputs["StreamArn"]["Value"] == {"Fn::GetAtt": ["Stream", "Arn"]}
    assert template.outputs["StreamName"]["Value"] == {"Ref": "Stream"}
    assert template.outputs["ConsumerArn"].get("Condition") == "HasEnhancedFanOut"
