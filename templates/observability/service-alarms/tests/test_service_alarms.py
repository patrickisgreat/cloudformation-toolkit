"""Assertions for observability/service-alarms."""

from __future__ import annotations

import pytest

ALARMS = [
    "Http5xxAlarm",
    "UnhealthyTargetsAlarm",
    "LatencyAlarm",
    "CpuAlarm",
    "MemoryAlarm",
    "DeadLetterQueueAlarm",
]


@pytest.mark.parametrize("alarm", ALARMS)
def test_every_alarm_notifies_and_announces_recovery(template, alarm: str) -> None:
    assert template.prop(alarm, "AlarmActions") == [{"Ref": "AlarmTopicArn"}]
    assert template.prop(alarm, "OKActions") == [{"Ref": "AlarmTopicArn"}], (
        "An alarm you are never told cleared is one you keep investigating."
    )


@pytest.mark.parametrize("alarm", ALARMS)
def test_every_alarm_says_what_to_do(template, alarm: str) -> None:
    """The description is what the person woken up reads first."""
    description = template.prop(alarm, "AlarmDescription")
    assert len(description.split()) >= 10, f"{alarm} needs an actionable description"


def test_idle_services_do_not_page(template) -> None:
    """A service with no traffic emits no datapoints for these metrics."""
    for alarm in ("Http5xxAlarm", "LatencyAlarm", "CpuAlarm", "MemoryAlarm"):
        assert template.prop(alarm, "TreatMissingData") == "notBreaching", (
            f"{alarm} breaching on missing data pages nightly for an idle "
            "environment, which teaches people to ignore it."
        )


def test_missing_target_health_data_is_itself_an_alarm(template) -> None:
    assert template.prop("UnhealthyTargetsAlarm", "TreatMissingData") == "breaching", (
        "No data from the target group means it is not reporting at all."
    )


def test_latency_alarms_on_the_tail_not_the_average(template) -> None:
    assert template.prop("LatencyAlarm", "ExtendedStatistic") == "p99", (
        "A service can sit at a 120ms average with a 9-second p99 and look "
        "healthy on an average-based alarm."
    )
    assert not template.has_prop("LatencyAlarm", "Statistic"), (
        "Statistic and ExtendedStatistic are mutually exclusive."
    )


def test_cpu_threshold_sits_above_the_autoscaling_target(template) -> None:
    assert template.default("CpuThresholdPercent") == 85, (
        "containers/fargate-service targets 65% CPU. Alarming at the level the "
        "scaler holds pages every time autoscaling works correctly."
    )


def test_each_alarm_group_needs_both_of_its_dimensions(template) -> None:
    """A dimension pair with one half empty matches no metric and never fires."""
    for condition in ("WatchesLoadBalancer", "WatchesEcsService"):
        assert "Fn::And" in template.conditions[condition]


def test_dead_letter_alarm_fires_on_a_single_message(template) -> None:
    assert template.default("DeadLetterMessageThreshold") == 1, (
        "One message in a DLQ is already a failure that needs looking at."
    )
    assert template.prop("DeadLetterQueueAlarm", "ComparisonOperator") == "GreaterThanOrEqualToThreshold"
