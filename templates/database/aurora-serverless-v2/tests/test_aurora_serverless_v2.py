"""Assertions for database/aurora-serverless-v2."""

from __future__ import annotations

import pytest

INSTANCES = ["Writer", "Reader1", "Reader2"]


def test_no_password_parameter_exists(template) -> None:
    """The password is generated, never passed.

    A master password supplied as a stack parameter appears in the change set,
    the stack events, and any CI log that prints them.
    """
    assert not any("password" in name.lower() for name in template.parameters)
    assert template.prop("Cluster", "MasterUserPassword") == {
        "Fn::Sub": "{{resolve:secretsmanager:${MasterSecret}::password}}"
    }


def test_generated_password_excludes_characters_rds_rejects(template) -> None:
    excluded = template.prop("MasterSecret", "GenerateSecretString.ExcludeCharacters")
    for char in ("/", "@", '"', "\\"):
        assert char in excluded, f"RDS rejects {char!r} in a master password"


def test_storage_encryption_is_not_optional(template) -> None:
    assert template.prop("Cluster", "StorageEncrypted") is True, (
        "StorageEncrypted cannot be enabled in place — retrofitting means "
        "snapshot, copy with a key, restore. It must be a literal true."
    )


@pytest.mark.parametrize("instance", INSTANCES)
def test_every_instance_is_serverless_and_private(template, instance: str) -> None:
    assert template.prop(instance, "DBInstanceClass") == "db.serverless", (
        "Any other instance class silently produces a provisioned instance "
        "billed by the hour, inside a cluster that otherwise looks serverless."
    )
    assert template.prop(instance, "PubliclyAccessible") is False


def test_cluster_snapshots_on_delete_but_instances_do_not(template) -> None:
    assert template.deletion_policy("Cluster") == "Snapshot", (
        "Deleting the stack must neither destroy the data nor leave a running "
        "cluster nobody is watching."
    )
    for instance in INSTANCES:
        assert template.deletion_policy(instance) == "Delete", (
            f"{instance} holds no data of its own; retaining it would leave you "
            "paying for compute attached to nothing."
        )


def test_ingress_follows_the_workload_not_an_address_range(template) -> None:
    ingress = template.prop("SecurityGroup", "SecurityGroupIngress.0")
    assert ingress["SourceSecurityGroupId"] == {"Ref": "ClientSecurityGroupId"}
    assert "CidrIp" not in ingress
    assert ingress["FromPort"] == {"Fn::If": ["IsPostgres", 5432, 3306]}
    assert ingress["Description"]


def test_readers_scale_with_the_count(template) -> None:
    assert template.condition_on("Reader1") == "HasReaders"
    assert template.condition_on("Reader2") == "HasSecondReader"


def test_secret_is_attached_to_the_cluster(template) -> None:
    """The attachment is what adds host, port and dbname to the secret.

    Without it the secret holds only a username and password, and every consumer
    has to be told the endpoint separately.
    """
    assert template.prop("SecretAttachment", "SecretId") == {"Ref": "MasterSecret"}
    assert template.prop("SecretAttachment", "TargetId") == {"Ref": "Cluster"}


def test_backups_and_logs_are_on(template) -> None:
    assert template.default("BackupRetentionDays") == 7
    assert template.prop("Cluster", "EnableCloudwatchLogsExports") == {
        "Fn::If": ["IsPostgres", ["postgresql"], ["error", "slowquery"]]
    }


def test_data_api_is_opt_in(template) -> None:
    assert template.default("EnableDataApi") == "false", (
        "The Data API is a second access path to the data, authorised by IAM "
        "rather than by network position."
    )


def test_outputs_let_a_consumer_connect_without_the_password(template) -> None:
    assert template.outputs["ClusterEndpoint"]["Value"] == {
        "Fn::GetAtt": ["Cluster", "Endpoint.Address"]
    }
    assert template.outputs["MasterSecretArn"]["Value"] == {"Ref": "MasterSecret"}
