"""Assertions for ml/sagemaker-endpoint."""

from __future__ import annotations


def _variant(template) -> dict:
    return template.prop("EndpointConfig", "ProductionVariants.0")


def test_serving_mode_properties_are_mutually_exclusive(template) -> None:
    """A variant carrying both instance and serverless config is rejected."""
    variant = _variant(template)
    assert variant["InstanceType"]["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert variant["InitialInstanceCount"]["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert variant["ServerlessConfig"]["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_autoscaling_only_exists_for_realtime(template) -> None:
    """Serverless endpoints have no instance count to scale."""
    for logical_id in ("ScalableTarget", "ScalingPolicy"):
        assert template.condition_on(logical_id) == "IsRealtime"


def test_scaling_tracks_invocations_not_cpu(template) -> None:
    metric = template.prop(
        "ScalingPolicy",
        "TargetTrackingScalingPolicyConfiguration.PredefinedMetricSpecification.PredefinedMetricType",
    )
    assert metric == "SageMakerVariantInvocationsPerInstance", (
        "GPU inference is frequently memory-bound with CPU near idle, so a "
        "CPU-based policy never fires while the endpoint queues."
    )


def test_scale_in_is_slower_than_scale_out(template) -> None:
    config = template.prop("ScalingPolicy", "TargetTrackingScalingPolicyConfiguration")
    assert config["ScaleInCooldown"] > config["ScaleOutCooldown"]


def test_deployment_rolls_back_on_errors(template) -> None:
    """Without this a model that loads but answers badly has already replaced
    the working one."""
    deployment = template.prop("Endpoint", "DeploymentConfig")
    assert deployment["AutoRollbackConfiguration"]["Alarms"] == [{"AlarmName": {"Ref": "InvocationErrorAlarm"}}]
    assert deployment["BlueGreenUpdatePolicy"]["TerminationWaitInSeconds"] >= 600, (
        "The old fleet must be held long enough for the alarm to evaluate."
    )


def test_rollback_alarm_watches_the_right_variant(template) -> None:
    dimensions = {d["Name"]: d["Value"] for d in template.prop("InvocationErrorAlarm", "Dimensions")}
    assert dimensions["VariantName"] == "primary"
    assert template.prop("InvocationErrorAlarm", "MetricName") == "Invocation5XXErrors"
    assert template.prop("InvocationErrorAlarm", "TreatMissingData") == "notBreaching", (
        "An endpoint receiving no traffic emits no datapoints; breaching on "
        "missing data would roll back every quiet deployment."
    )


def test_execution_role_artifact_access_is_scoped(template) -> None:
    statement = template.prop("ExecutionRole", "Policies.0.PolicyDocument.Statement.3")
    assert statement["Fn::If"][1]["Resource"] == [
        {"Ref": "ModelArtifactBucketArn"},
        {"Fn::Sub": "${ModelArtifactBucketArn}/*"},
    ]


def test_metric_publishing_is_namespace_scoped(template) -> None:
    statement = template.prop("ExecutionRole", "Policies.0.PolicyDocument.Statement.2")
    assert statement["Condition"]["StringEquals"]["cloudwatch:namespace"] == "AWS/SageMaker", (
        "PutMetricData has no resource-level permissions; the namespace "
        "condition is the only way to scope it."
    )


def test_data_capture_is_opt_in_and_records_both_directions(template) -> None:
    capture = template.prop("EndpointConfig", "DataCaptureConfig")
    assert capture["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    modes = [entry["CaptureMode"] for entry in capture["Fn::If"][1]["CaptureOptions"]]
    assert modes == ["Input", "Output"], (
        "Capturing inputs without outputs makes offline evaluation impossible."
    )
