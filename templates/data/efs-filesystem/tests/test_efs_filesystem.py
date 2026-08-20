"""Tests for data/efs-filesystem — see docs/TESTING.md for the categories."""

from __future__ import annotations


# 1. Secure defaults -----------------------------------------------------------

def test_filesystem_is_always_encrypted(template) -> None:
    assert template.prop("FileSystem", "Encrypted") is True, (
        "Encryption at rest is not a choice this library offers — an EFS created "
        "unencrypted can never be encrypted in place, only migrated."
    )


def test_filesystem_policy_denies_insecure_transport(template) -> None:
    statements = template.prop("FileSystem", "FileSystemPolicy")["Statement"]
    deny = next(s for s in statements if s["Sid"] == "DenyInsecureTransport")
    assert deny["Effect"] == "Deny" and deny["Condition"]["Bool"]["aws:SecureTransport"] == "false", (
        "Without the TLS-only policy, any client in the security group can mount "
        "over plaintext NFS. ECS satisfies this with TransitEncryption: ENABLED."
    )


def test_backups_default_off_because_they_bill_monthly(template) -> None:
    assert template.default("EnableAutomaticBackups") == "false", (
        "Backup storage is a recurring cost, and this library defaults recurring "
        "costs to off. Turn it on when the data is not reproducible."
    )


def test_nfs_ingress_is_scoped_to_the_client_group(template) -> None:
    ingress = template.prop("MountTargetSecurityGroup", "SecurityGroupIngress")
    assert len(ingress) == 1, "Exactly one ingress rule: NFS from the client group."
    rule = ingress[0]
    assert rule["FromPort"] == 2049 and rule["ToPort"] == 2049, (
        "Only NFS belongs on a mount-target security group."
    )
    assert rule["SourceSecurityGroupId"] == {"Ref": "ClientSecurityGroupId"}, (
        "Ingress must be scoped to the client security group, never a CIDR — the "
        "clients are the only principals with any business mounting this."
    )


def test_filesystem_survives_a_failed_rollback(template) -> None:
    assert template.deletion_policy("FileSystem") == "Retain", (
        "The file system is the data. A rollback that deletes it turns a failed "
        "deploy into data loss."
    )


# 2. Conditional wiring --------------------------------------------------------

def test_extra_mount_targets_appear_with_their_subnets(template) -> None:
    assert template.condition_on("MountTarget2") == "HasMountTarget2"
    assert template.condition_on("MountTarget3") == "HasMountTarget3", (
        "Mount targets two and three exist only when their subnet is supplied — "
        "single-AZ callers should not pay for or wait on extra mount targets."
    )


def test_access_point_is_conditional_and_its_outputs_match(template) -> None:
    assert template.condition_on("AccessPoint") == "ShouldCreateAccessPoint"
    for output in ("AccessPointId", "AccessPointArn"):
        assert template.outputs[output].get("Condition") == "ShouldCreateAccessPoint", (
            "An output referencing a conditional resource must carry the same "
            "Condition, or stack creation fails when the toggle is off."
        )


def test_custom_key_replaces_the_managed_key_only_when_given(template) -> None:
    assert template.prop("FileSystem", "KmsKeyId") == {
        "Fn::If": ["HasCustomKey", {"Ref": "KmsKeyArn"}, {"Ref": "AWS::NoValue"}]
    }, (
        "An empty KmsKeyId is rejected by the API where an absent one is fine — "
        "the CMK must be added via AWS::NoValue, not an empty string."
    )


# 3. Pass-through --------------------------------------------------------------

def test_access_point_enforces_the_posix_identity(template) -> None:
    posix = template.prop("AccessPoint", "PosixUser")
    assert posix == {"Uid": {"Ref": "PosixUid"}, "Gid": {"Ref": "PosixGid"}}, (
        "The access point pins every client to the configured POSIX identity; "
        "losing this pass-through silently changes file ownership on the volume."
    )
    root = template.prop("AccessPoint", "RootDirectory")
    assert root["CreationInfo"]["OwnerUid"] == {"Ref": "PosixUid"}, (
        "The root directory must be created owned by the same identity the "
        "access point enforces, or first mount fails with EACCES."
    )


# 4. Interface -----------------------------------------------------------------

def test_consumer_interface_is_stable(template) -> None:
    for param in ("VpcId", "SubnetId1", "ClientSecurityGroupId"):
        assert param in template.parameters, f"Required parameter {param} is part of the contract."
    for output in ("FileSystemId", "FileSystemArn", "MountTargetSecurityGroupId"):
        assert output in template.outputs, (
            f"Output {output} is what callers wire into ECS volume configurations "
            "and IAM policies — removing it breaks every consumer."
        )
