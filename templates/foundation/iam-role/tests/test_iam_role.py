"""Assertions for foundation/iam-role.

The trust policy is the security boundary. Most of this file checks that the
optional trust statements and conditions drop out cleanly rather than widening
the trust when unused.
"""

from __future__ import annotations


def _trust_statements(template):
    return template.prop("Role", "AssumeRolePolicyDocument.Statement")


# --- the trust policy --------------------------------------------------------

def test_unused_trust_statements_vanish(template) -> None:
    """An empty-principal statement is a malformed policy, not a narrower one."""
    statements = _trust_statements(template)
    assert len(statements) == 2
    for entry in statements:
        assert entry["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
            "a trust statement whose principal parameter is empty must be "
            "removed entirely, not left behind with an empty Principal"
        )


def test_mfa_is_required_of_human_principals_by_default(template) -> None:
    assert template.default("RequireMfa") == "true", (
        "Cross-account trust is usually for humans. Requiring MFA by default "
        "means forgetting the parameter fails closed; machine-role callers "
        "opt out explicitly."
    )


def test_condition_map_is_swapped_whole(template) -> None:
    """Fn::If cannot add or remove a map key, so every ExternalId x MFA
    combination must swap in a complete Condition map."""
    aws_statement = _trust_statements(template)[1]["Fn::If"][1]
    condition = aws_statement["Condition"]

    both = condition["Fn::If"]
    assert both[0] == "HasExternalIdAndMfa"
    assert both[1]["StringEquals"]["sts:ExternalId"] == {"Ref": "ExternalId"}
    assert both[1]["Bool"]["aws:MultiFactorAuthPresent"] == "true"

    external_only = both[2]["Fn::If"]
    assert external_only[1] == {"StringEquals": {"sts:ExternalId": {"Ref": "ExternalId"}}}

    mfa_only = external_only[2]["Fn::If"]
    assert mfa_only[1] == {"Bool": {"aws:MultiFactorAuthPresent": "true"}}
    assert mfa_only[2] == {"Ref": "AWS::NoValue"}, (
        "with neither ExternalId nor MFA the Condition key must vanish - an "
        "empty Condition map is a malformed trust policy"
    )


def test_a_role_nobody_can_assume_is_rejected_up_front(template) -> None:
    """The Rules assertion turns a 15-minute rollback into an immediate error."""
    rules = template.body.get("Rules", {})
    assert "SomeoneMustBeTrusted" in rules, (
        "with both principal parameters empty the trust policy has no "
        "statements, which IAM rejects only after the stack starts creating"
    )


def test_service_principal_pattern_rejects_wildcards_and_bare_arns(template) -> None:
    import re

    pattern = template.param("ServicePrincipal")["AllowedPattern"]
    assert re.fullmatch(pattern, "ecs-tasks.amazonaws.com")
    assert re.fullmatch(pattern, "")
    assert not re.fullmatch(pattern, "*"), "a wildcard service principal trusts everything"
    assert not re.fullmatch(pattern, "arn:aws:iam::123456789012:root"), (
        "an account ARN belongs in TrustedPrincipalArns, where MFA and "
        "ExternalId conditions apply to it"
    )


# --- permissions -------------------------------------------------------------

def test_permissions_drop_out_rather_than_attach_empty(template) -> None:
    managed = template.prop("Role", "ManagedPolicyArns")
    assert managed["Fn::If"][0] == "HasManagedPolicies"
    assert managed["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
        "an empty string Split()s to [''], which IAM rejects as a policy ARN"
    )

    inline = template.prop("Role", "Policies")[0]["Fn::If"]
    assert inline[0] == "HasInlinePolicy"
    assert inline[2] == {"Ref": "AWS::NoValue"}


def test_session_defaults_to_one_hour(template) -> None:
    assert template.default("MaxSessionDurationSeconds") == 3600
    assert template.param("MaxSessionDurationSeconds")["MinValue"] == 900


def test_boundary_is_omitted_not_empty(template) -> None:
    boundary = template.prop("Role", "PermissionsBoundary")
    assert boundary == {
        "Fn::If": ["HasPermissionsBoundary", {"Ref": "PermissionsBoundaryArn"}, {"Ref": "AWS::NoValue"}]
    }, "an empty-string boundary ARN fails the create; absent means no boundary"


# --- conditional wiring and interface ---------------------------------------

def test_instance_profile_is_opt_in_and_wraps_the_role(template) -> None:
    assert template.default("CreateInstanceProfile") == "false"
    assert template.condition_on("InstanceProfile") == "ShouldCreateInstanceProfile"
    assert template.prop("InstanceProfile", "Roles") == [{"Ref": "Role"}]
    for output in ("InstanceProfileArn", "InstanceProfileName"):
        assert template.outputs[output].get("Condition") == "ShouldCreateInstanceProfile", (
            "an output referencing a conditional resource needs the same Condition"
        )


def test_outputs_expose_arn_name_and_stable_id(template) -> None:
    assert template.outputs["RoleArn"]["Value"] == {"Fn::GetAtt": ["Role", "Arn"]}
    assert template.outputs["RoleName"]["Value"] == {"Ref": "Role"}
    assert template.outputs["RoleId"]["Value"] == {"Fn::GetAtt": ["Role", "RoleId"]}
