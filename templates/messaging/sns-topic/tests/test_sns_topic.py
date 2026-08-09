"""Assertions for messaging/sns-topic."""

from __future__ import annotations


def test_topic_is_encrypted_by_default(template) -> None:
    """SNS has no managed-SSE toggle, so a key is the only way to get encryption.

    Defaulting to the AWS-managed alias makes it free and keyless rather than
    something a caller has to remember.
    """
    assert template.default("KmsKeyId") == "alias/aws/sns"
    assert template.prop("Topic", "KmsMasterKeyId") == {"Ref": "KmsKeyId"}


def test_sqs_subscription_uses_raw_delivery(template) -> None:
    assert template.prop("QueueSubscription", "RawMessageDelivery") is True, (
        "Without raw delivery the consumer receives the SNS envelope with the "
        "payload embedded as a JSON string, so every consumer parses twice."
    )


def test_sqs_subscription_is_a_separate_resource(template) -> None:
    """Inline topic subscriptions support neither FilterPolicy nor raw delivery."""
    assert template.resource_type("QueueSubscription") == "AWS::SNS::Subscription"
    assert template.condition_on("QueueSubscription") == "HasSqs"


def test_filter_policy_and_its_scope_appear_together(template) -> None:
    assert template.prop("QueueSubscription", "FilterPolicy")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert template.prop("QueueSubscription", "FilterPolicyScope") == {
        "Fn::If": ["HasFilterPolicy", "MessageAttributes", {"Ref": "AWS::NoValue"}]
    }, "a scope without a policy, or the reverse, is rejected"


def test_service_publish_grant_is_scoped_to_a_source_arn(template) -> None:
    statement = template.prop("TopicPolicy", "PolicyDocument.Statement.0")
    condition = statement["Condition"]
    assert condition["StringEquals"]["aws:SourceAccount"] == {"Ref": "AWS::AccountId"}
    assert condition["ArnLike"]["aws:SourceArn"] == {"Ref": "AllowPublishFromSourceArn"}, (
        "A service grant with no SourceArn condition lets any bucket or alarm in "
        "the account publish to this topic."
    )
    assert statement["Action"] == "sns:Publish"


def test_fifo_settings_are_omitted_for_standard_topics(template) -> None:
    for prop in ("FifoTopic", "ContentBasedDeduplication"):
        assert template.prop("Topic", prop)["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert template.prop("Topic", "TopicName")["Fn::If"][1] == {
        "Fn::Sub": "${NamePrefix}-${Environment}-${TopicSuffix}.fifo"
    }


def test_email_subscription_drops_out_when_unset(template) -> None:
    assert template.prop("Topic", "Subscription.0")["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_outputs_serve_alarm_actions_and_dimensions(template) -> None:
    assert template.outputs["TopicArn"]["Value"] == {"Ref": "Topic"}
    assert template.outputs["TopicName"]["Value"] == {"Fn::GetAtt": ["Topic", "TopicName"]}
