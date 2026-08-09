"""Assertions for messaging/sqs-queue."""

from __future__ import annotations


def test_a_dead_letter_queue_is_not_optional(template) -> None:
    """There is no parameter to disable the DLQ, and that is deliberate.

    A queue without one retries a poison message until retention expires and
    then drops it silently. That is data loss by design.
    """
    assert template.condition_on("DeadLetterQueue") is None
    assert template.prop("Queue", "RedrivePolicy") == {
        "deadLetterTargetArn": {"Fn::GetAtt": ["DeadLetterQueue", "Arn"]},
        "maxReceiveCount": {"Ref": "MaxReceiveCount"},
    }


def test_kms_and_managed_sse_are_never_both_present(template) -> None:
    """Setting SqsManagedSseEnabled: false alongside a key still errors.

    The API's conflict check fires on the argument being present at all, not on
    its value — so the false branch has to be AWS::NoValue, not `false`.
    """
    for queue in ("Queue", "DeadLetterQueue"):
        managed = template.prop(queue, "SqsManagedSseEnabled")
        assert managed == {"Fn::If": ["UsesKms", {"Ref": "AWS::NoValue"}, True]}
        kms = template.prop(queue, "KmsMasterKeyId")
        assert kms == {"Fn::If": ["UsesKms", {"Ref": "KmsKeyArn"}, {"Ref": "AWS::NoValue"}]}


def test_long_polling_is_on_at_the_maximum(template) -> None:
    assert template.default("ReceiveMessageWaitTimeSeconds") == 20, (
        "Short polling bills a request per empty receive, so an idle consumer "
        "at 0 pays to receive nothing and adds latency doing it."
    )


def test_fifo_naming_is_applied_to_both_queues(template) -> None:
    """A FIFO queue with a standard DLQ is rejected, and the error does not
    mention the .fifo suffix that is actually missing."""
    assert template.prop("Queue", "QueueName")["Fn::If"][1] == {
        "Fn::Sub": "${NamePrefix}-${Environment}-${QueueSuffix}.fifo"
    }
    assert template.prop("DeadLetterQueue", "QueueName")["Fn::If"][1] == {
        "Fn::Sub": "${NamePrefix}-${Environment}-${QueueSuffix}-dlq.fifo"
    }
    assert template.prop("DeadLetterQueue", "FifoQueue") == {
        "Fn::If": ["IsFifo", True, {"Ref": "AWS::NoValue"}]
    }


def test_fifo_only_settings_are_omitted_for_standard_queues(template) -> None:
    assert template.prop("Queue", "ContentBasedDeduplication") == {
        "Fn::If": ["IsFifo", {"Ref": "ContentBasedDeduplication"}, {"Ref": "AWS::NoValue"}]
    }, "ContentBasedDeduplication on a standard queue is rejected outright."


def test_dead_letter_queue_retains_longer_than_the_main_queue(template) -> None:
    assert template.default("DeadLetterRetentionSeconds") == 1209600
    assert template.default("DeadLetterRetentionSeconds") > template.default("MessageRetentionSeconds"), (
        "The DLQ is what you inspect after the incident, so it must outlive the "
        "queue that fed it."
    )


def test_both_queues_survive_a_rollback(template) -> None:
    for queue in ("Queue", "DeadLetterQueue"):
        assert template.deletion_policy(queue) == "Retain"


def test_outputs_include_names_for_alarm_dimensions(template) -> None:
    """CloudWatch alarms key on QueueName, not on the URL or ARN."""
    assert template.outputs["DeadLetterQueueName"]["Value"] == {
        "Fn::GetAtt": ["DeadLetterQueue", "QueueName"]
    }
    assert template.outputs["QueueUrl"]["Value"] == {"Ref": "Queue"}
