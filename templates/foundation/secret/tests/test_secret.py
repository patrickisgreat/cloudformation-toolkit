"""Assertions for foundation/secret."""

from __future__ import annotations

import json


# --- the design constraint ---------------------------------------------------

def test_no_parameter_can_carry_the_secret_value(template) -> None:
    """The template must offer no way to pass a value in.

    A secret supplied as a stack parameter appears in the change set, in the
    stack events, and in CI logs. NoEcho masks the API response, not the change
    set someone reviewed. If this test ever fails because a `SecretString`
    parameter was added for convenience, the convenience is the bug.
    """
    forbidden = {"SecretString", "SecretValue", "Password", "InitialValue"}
    assert not (forbidden & set(template.parameters)), (
        "A value passed as a parameter is a value that has leaked. Populate "
        "non-generated secrets out of band with put-secret-value."
    )


def _generation_block(template) -> dict:
    """The true branch of the Fn::If wrapping GenerateSecretString."""
    return template.prop("Secret", "GenerateSecretString")["Fn::If"][1]


def test_generation_is_the_default(template) -> None:
    assert template.default("GenerateSecret") == "true"
    assert _generation_block(template)["PasswordLength"] == {"Ref": "PasswordLength"}
    assert _generation_block(template)["RequireEachIncludedType"] is True, (
        "Without RequireEachIncludedType, a generated password can legally come "
        "back as 32 lowercase letters and fail an RDS complexity check."
    )
    assert template.default("PasswordLength") == 32
    assert template.param("PasswordLength")["MinValue"] == 16, (
        "Below 16 characters a generated password stops being meaningfully strong."
    )


def test_generated_passwords_exclude_characters_that_break_connection_strings(template) -> None:
    excluded = template.default("ExcludeCharacters")
    for char in ("/", "@", '"', "\\", "$", "`"):
        assert char in excluded, (
            f"{char!r} must be excluded — it breaks shell quoting, JDBC URLs, or "
            "RDS master passwords, which is a far more common outage than the "
            "entropy lost by excluding it."
        )


def test_string_template_produces_the_shape_rds_rotation_expects(template) -> None:
    default = template.default("SecretStringTemplate")
    parsed = json.loads(default)
    assert "username" in parsed, (
        "RDS, Aurora and DocumentDB managed rotation all expect a JSON secret "
        "with username and password keys."
    )
    assert template.default("GenerateStringKey") == "password"


# --- secure defaults ---------------------------------------------------------

def test_secret_survives_stack_deletion(template) -> None:
    assert template.deletion_policy("Secret") == "Retain", (
        "The database that trusts this password does not roll back when the "
        "stack does."
    )


def test_recovery_window_cannot_be_waived(template) -> None:
    assert template.param("RecoveryWindowInDays")["MinValue"] == 7, (
        "AWS removed the zero-day delete option because deleting a live database "
        "password by accident turned out to be common. Do not reintroduce it."
    )
    assert template.default("RecoveryWindowInDays") == 30


def test_resource_policy_blocks_public_access(template) -> None:
    assert template.prop("ResourcePolicy", "BlockPublicPolicy") is True, (
        "BlockPublicPolicy is one property and rejects a policy that would make "
        "the secret world-readable — cheap insurance against a pasted principal."
    )


# --- conditional wiring ------------------------------------------------------

def test_generation_block_disappears_when_not_generating(template) -> None:
    generate = template.prop("Secret", "GenerateSecretString")
    assert generate["Fn::If"][0] == "ShouldGenerateSecret"
    assert generate["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
        "Leaving an empty GenerateSecretString would have Secrets Manager "
        "generate a value over the one you are about to put there."
    )


def test_replication_and_resource_policy_are_opt_in(template) -> None:
    assert template.prop("Secret", "ReplicaRegions")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert template.condition_on("ResourcePolicy") == "HasReaderRole"


def test_replica_inherits_the_customer_managed_key(template) -> None:
    replica = template.prop("Secret", "ReplicaRegions")["Fn::If"][1][0]
    assert replica["KmsKeyId"]["Fn::If"][0] == "HasKmsKey", (
        "A replica in another region must use the same key selection as the "
        "primary, or the copy is unreadable there."
    )


# --- interface ---------------------------------------------------------------

def test_name_is_environment_scoped(template) -> None:
    assert template.prop("Secret", "Name") == {
        "Fn::Sub": "${Environment}/${NamePrefix}/${SecretSuffix}"
    }, (
        "Secret names are account-global. Without the environment prefix, dev and "
        "prod collide on the same name."
    )
    assert template.outputs["SecretName"]["Value"] == template.prop("Secret", "Name")
