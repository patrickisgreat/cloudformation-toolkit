"""Assertions for data/athena-workgroup."""

from __future__ import annotations


def _config(template) -> dict:
    return template.prop("Workgroup", "WorkGroupConfiguration")


def test_workgroup_configuration_is_enforced(template) -> None:
    """Without enforcement, a client overrides the result location and the scan
    cutoff from its own settings, making both suggestions rather than controls."""
    assert _config(template)["EnforceWorkGroupConfiguration"] is True


def test_scan_cutoff_defaults_to_ten_gigabytes(template) -> None:
    assert template.default("BytesScannedCutoffPerQuery") == 10737418240, (
        "Athena bills per terabyte scanned. One SELECT * over an unpartitioned "
        "lake is a real invoice, and the cutoff is what makes exceeding it a "
        "decision rather than an accident."
    )
    assert _config(template)["BytesScannedCutoffPerQuery"]["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
        "A cutoff of 0 must remove the property; Athena rejects zero as a value."
    )


def test_results_are_encrypted(template) -> None:
    encryption = _config(template)["ResultConfiguration"]["EncryptionConfiguration"]
    assert encryption["EncryptionOption"] == {"Fn::If": ["UsesKms", "SSE_KMS", "SSE_S3"]}
    assert encryption["KmsKey"]["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_metrics_are_published(template) -> None:
    assert _config(template)["PublishCloudWatchMetricsEnabled"] is True, (
        "Without metrics there is no way to see scanned bytes trending up before "
        "the bill arrives."
    )


def test_recursive_delete_is_enabled(template) -> None:
    assert template.prop("Workgroup", "RecursiveDeleteOption") is True, (
        "Deleting a workgroup containing saved queries otherwise fails, turning a "
        "stack teardown into manual console cleanup."
    )


def test_engine_version_auto_omits_the_block(template) -> None:
    assert _config(template)["EngineVersion"]["Fn::If"][1] == {"Ref": "AWS::NoValue"}
    assert template.default("EngineVersion") == "AUTO"


def test_result_location_is_derived_from_the_bucket_arn(template) -> None:
    location = _config(template)["ResultConfiguration"]["OutputLocation"]
    assert location["Fn::Sub"][1]["BucketName"] == {
        "Fn::Select": [5, {"Fn::Split": [":", {"Ref": "ResultsBucketArn"}]}]
    }, "callers pass an ARN everywhere else, so the bucket name is derived here"
    assert template.outputs["ResultsLocation"]["Value"] == location
