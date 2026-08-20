"""Assertions for foundation/iam-user.

The claim under test: no credential ever passes through a parameter, an
output, or a change set - passwords and key material exist only inside
Secrets Manager and inside the resources that consume them.
"""

from __future__ import annotations

import json


# --- no secrets through parameters ------------------------------------------

def test_no_parameter_can_carry_a_credential(template) -> None:
    """Every parameter is a name, an ARN list, or an enumerated switch."""
    for name, spec in template.parameters.items():
        assert "AllowedPattern" in spec or "AllowedValues" in spec or name in ("Groups", "ManagedPolicyArns", "PermissionsBoundaryArn"), name
    for switch in ("EnableConsoleAccess", "CreateAccessKey"):
        assert template.allowed_values(switch) == ["true", "false"], (
            "credential creation must be a switch, never a value"
        )


def test_console_password_is_generated_not_supplied(template) -> None:
    generate = template.prop("ConsolePasswordSecret", "GenerateSecretString")
    assert generate["PasswordLength"] == 32
    assert generate["RequireEachIncludedType"] is True

    login = template.prop("User", "LoginProfile")["Fn::If"][1]
    assert login["Password"] == {
        "Fn::Sub": "{{resolve:secretsmanager:${ConsolePasswordSecret}}}"
    }, (
        "the password must arrive by dynamic reference - resolved inside "
        "CloudFormation, invisible to the change set and the events"
    )


def test_first_password_is_single_use(template) -> None:
    login = template.prop("User", "LoginProfile")["Fn::If"][1]
    assert login["PasswordResetRequired"] is True, (
        "the generated password is written down in a secret; forcing a change "
        "at first sign-in is what makes that stored copy worthless to steal"
    )


def test_secret_access_key_never_leaves_secrets_manager(template) -> None:
    secret_string = template.prop("AccessKeySecret", "SecretString")
    assert "${AccessKey.SecretAccessKey}" in secret_string["Fn::Sub"], (
        "GetAtt into the secret resource is the only place the secret half "
        "may appear"
    )
    for name, output in template.outputs.items():
        assert "SecretAccessKey" not in json.dumps(output["Value"]), (
            f"output {name} must not expose the secret half - outputs are "
            "readable by anyone with DescribeStacks"
        )


# --- secure defaults ---------------------------------------------------------

def test_credentials_default_to_none(template) -> None:
    assert template.default("EnableConsoleAccess") == "false", (
        "a user who only assumes roles needs no password; a password that "
        "does not exist cannot be phished"
    )
    assert template.default("CreateAccessKey") == "false", (
        "long-lived keys are the credential that leaks - opt in per user, "
        "per tool"
    )


# --- conditional wiring ------------------------------------------------------

def test_credential_resources_track_their_switches(template) -> None:
    assert template.condition_on("ConsolePasswordSecret") == "HasConsoleAccess"
    assert template.condition_on("AccessKey") == "HasAccessKey"
    assert template.condition_on("AccessKeySecret") == "HasAccessKey"
    for output, condition in (
        ("ConsoleSignInUrl", "HasConsoleAccess"),
        ("ConsolePasswordSecretArn", "HasConsoleAccess"),
        ("AccessKeyId", "HasAccessKey"),
        ("AccessKeySecretArn", "HasAccessKey"),
    ):
        assert template.outputs[output].get("Condition") == condition


def test_empty_grants_drop_out_rather_than_attach_empty(template) -> None:
    assert template.prop("User", "Groups")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert template.prop("User", "ManagedPolicyArns")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert template.prop("User", "PermissionsBoundary")["Fn::If"][2] == {"Ref": "AWS::NoValue"}


# --- interface ---------------------------------------------------------------

def test_iam_users_are_account_global_so_no_environment(template) -> None:
    """Humans are not deployed per environment. A `dev` copy of a person is
    two credentials for one human; environment separation for humans is done
    with separate accounts (foundation/org-account), not name suffixes.
    """
    assert "Environment" not in template.parameters
    assert template.prop("User", "UserName") == {"Fn::Sub": "${NamePrefix}-${UserName}"}
