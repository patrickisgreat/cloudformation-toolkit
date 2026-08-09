"""Assertions for ml/gpu-inference-service."""

from __future__ import annotations


def _container(template) -> dict:
    return template.prop("TaskDefinition", "ContainerDefinitions.0")


# --- cost posture ------------------------------------------------------------

def test_the_fleet_scales_to_zero_by_default(template) -> None:
    """The difference between a dev environment at $30/month and $730."""
    assert template.default("MinInstanceCount") == 0
    assert template.prop("AutoScalingGroup", "MinSize") == {"Ref": "MinInstanceCount"}
    assert template.prop("AutoScalingGroup", "DesiredCapacity") == {"Ref": "MinInstanceCount"}


def test_spot_is_opt_in(template) -> None:
    assert template.default("UseSpotInstances") == "false", (
        "For interactive serving, a Spot reclamation means a multi-minute model "
        "reload before the replacement can answer."
    )
    distribution = template.prop("AutoScalingGroup", "MixedInstancesPolicy.InstancesDistribution")
    assert distribution["OnDemandPercentageAboveBaseCapacity"] == {
        "Fn::If": ["UsesSpot", 0, 100]
    }


def test_max_instance_count_is_a_real_ceiling(template) -> None:
    assert template.prop("AutoScalingGroup", "MaxSize") == {"Ref": "MaxInstanceCount"}
    assert template.default("MaxInstanceCount") == 2


# --- the cluster-wide side effect --------------------------------------------

def test_fargate_providers_are_relisted_on_the_cluster(template) -> None:
    """ClusterCapacityProviderAssociations replaces the whole provider list.

    Omitting FARGATE and FARGATE_SPOT silently detaches every Fargate service on
    the cluster from its capacity — they keep reporting healthy and stop being
    able to place tasks.
    """
    providers = template.prop("ClusterProviders", "CapacityProviders")
    assert "FARGATE" in providers
    assert "FARGATE_SPOT" in providers
    assert {"Ref": "CapacityProvider"} in providers


def test_scale_in_cannot_kill_a_running_generation(template) -> None:
    assert template.prop("CapacityProvider", "AutoScalingGroupProvider.ManagedTerminationProtection") == "ENABLED"
    assert template.prop("AutoScalingGroup", "NewInstancesProtectedFromScaleIn") is True, (
        "The ASG must not fight the capacity provider's managed scaling."
    )


# --- startup correctness -----------------------------------------------------

def test_health_check_grace_period_covers_model_load(template) -> None:
    """Too short a grace period produces an endless kill-and-restart loop that
    looks exactly like a crash."""
    assert template.default("HealthCheckGracePeriodSeconds") == 900
    assert template.prop("Service", "HealthCheckGracePeriodSeconds") == {
        "Ref": "HealthCheckGracePeriodSeconds"
    }


def test_agent_timeouts_are_raised_for_large_pulls(template) -> None:
    user_data = template.prop("LaunchTemplate", "LaunchTemplateData.UserData")["Fn::Base64"]["Fn::Sub"]
    assert "ECS_ENABLE_GPU_SUPPORT=true" in user_data, (
        "Without GPU support in the agent config, a task with a GPU resource "
        "requirement never places."
    )
    assert "ECS_CONTAINER_START_TIMEOUT=15m" in user_data, (
        "Image pull plus model download exceeds the default, and the task is "
        "killed mid-download."
    )
    assert "ECS_CLUSTER=${ClusterName}" in user_data


def test_shared_memory_is_raised_for_the_model_server(template) -> None:
    assert _container(template)["LinuxParameters"]["SharedMemorySize"] == 8192, (
        "Model servers allocate large pinned host buffers for CUDA transfers and "
        "crash on the 64 MB default."
    )


def test_gpu_is_reserved_as_a_resource_requirement(template) -> None:
    requirements = _container(template)["ResourceRequirements"]
    assert requirements == [{"Type": "GPU", "Value": {"Ref": "GpuCount"}}]


def test_one_model_server_per_instance(template) -> None:
    strategies = template.prop("Service", "PlacementStrategies")
    assert strategies == [{"Type": "spread", "Field": "instanceId"}], (
        "Two model servers on one GPU means both fail to allocate KV cache."
    )


def test_bridge_networking_avoids_the_eni_limit(template) -> None:
    assert template.prop("TaskDefinition", "NetworkMode") == "bridge", (
        "An awsvpc task consumes an ENI per task, and GPU instance types have "
        "low ENI limits."
    )
    assert template.prop("TargetGroup", "TargetType") == "instance"


# --- security ----------------------------------------------------------------

def test_instances_require_imdsv2(template) -> None:
    options = template.prop("LaunchTemplate", "LaunchTemplateData.MetadataOptions")
    assert options["HttpTokens"] == "required", (
        "A token-less metadata request from inside a container is how instance "
        "credentials get exfiltrated through SSRF."
    )


def test_root_volume_is_encrypted_and_large_enough_for_weights(template) -> None:
    ebs = template.prop("LaunchTemplate", "LaunchTemplateData.BlockDeviceMappings.0.Ebs")
    assert ebs["Encrypted"] is True
    assert template.param("RootVolumeSizeGb")["MinValue"] >= 100, (
        "A 7B model in 16-bit is ~15 GB before the image; too small a volume "
        "fails the pull minutes in with a disk-space error."
    )


def test_there_is_no_ssh_access(template) -> None:
    """Debugging a stuck model load is common; Session Manager is the way."""
    ingress = template.prop("InstanceSecurityGroup", "SecurityGroupIngress")
    assert all(rule["FromPort"] != 22 for rule in ingress)
    assert ingress[0]["SourceSecurityGroupId"] == {"Ref": "AlbSecurityGroupId"}
    assert not template.has_prop("LaunchTemplate", "LaunchTemplateData.KeyName")


def test_hub_token_access_is_scoped_to_the_one_secret(template) -> None:
    policy = template.prop("ExecutionRole", "Policies.0")["Fn::If"][1]
    statement = policy["PolicyDocument"]["Statement"][0]
    assert statement["Resource"] == {"Ref": "HuggingFaceTokenSecretArn"}


# --- deployment --------------------------------------------------------------

def test_deployment_does_not_require_doubling_the_gpu_fleet(template) -> None:
    config = template.prop("Service", "DeploymentConfiguration")
    assert config["MinimumHealthyPercent"] == 0
    assert config["MaximumPercent"] == 100, (
        "The usual 100/200 would need double the GPU fleet during a deploy, "
        "which is expensive and may simply not be available."
    )
    assert config["DeploymentCircuitBreaker"] == {"Enable": True, "Rollback": True}


def test_draining_allows_a_generation_to_finish(template) -> None:
    attributes = {
        entry["Key"]: entry["Value"]
        for entry in template.prop("TargetGroup", "TargetGroupAttributes")
    }
    assert int(attributes["deregistration_delay.timeout_seconds"]) >= 120, (
        "Generation requests are long; draining too fast cuts a response off "
        "mid-stream during a deploy."
    )
