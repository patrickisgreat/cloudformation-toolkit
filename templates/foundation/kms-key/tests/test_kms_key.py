"""Assertions for foundation/kms-key."""

from __future__ import annotations


def _statements(template):
    return template.prop("Key", "KeyPolicy.Statement")


def _by_sid(template, sid):
    for statement in _statements(template):
        if isinstance(statement, dict) and statement.get("Sid") == sid:
            return statement
        # Conditional statements are wrapped in an Fn::If whose true branch is
        # the statement itself.
        if isinstance(statement, dict) and "Fn::If" in statement:
            branch = statement["Fn::If"][1]
            if isinstance(branch, dict) and branch.get("Sid") == sid:
                return branch
    return None


# --- secure defaults ---------------------------------------------------------

def test_rotation_is_on_and_not_optional(template) -> None:
    assert template.prop("Key", "EnableKeyRotation") is True, (
        "Annual rotation is one property and bounds the blast radius of a leaked "
        "key with no application change. It is not exposed as a parameter because "
        "there is no good reason to turn it off."
    )


def test_key_is_retained_on_stack_deletion(template) -> None:
    assert template.deletion_policy("Key") == "Retain", (
        "Deleting a KMS key makes every ciphertext encrypted under it permanently "
        "unreadable. A stack rollback must not be able to do that."
    )
    assert template.resource("Key").get("UpdateReplacePolicy") == "Retain"


def test_pending_window_defaults_to_the_maximum(template) -> None:
    assert template.default("PendingWindowInDays") == 30, (
        "The pending window is the only chance to notice a mistaken deletion, so "
        "it defaults to the longest AWS allows."
    )
    assert template.param("PendingWindowInDays")["MinValue"] == 7


def test_multi_region_is_off_by_default(template) -> None:
    assert template.default("MultiRegion") == "false", (
        "MultiRegion cannot be changed after creation, so the reversible choice "
        "is the default."
    )


# --- key policy --------------------------------------------------------------

def test_account_root_statement_is_unconditional(template) -> None:
    """The statement that keeps the key manageable must not be removable.

    Without it, no IAM policy in the account can grant access to the key, and
    the key is orphaned with no recovery path. It is the most common way to
    permanently lose a CMK.
    """
    root = _by_sid(template, "EnableIAMPoliciesInThisAccount")
    assert root is not None, "the account-root statement is missing"
    assert root["Principal"]["AWS"] == {
        "Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:root"
    }
    assert "Fn::If" not in str(_statements(template)[0]), (
        "the account-root statement must be the unconditional first statement"
    )


def test_administration_and_usage_are_separate_principals(template) -> None:
    admin = _by_sid(template, "AllowKeyAdministration")
    user = _by_sid(template, "AllowUseOfTheKey")
    assert admin is not None and user is not None

    admin_actions = set(admin["Action"])
    user_actions = set(user["Action"])
    assert "kms:ScheduleKeyDeletion" in admin_actions
    assert "kms:ScheduleKeyDeletion" not in user_actions, (
        "The workload role must not be able to schedule the key for deletion — "
        "separating destruction from use is the reason to run a CMK at all."
    )
    assert "kms:Decrypt" in user_actions
    assert "kms:Decrypt" not in admin_actions, (
        "Key administrators should not get data access for free."
    )


def test_service_principal_grant_is_scoped_to_this_account(template) -> None:
    service = _by_sid(template, "AllowAwsServiceUse")
    assert service is not None
    assert service["Condition"]["StringEquals"]["aws:SourceAccount"] == {"Ref": "AWS::AccountId"}, (
        "An unscoped service principal lets another account's log group or bucket "
        "name your key and have AWS honour the request (the confused deputy)."
    )


# --- conditional wiring ------------------------------------------------------

def test_optional_statements_drop_out_cleanly(template) -> None:
    """Unused principals must produce no statement at all, not an empty one."""
    conditional = [s for s in _statements(template) if isinstance(s, dict) and "Fn::If" in s]
    assert len(conditional) == 3, "admin, user, and service statements are each optional"
    for statement in conditional:
        condition, _, false_branch = statement["Fn::If"]
        assert false_branch == {"Ref": "AWS::NoValue"}, (
            f"the {condition} statement must resolve to AWS::NoValue when off — "
            "an empty Principal makes the whole policy invalid"
        )


# --- pass-through and interface ---------------------------------------------

def test_alias_is_derived_from_the_name_prefix(template) -> None:
    assert template.prop("Alias", "AliasName") == {
        "Fn::Sub": "alias/${NamePrefix}-${AliasSuffix}"
    }
    assert template.prop("Alias", "TargetKeyId") == {"Ref": "Key"}


def test_outputs_cover_both_id_and_arn(template) -> None:
    """Different AWS properties want different forms of the same key."""
    assert template.outputs["KeyId"]["Value"] == {"Ref": "Key"}
    assert template.outputs["KeyArn"]["Value"] == {"Fn::GetAtt": ["Key", "Arn"]}
    assert "AliasName" in template.outputs
