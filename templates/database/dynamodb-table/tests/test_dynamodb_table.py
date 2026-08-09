"""Assertions for database/dynamodb-table."""

from __future__ import annotations


def test_point_in_time_recovery_is_on_by_default(template) -> None:
    """PITR's window starts when you enable it — turning it on after a bad
    migration recovers nothing."""
    assert template.default("PointInTimeRecovery") == "true"
    assert template.prop("Table", "PointInTimeRecoverySpecification.PointInTimeRecoveryEnabled") == {
        "Ref": "PointInTimeRecovery"
    }


def test_encryption_is_always_declared(template) -> None:
    assert template.prop("Table", "SSESpecification.SSEEnabled") is True
    assert template.prop("Table", "SSESpecification.SSEType")["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
        "SSEType must be omitted for the AWS-owned key; supplying it without a "
        "KMS key is rejected."
    )


def test_table_survives_a_rollback(template) -> None:
    assert template.deletion_policy("Table") == "Retain"


def test_only_key_attributes_are_declared(template) -> None:
    """DynamoDB rejects an AttributeDefinition for a non-key attribute."""
    definitions = template.prop("Table", "AttributeDefinitions")
    assert definitions[0] == {
        "AttributeName": {"Ref": "PartitionKeyName"},
        "AttributeType": {"Ref": "PartitionKeyType"},
    }
    for entry in definitions[1:]:
        assert "Fn::If" in entry and entry["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
            "An attribute definition with no matching key is rejected, so every "
            "optional one must disappear rather than be empty."
        )


def test_sort_key_disappears_cleanly(template) -> None:
    assert template.prop("Table", "KeySchema.1")["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_index_sort_key_requires_the_index(template) -> None:
    assert "Fn::And" in template.conditions["HasIndexSortKey"], (
        "An index sort key without an index would emit an orphan attribute "
        "definition and fail the deploy."
    )


def test_index_projects_keys_only_by_default(template) -> None:
    assert template.default("IndexProjection") == "KEYS_ONLY", (
        "A GSI stores its own copy of projected attributes and consumes write "
        "capacity on every base-table write. ALL roughly doubles both."
    )


def test_provisioned_throughput_disappears_in_on_demand_mode(template) -> None:
    assert template.default("BillingMode") == "PAY_PER_REQUEST"
    assert template.prop("Table", "ProvisionedThroughput")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    index = template.prop("Table", "GlobalSecondaryIndexes")["Fn::If"][1][0]
    assert index["ProvisionedThroughput"]["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
        "A GSI carrying provisioned throughput on a PAY_PER_REQUEST table is "
        "rejected."
    )


def test_stream_and_ttl_are_opt_in_and_drop_out(template) -> None:
    assert template.default("StreamViewType") == "NONE"
    assert template.prop("Table", "StreamSpecification")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert template.prop("Table", "TimeToLiveSpecification")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert template.outputs["StreamArn"].get("Condition") == "HasStream", (
        "GetAtt StreamArn on a table with no stream fails the whole stack."
    )
