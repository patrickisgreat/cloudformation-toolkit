"""Assertions for containers/ecs-cluster."""

from __future__ import annotations


# --- capacity strategy -------------------------------------------------------

def test_spot_is_opt_in(template) -> None:
    assert template.default("SpotWeight") == 0, (
        "Fargate Spot is ~70% cheaper and reclaimable with two minutes' notice. "
        "That trade is fine for a stateless service and wrong for a queue "
        "consumer mid-batch, so it must be a deliberate choice rather than a "
        "default someone inherits."
    )


def test_on_demand_base_guarantees_a_surviving_task(template) -> None:
    assert template.default("OnDemandBaseCount") == 1, (
        "Base is the interruption floor — tasks placed on on-demand before any "
        "weight applies. A default of 0 means a Spot reclamation event can take "
        "every task at once."
    )
    strategy = template.prop("Cluster", "DefaultCapacityProviderStrategy")
    assert strategy[0]["CapacityProvider"] == "FARGATE"
    assert strategy[0]["Base"] == {"Ref": "OnDemandBaseCount"}


def test_spot_provider_never_carries_the_base(template) -> None:
    """Only one provider in a strategy may set a non-zero Base, and it must be
    the on-demand one — a Base on Spot would place the guaranteed tasks on
    exactly the capacity that can be reclaimed."""
    spot = template.prop("Cluster", "DefaultCapacityProviderStrategy")[1]["Fn::If"][1]
    assert spot["CapacityProvider"] == "FARGATE_SPOT"
    assert spot["Base"] == 0


def test_both_providers_are_registered_regardless_of_weights(template) -> None:
    assert template.prop("Cluster", "CapacityProviders") == ["FARGATE", "FARGATE_SPOT"], (
        "Registering both up front makes moving a service onto Spot a parameter "
        "change instead of a cluster rebuild."
    )


def test_spot_entry_disappears_when_weight_is_zero(template) -> None:
    entry = template.prop("Cluster", "DefaultCapacityProviderStrategy")[1]
    assert entry["Fn::If"][0] == "ShouldUseSpot"
    assert entry["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
        "A strategy entry with weight 0 is accepted but confusing in the console; "
        "removing it entirely is clearer."
    )


# --- ECS Exec auditing -------------------------------------------------------

def test_exec_sessions_are_logged_by_default(template) -> None:
    assert template.default("EnableExecuteCommandLogging") == "true", (
        "ECS Exec is an interactive shell inside a running production container. "
        "Without the log group there is no record of what was run."
    )
    assert template.prop("Cluster", "Configuration.ExecuteCommandConfiguration.Logging") == {
        "Fn::If": ["ShouldLogExecSessions", "OVERRIDE", "DEFAULT"]
    }


def test_exec_audit_log_outlives_the_stack(template) -> None:
    assert template.deletion_policy("ExecuteCommandLogGroup") == "Retain"
    assert template.default("LogRetentionDays") == 90, (
        "An audit trail wants a longer retention than an application log; 90 days "
        "covers a typical incident review window."
    )


# --- observability -----------------------------------------------------------

def test_container_insights_is_on_but_not_at_the_most_expensive_tier(template) -> None:
    assert template.default("ContainerInsights") == "enabled", (
        "`enhanced` adds per-container detail and costs meaningfully more on a "
        "large cluster; it should be a deliberate upgrade, not the default."
    )
    assert "disabled" in template.allowed_values("ContainerInsights")


# --- conditional wiring ------------------------------------------------------

def test_service_connect_namespace_is_opt_in_and_needs_a_vpc(template) -> None:
    assert template.default("CreateServiceConnectNamespace") == "false", (
        "With one service there is nothing to connect to, and an unused namespace "
        "blocks deletion of the VPC it is attached to."
    )
    assert template.condition_on("ServiceConnectNamespace") == "ShouldCreateNamespace"
    assert template.prop("ServiceConnectNamespace", "Vpc") == {"Ref": "VpcId"}


def test_conditional_outputs_carry_their_conditions(template) -> None:
    for name, condition in (
        ("ServiceConnectNamespaceArn", "ShouldCreateNamespace"),
        ("ServiceConnectNamespaceName", "ShouldCreateNamespace"),
        ("ExecuteCommandLogGroupName", "ShouldLogExecSessions"),
    ):
        assert template.outputs[name].get("Condition") == condition, (
            f"{name} references a conditional resource; without the same "
            "Condition the stack fails to create when the toggle is off."
        )


# --- interface ---------------------------------------------------------------

def test_cluster_name_is_unique_per_environment(template) -> None:
    assert template.prop("Cluster", "ClusterName") == {"Fn::Sub": "${NamePrefix}-${Environment}"}, (
        "Cluster names are account- and region-scoped, so dev and prod in one "
        "account must not collide."
    )
    assert template.outputs["ClusterName"]["Value"] == {"Ref": "Cluster"}
    assert template.outputs["ClusterArn"]["Value"] == {"Fn::GetAtt": ["Cluster", "Arn"]}
