"""Assertions for observability/budget-alarms."""

from __future__ import annotations

NOTIFICATIONS = "NotificationsWithSubscribers"


def _notification(template, index: int) -> dict:
    return template.prop("MonthlyBudget", f"{NOTIFICATIONS}.{index}.Notification")


# 1. Secure defaults -----------------------------------------------------------


def test_thresholds_warn_before_the_budget_is_spent(template) -> None:
    assert template.default("ActualThresholdPercent1") == 50
    assert template.default("ActualThresholdPercent2") == 80
    assert template.default("ForecastThresholdPercent") == 100, (
        "The defaults are two warnings on the way up and a forecast at the line; "
        "a single threshold at 100% tells you about the bill after it is spent."
    )


def test_two_actual_and_one_forecast_notification(template) -> None:
    kinds = [_notification(template, i)["NotificationType"] for i in range(3)]
    assert kinds == ["ACTUAL", "ACTUAL", "FORECASTED"], (
        "The forecast notification is the early one - it fires days before "
        "actual spend reaches the line."
    )
    for i in range(3):
        assert _notification(template, i)["ThresholdType"] == "PERCENTAGE"
        assert _notification(template, i)["ComparisonOperator"] == "GREATER_THAN"


def test_budget_is_a_monthly_cost_budget_in_usd(template) -> None:
    budget = template.prop("MonthlyBudget", "Budget")
    assert budget["BudgetType"] == "COST"
    assert budget["TimeUnit"] == "MONTHLY"
    assert budget["BudgetLimit"] == {"Amount": {"Ref": "MonthlyBudgetUsd"}, "Unit": "USD"}


def test_anomaly_detection_is_on_by_default_because_it_is_free(template) -> None:
    assert template.default("EnableAnomalyDetection") == "true"
    assert template.prop("AnomalyMonitor", "MonitorDimension") == "SERVICE"
    assert template.prop("AnomalySubscription", "Frequency") == "DAILY", (
        "DAILY is the only frequency that delivers by email; IMMEDIATE requires SNS."
    )


# 2. Conditional wiring --------------------------------------------------------


def test_anomaly_resources_follow_their_toggle(template) -> None:
    assert template.condition_on("AnomalyMonitor") == "ShouldDetectAnomalies"
    assert template.condition_on("AnomalySubscription") == "ShouldDetectAnomalies"
    assert template.outputs["AnomalyMonitorArn"].get("Condition") == "ShouldDetectAnomalies", (
        "An output referencing a conditional resource must carry the same "
        "Condition, or the stack fails to create when the toggle is off."
    )


def test_sns_subscriber_drops_out_when_no_topic_is_given(template) -> None:
    for i in range(3):
        subscribers = template.prop("MonthlyBudget", f"{NOTIFICATIONS}.{i}.Subscribers")
        assert subscribers[0] == {"SubscriptionType": "EMAIL", "Address": {"Ref": "AlertEmail"}}, (
            "Email is the subscriber that always exists: Budgets emails directly, "
            "with no confirmation step."
        )
        assert subscribers[1]["Fn::If"][0] == "HasAlarmTopic"
        assert subscribers[1]["Fn::If"][2] == {"Ref": "AWS::NoValue"}


# 3. Pass-through --------------------------------------------------------------


def test_thresholds_reach_their_notifications(template) -> None:
    assert _notification(template, 0)["Threshold"] == {"Ref": "ActualThresholdPercent1"}
    assert _notification(template, 1)["Threshold"] == {"Ref": "ActualThresholdPercent2"}
    assert _notification(template, 2)["Threshold"] == {"Ref": "ForecastThresholdPercent"}


def test_anomaly_threshold_is_an_absolute_dollar_impact(template) -> None:
    expression = template.prop("AnomalySubscription", "ThresholdExpression")["Fn::Sub"]
    assert "ANOMALY_TOTAL_IMPACT_ABSOLUTE" in expression
    assert "${AnomalyThresholdUsd}" in expression, (
        "A percentage threshold fires on tiny services doubling from nothing; "
        "an absolute dollar impact is what a bill-payer cares about."
    )


def test_names_derive_from_the_name_prefix(template) -> None:
    assert template.prop("MonthlyBudget", "Budget.BudgetName") == {
        "Fn::Sub": "${NamePrefix}-${Environment}-monthly"
    }
    assert template.prop("AnomalyMonitor", "MonitorName") == {
        "Fn::Sub": "${NamePrefix}-${Environment}-services"
    }


# 4. Interface -----------------------------------------------------------------


def test_only_a_name_and_an_email_are_required(template) -> None:
    assert sorted(template.required_parameters) == ["AlertEmail", "NamePrefix"], (
        "A budget must be deployable into a brand-new account with nothing else "
        "in it: no topic, no key, no VPC."
    )
