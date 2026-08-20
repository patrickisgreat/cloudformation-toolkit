"""Assertions for foundation/iam-groups.

The MFA-enforcement policy is where the security lives; most of this file is
about which actions escape the deny, because every action in that NotAction
list is available to a phished password.
"""

from __future__ import annotations

import json


def _mfa_statements(template):
    return template.prop("MfaEnforcementPolicy", "PolicyDocument.Statement")


# --- MFA enforcement ---------------------------------------------------------

def test_mfa_is_enforced_by_default_on_every_created_group(template) -> None:
    assert template.default("EnforceMfa") == "true", (
        "Without the MFA policy, a phished password is full account access at "
        "whatever tier the group grants."
    )
    groups = template.prop("MfaEnforcementPolicy", "Groups")
    conditions = {entry["Fn::If"][0] for entry in groups}
    assert conditions == {"HasAdminGroup", "HasPowerUserGroup", "HasReadOnlyGroup", "HasCustomGroup"}, (
        "every group this template can create must receive the MFA policy"
    )
    for entry in groups:
        assert entry["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_deny_carve_out_cannot_remove_the_second_factor(template) -> None:
    """The NotAction list is the attack surface of a no-MFA session."""
    deny = _mfa_statements(template)[-1]
    assert deny["Effect"] == "Deny"
    assert deny["Condition"] == {"BoolIfExists": {"aws:MultiFactorAuthPresent": "false"}}, (
        "BoolIfExists is required: access-key requests carry no MFA context "
        "key at all, and a plain Bool would let them straight past the deny"
    )
    not_action = deny["NotAction"]
    for action in ("iam:DeactivateMFADevice", "iam:DeleteVirtualMFADevice"):
        assert action not in not_action, (
            f"{action} without MFA lets stolen access keys remove the second "
            "factor and then do anything"
        )


def test_mfa_self_enrolment_is_scoped_to_the_calling_user(template) -> None:
    statements = _mfa_statements(template)
    own_device = statements[1]["Resource"]["Fn::Sub"]
    own_user = statements[2]["Resource"]["Fn::Sub"]
    assert own_device.endswith("mfa/${!aws:username}"), (
        "${!aws:username} must survive Fn::Sub as a literal IAM policy "
        "variable - ${aws:username} would be a template substitution error"
    )
    assert own_user.endswith("user/${!aws:username}")


# --- the tiers ---------------------------------------------------------------

def test_tiers_use_aws_managed_policies_not_inline_admin(template) -> None:
    """`Action: '*'` in a template is what the policy suite exists to reject;
    the admin tier must arrive as the AWS-managed policy ARN instead."""
    for logical_id, policy in (
        ("AdminGroup", "AdministratorAccess"),
        ("PowerUserGroup", "PowerUserAccess"),
        ("ReadOnlyGroup", "ReadOnlyAccess"),
    ):
        arns = template.prop(logical_id, "ManagedPolicyArns")
        assert arns == [{"Fn::Sub": f"arn:${{AWS::Partition}}:iam::aws:policy/{policy}"}]


def test_each_tier_is_individually_optional(template) -> None:
    for logical_id, condition in (
        ("AdminGroup", "HasAdminGroup"),
        ("PowerUserGroup", "HasPowerUserGroup"),
        ("ReadOnlyGroup", "HasReadOnlyGroup"),
        ("CustomGroup", "HasCustomGroup"),
    ):
        assert template.condition_on(logical_id) == condition


def test_custom_group_exists_only_when_it_grants_something(template) -> None:
    """A group with no policies is a trap: it looks like access and grants none."""
    assert template.conditions["HasCustomGroup"] == {
        "Fn::Not": [{"Fn::Equals": [{"Ref": "CustomGroupManagedPolicyArns"}, ""]}]
    }
    assert template.prop("CustomGroup", "ManagedPolicyArns") == {
        "Fn::Split": [",", {"Ref": "CustomGroupManagedPolicyArns"}]
    }


# --- interface ---------------------------------------------------------------

def test_iam_groups_are_account_global_so_no_environment(template) -> None:
    """Every service template takes `Environment`. This one does not: IAM has
    no regions and no environments, and a `myapp-dev-admins` group implies a
    per-environment human-access model that IAM cannot actually deliver -
    environment separation for humans is what separate accounts
    (foundation/org-account) are for.
    """
    assert "Environment" not in template.parameters
    assert "Environment" not in json.dumps(template.prop("AdminGroup", "GroupName"))


def test_outputs_carry_the_same_condition_as_their_group(template) -> None:
    for output, condition in (
        ("AdminGroupName", "HasAdminGroup"),
        ("PowerUserGroupName", "HasPowerUserGroup"),
        ("ReadOnlyGroupName", "HasReadOnlyGroup"),
        ("CustomGroupName", "HasCustomGroup"),
        ("MfaEnforcementPolicyArn", "ShouldEnforceMfa"),
    ):
        assert template.outputs[output].get("Condition") == condition
