"""Assertions for foundation/org-account.

An account is the outermost container of state there is. The assertions here
are mostly about the ways CloudFormation could be tricked into closing or
replacing one.
"""

from __future__ import annotations

import json
import re


# --- the account must survive everything -------------------------------------

def test_account_is_retained_on_delete_and_replace(template) -> None:
    resource = template.resource("Account")
    assert resource.get("DeletionPolicy") == "Retain", (
        "a stack delete must leave the account alive; closing an account is "
        "`aws organizations close-account`, taken deliberately by a human"
    )
    assert resource.get("UpdateReplacePolicy") == "Retain", (
        "Email is immutable, so an email change replaces the account - "
        "without Retain, the replacement closes the original and everything "
        "in it"
    )


def test_email_cannot_be_wildcarded_or_reused_casually(template) -> None:
    pattern = template.param("Email")["AllowedPattern"]
    assert re.fullmatch(pattern, "aws+dev@example.com"), (
        "plus-addressing is the documented pattern for per-account root email"
    )
    assert not re.fullmatch(pattern, "not-an-email")
    assert "Default" not in template.param("Email"), (
        "a default email would silently point two accounts' root at one inbox"
    )


# --- placement ---------------------------------------------------------------

def test_ou_placement_falls_back_to_the_root_cleanly(template) -> None:
    parents = template.prop("Account", "ParentIds")
    assert parents == [
        {"Fn::If": ["HasParentOu", {"Ref": "ParentOuId"}, {"Ref": "AWS::NoValue"}]}
    ], (
        "an empty ParentIds entry is invalid; with no OU the entry must "
        "vanish so Organizations defaults to the root"
    )


def test_parent_ou_pattern_accepts_ous_and_roots_only(template) -> None:
    pattern = template.param("ParentOuId")["AllowedPattern"]
    assert re.fullmatch(pattern, "ou-ab12-cdef3456")
    assert re.fullmatch(pattern, "r-ab12")
    assert re.fullmatch(pattern, "")
    assert not re.fullmatch(pattern, "123456789012"), (
        "an account ID is not a parent - failing at parameter validation "
        "beats failing mid-create"
    )


# --- access ------------------------------------------------------------------

def test_access_role_defaults_to_the_name_every_tool_expects(template) -> None:
    assert template.default("AccessRoleName") == "OrganizationAccountAccessRole"


def test_outputs_hand_over_id_and_bootstrap_role_together(template) -> None:
    assert template.outputs["AccountId"]["Value"] == {"Fn::GetAtt": ["Account", "AccountId"]}
    role_arn = template.outputs["AccessRoleArn"]["Value"]["Fn::Sub"]
    assert "${Account.AccountId}" in role_arn and "${AccessRoleName}" in role_arn, (
        "the ID and the role ARN are the two halves a caller needs to "
        "actually enter the new account"
    )


# --- interface ---------------------------------------------------------------

def test_accounts_are_environments_so_no_environment_parameter(template) -> None:
    """Every service template takes `Environment`. This one cannot: the
    account IS the environment - AccountSuffix carries that meaning, and an
    Environment parameter here would imply a dev copy of a prod account,
    which is not a thing Organizations can express.
    """
    assert "Environment" not in template.parameters
    assert template.prop("Account", "AccountName") == {
        "Fn::Sub": "${NamePrefix}-${AccountSuffix}"
    }
