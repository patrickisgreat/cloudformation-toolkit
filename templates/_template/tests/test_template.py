"""Starter test suite. A template scaffolded with `cfn new` is born tested.

Four categories, in rough order of value — see docs/TESTING.md:

1. Secure defaults — the *default* parameter set produces the safe configuration
2. Conditional wiring — optional resources appear and disappear with their toggle
3. Pass-through — a supplied value reaches the resource unchanged
4. Interface — the parameters and outputs a caller depends on still exist

Write assertion messages for someone who just broke the assertion and does not
know why the default was chosen. "Must be 30" is useless; "unset retention keeps
logs forever and bills forever" tells them what they are about to change.
"""

from __future__ import annotations


# 1. Secure defaults -----------------------------------------------------------

def test_logs_have_a_retention_by_default(template) -> None:
    assert template.default("LogRetentionDays") == 30, (
        "Log groups must default to a bounded retention — an unset RetentionInDays "
        "keeps logs forever and bills forever."
    )
    assert template.prop("LogGroup", "RetentionInDays") == {"Ref": "LogRetentionDays"}, (
        "The retention parameter must actually reach the log group."
    )


def test_logs_survive_a_failed_rollback(template) -> None:
    assert template.deletion_policy("LogGroup") == "Retain", (
        "Logs are what you read to understand a failed deploy. Deleting them as "
        "part of the rollback removes the evidence."
    )


# 2. Conditional wiring --------------------------------------------------------

def test_alarm_topic_is_conditional(template) -> None:
    assert template.condition_on("AlarmTopic") == "ShouldCreateAlarmTopic", (
        "The alarm topic must be guarded by its toggle — CloudFormation Conditions "
        "are how this library does Terraform's `count = 0`."
    )
    assert template.outputs["AlarmTopicArn"].get("Condition") == "ShouldCreateAlarmTopic", (
        "An output referencing a conditional resource must carry the same "
        "Condition, or the stack fails to create when the toggle is off."
    )


# 3. Pass-through --------------------------------------------------------------

def test_names_derive_from_the_name_prefix(template) -> None:
    assert template.prop("AlarmTopic", "TopicName") == {"Fn::Sub": "${NamePrefix}-alarms"}, (
        "Physical names must derive from NamePrefix so two environments can run "
        "the same template in one account without colliding."
    )


# 4. Interface -----------------------------------------------------------------

def test_name_prefix_is_the_only_required_parameter(template) -> None:
    assert template.required_parameters == ["NamePrefix"], (
        "Everything except the name should have a defensible default, so the "
        "template deploys with one parameter."
    )
