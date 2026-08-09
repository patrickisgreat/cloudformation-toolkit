"""Assertions for containers/fargate-service — the flagship template."""

from __future__ import annotations

import json

import pytest


def _container(template) -> dict:
    return template.prop("TaskDefinition", "ContainerDefinitions.0")


# --- IAM separation ----------------------------------------------------------

def test_execution_and_task_roles_are_distinct(template) -> None:
    """Merging them hands the application every secret the task references.

    The execution role is the ECS agent's identity and reads secrets before the
    container starts. The task role is the application's. Collapsing them defeats
    the point of secret injection entirely.
    """
    assert template.resource_type("ExecutionRole") == "AWS::IAM::Role"
    assert template.resource_type("TaskRole") == "AWS::IAM::Role"
    assert template.prop("TaskDefinition", "ExecutionRoleArn") == {"Fn::GetAtt": ["ExecutionRole", "Arn"]}
    assert template.prop("TaskDefinition", "TaskRoleArn") == {"Fn::GetAtt": ["TaskRole", "Arn"]}


def test_execution_role_secret_access_is_scoped_to_the_injected_secrets(template) -> None:
    policy = template.prop("ExecutionRole", "Policies.0")["Fn::If"][1]
    statement = policy["PolicyDocument"]["Statement"][0]
    assert statement["Resource"] == [
        {"Fn::If": ["HasSecret1", {"Ref": "Secret1Arn"}, {"Ref": "AWS::NoValue"}]},
        {"Fn::If": ["HasSecret2", {"Ref": "Secret2Arn"}, {"Ref": "AWS::NoValue"}]},
    ], (
        "The execution role must read exactly the secrets this task definition "
        "injects, not every secret in the account."
    )


def test_both_roles_are_confused_deputy_protected(template) -> None:
    for role in ("ExecutionRole", "TaskRole"):
        statement = template.prop(role, "AssumeRolePolicyDocument.Statement.0")
        assert statement["Principal"]["Service"] == "ecs-tasks.amazonaws.com"
        assert statement["Condition"]["StringEquals"]["aws:SourceAccount"] == {"Ref": "AWS::AccountId"}, (
            f"{role} must scope the ECS service principal to this account."
        )


def test_task_role_carries_exec_permissions_not_the_execution_role(template) -> None:
    """ECS Exec opens an SSM channel from inside the task, so it is the task's
    identity that needs the permission — a very common misplacement."""
    statement = template.prop("TaskRole", "Policies.0.PolicyDocument.Statement.0")
    assert set(statement["Action"]) == {
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
    }


# --- secrets -----------------------------------------------------------------

def test_secret_value_never_appears_in_the_task_definition(template) -> None:
    secrets = _container(template)["Secrets"]["Fn::If"][1]
    entry = secrets[0]["Fn::If"][1]
    assert entry["Name"] == {"Ref": "Secret1Name"}
    assert entry["ValueFrom"] == {
        "Fn::If": [
            "HasSecret1JsonKey",
            {"Fn::Sub": "${Secret1Arn}:${Secret1JsonKey}::"},
            {"Ref": "Secret1Arn"},
        ]
    }, (
        "ValueFrom carries the ':key::' suffix while IAM needs the bare ARN. "
        "Conflating them produces a task that will not start, with an "
        "AccessDenied naming a resource that looks correct."
    )


def test_no_parameter_invites_a_plaintext_credential(template) -> None:
    for name in template.parameters:
        assert not name.lower().endswith("password"), (
            f"{name} would put a credential in the change set. Use the secret slots."
        )


# --- network isolation -------------------------------------------------------

def test_tasks_only_admit_the_load_balancer(template) -> None:
    ingress = template.prop("TaskSecurityGroup", "SecurityGroupIngress")["Fn::If"][1][0]
    assert ingress["SourceSecurityGroupId"] == {"Ref": "AlbSecurityGroupId"}, (
        "Tasks must be reachable through the load balancer only. A CIDR-based "
        "rule here would expose them to the whole VPC."
    )
    assert ingress["FromPort"] == {"Ref": "ContainerPort"}
    assert ingress["Description"]


def test_worker_mode_opens_no_ingress_at_all(template) -> None:
    assert template.prop("TaskSecurityGroup", "SecurityGroupIngress")["Fn::If"][2] == {
        "Ref": "AWS::NoValue"
    }, "A queue consumer has no inbound traffic and should have no inbound rule."


def test_tasks_do_not_get_public_addresses_by_default(template) -> None:
    assert template.default("AssignPublicIp") == "DISABLED"


# --- deployment safety -------------------------------------------------------

def test_circuit_breaker_rolls_back(template) -> None:
    breaker = template.prop("Service", "DeploymentConfiguration.DeploymentCircuitBreaker")
    assert breaker == {"Enable": True, "Rollback": True}, (
        "Without it a broken image rolls forward: ECS keeps replacing tasks that "
        "crash on start, the deploy hangs for hours, and capacity drains as "
        "healthy old tasks are stopped."
    )


def test_deploys_do_not_dip_below_full_capacity(template) -> None:
    config = template.prop("Service", "DeploymentConfiguration")
    assert config["MinimumHealthyPercent"] == 100
    assert config["MaximumPercent"] == 200


def test_deregistration_delay_is_shorter_than_the_aws_default(template) -> None:
    assert template.default("DeregistrationDelaySeconds") == 30, (
        "AWS defaults to 300s, which adds five minutes to every deploy for no "
        "benefit on a normal API."
    )


def test_stop_timeout_allows_graceful_shutdown(template) -> None:
    assert template.default("StopTimeoutSeconds") == 30
    assert _container(template)["StopTimeout"] == {"Ref": "StopTimeoutSeconds"}


def test_service_ordering_survives_worker_mode(template) -> None:
    """The service must be created after the listener rule when one exists.

    ECS refuses to create a service whose target group has no associated load
    balancer, and the rule is what associates it. `DependsOn` cannot be
    conditional, so the ordering edge is created by referencing the rule inside
    an Fn::If — which only applies on the branch where the rule exists.
    """
    assert "DependsOn" not in template.resource("Service"), (
        "An unconditional DependsOn on the conditional ListenerRule makes the "
        "template invalid for a worker service."
    )
    tags = template.prop("Service", "Tags")
    assert any(
        tag.get("Value") == {"Fn::If": ["AttachedToLoadBalancer", {"Ref": "ListenerRule"}, "none"]}
        for tag in tags
    ), "the ordering edge to ListenerRule has been lost"


# --- load balancer attachment ------------------------------------------------

def test_load_balancer_wiring_is_all_conditional(template) -> None:
    """One parameter turns an HTTP service into a worker."""
    for logical_id in ("TargetGroup", "ListenerRule"):
        assert template.condition_on(logical_id) == "AttachedToLoadBalancer"
    for prop in ("LoadBalancers", "HealthCheckGracePeriodSeconds"):
        assert template.prop("Service", prop)["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_grpc_switches_the_health_check_matcher(template) -> None:
    """A GRPC target group with an HttpCode matcher is rejected at deploy time."""
    matcher = template.prop("TargetGroup", "Matcher")
    assert matcher == {
        "Fn::If": ["IsGrpc", {"GrpcCode": "0"}, {"HttpCode": {"Ref": "HealthCheckMatcher"}}]
    }
    assert _container(template)["PortMappings"][0]["AppProtocol"] == {
        "Fn::If": ["IsGrpc", "grpc", "http"]
    }


def test_host_header_condition_is_optional(template) -> None:
    conditions = template.prop("ListenerRule", "Conditions")
    assert conditions[0]["Field"] == "path-pattern"
    assert conditions[1]["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
        "An empty host-header condition matches nothing, so it must be omitted "
        "rather than emptied."
    )


def test_health_check_grace_period_allows_a_slow_start(template) -> None:
    assert template.default("HealthCheckGracePeriodSeconds") == 60
    assert template.param("HealthCheckGracePeriodSeconds")["MaxValue"] >= 600, (
        "A JVM with a large heap, or a container that loads a model at startup, "
        "needs minutes. Too short a grace period produces an infinite "
        "kill-and-restart loop that looks exactly like a crash."
    )


# --- scaling -----------------------------------------------------------------

def test_cpu_scaling_is_always_on(template) -> None:
    assert template.condition_on("CpuScalingPolicy") is None
    spec = template.prop(
        "CpuScalingPolicy",
        "TargetTrackingScalingPolicyConfiguration.PredefinedMetricSpecification.PredefinedMetricType",
    )
    assert spec == "ECSServiceAverageCPUUtilization"
    assert template.default("TargetCpuUtilization") == 65


def test_memory_scaling_is_off_by_default(template) -> None:
    assert template.default("TargetMemoryUtilization") == 0, (
        "A garbage-collected runtime holds memory at a high-water mark that "
        "adding tasks never reduces, so memory scaling ratchets up and never "
        "comes back down."
    )
    assert template.condition_on("MemoryScalingPolicy") == "ScalesOnMemory"


def test_request_scaling_requires_both_load_balancer_facts(template) -> None:
    """The resource label needs the LB full name *and* the target group's."""
    assert template.condition_on("RequestScalingPolicy") == "ScalesOnRequests"
    label = template.prop(
        "RequestScalingPolicy",
        "TargetTrackingScalingPolicyConfiguration.PredefinedMetricSpecification.ResourceLabel",
    )
    assert label == {"Fn::Sub": "${LoadBalancerFullName}/${TargetGroup.TargetGroupFullName}"}
    assert len(template.conditions["ScalesOnRequests"]["Fn::And"]) == 3


def test_scale_in_is_slower_than_scale_out(template) -> None:
    assert template.default("ScaleInCooldownSeconds") > template.default("ScaleOutCooldownSeconds"), (
        "Scaling out too eagerly costs money; scaling in too eagerly costs "
        "availability. They are not symmetric."
    )


def test_minimum_capacity_survives_a_single_task_loss(template) -> None:
    assert template.default("MinCapacity") == 2
    assert template.default("DesiredCount") == 2


# --- logging -----------------------------------------------------------------

def test_log_driver_cannot_take_the_service_down(template) -> None:
    options = _container(template)["LogConfiguration"]["Options"]
    assert options["mode"] == "non-blocking", (
        "In blocking mode the awslogs driver fails the task when it cannot reach "
        "CloudWatch, turning a logging blip into an outage."
    )
    assert options["awslogs-group"] == {"Ref": "LogGroup"}


def test_logs_survive_a_failed_rollback(template) -> None:
    assert template.deletion_policy("LogGroup") == "Retain"


# --- interface ---------------------------------------------------------------

def test_standard_environment_variables_are_always_injected(template) -> None:
    env = _container(template)["Environment"]
    always = {e["Name"]: e["Value"] for e in env if isinstance(e, dict) and "Fn::If" not in e}
    assert always == {"ENVIRONMENT": {"Ref": "Environment"}, "PORT": {"Ref": "ContainerPort"}}, (
        "Every service in the library should read its environment and port the "
        "same way, whatever language it is written in."
    )


def test_optional_environment_slots_drop_out_cleanly(template) -> None:
    env = _container(template)["Environment"]
    optional = [e for e in env if isinstance(e, dict) and "Fn::If" in e]
    assert len(optional) == 4
    for entry in optional:
        assert entry["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_cluster_capacity_strategy_is_inherited_by_default(template) -> None:
    """Omitting both LaunchType and CapacityProviderStrategy is what makes a
    cluster-level Fargate Spot mix actually reach its services."""
    strategy = template.prop("Service", "CapacityProviderStrategy")
    assert strategy["Fn::If"][0] == "UsesClusterStrategy"
    assert strategy["Fn::If"][1] == {"Ref": "AWS::NoValue"}
    assert not template.has_prop("Service", "LaunchType"), (
        "Setting LaunchType overrides the cluster default strategy entirely."
    )


@pytest.mark.parametrize(
    "output",
    ["ServiceName", "TaskRoleArn", "TaskSecurityGroupId", "LogGroupName", "TargetGroupArn"],
)
def test_composition_outputs_exist(template, output: str) -> None:
    assert output in template.outputs


def test_image_uri_is_required(template) -> None:
    assert "ImageUri" in template.required_parameters
    assert "latest" not in json.dumps(template.param("ImageUri").get("Default", "")), (
        "There must be no default image — a default is how a stack silently "
        "deploys something nobody chose."
    )
