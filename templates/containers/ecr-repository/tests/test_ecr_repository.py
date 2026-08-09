"""Assertions for containers/ecr-repository."""

from __future__ import annotations

import json


def _lifecycle_json(template) -> dict:
    """The generated lifecycle policy, with Fn::Sub placeholders substituted.

    The policy is authored as a Sub'd JSON string because ECR takes it as a
    string, not a structure. That means a typo produces a template that lints
    clean and fails at deploy — so the test parses it the way ECR will.
    """
    body = template.prop("Repository", "LifecyclePolicy")["Fn::If"][1]
    text = body["LifecyclePolicyText"]["Fn::If"][2]["Fn::Sub"]
    rendered = (
        text.replace("${ExpireUntaggedAfterDays}", "14")
        .replace("${KeepLastNImages}", "30")
    )
    return json.loads(rendered)


# --- secure defaults ---------------------------------------------------------

def test_tags_are_immutable_by_default(template) -> None:
    assert template.default("ImageTagMutability") == "IMMUTABLE", (
        "Mutable tags let a pushed digest change under a running service, so the "
        "image you tested is not necessarily the image serving traffic."
    )


def test_images_are_scanned_on_push(template) -> None:
    assert template.default("ScanOnPush") == "true"
    assert template.prop("Repository", "ImageScanningConfiguration.ScanOnPush") == {"Ref": "ScanOnPush"}


def test_repository_is_not_emptied_or_deleted_by_a_rollback(template) -> None:
    assert template.deletion_policy("Repository") == "Retain"
    assert template.default("EmptyOnDelete") == "false", (
        "The images in a repository are the deploy history and the rollback path. "
        "A stack rollback must not be able to discard them."
    )


def test_encryption_defaults_to_the_free_option(template) -> None:
    assert template.default("EncryptionType") == "AES256", (
        "AES256 satisfies encryption-at-rest at no cost; KMS is for cross-account "
        "or key-level audit, and costs per request."
    )


# --- the generated lifecycle policy -----------------------------------------

def test_generated_lifecycle_policy_is_valid_json(template) -> None:
    policy = _lifecycle_json(template)
    assert len(policy["rules"]) == 2


def test_tagstatus_any_rule_sorts_last(template) -> None:
    """ECR rejects a policy where the tagStatus=any rule is not lowest priority.

    The failure arrives at deploy time as an InvalidParameterException with no
    hint about which rule is wrong, so it is worth catching here.
    """
    rules = {r["selection"]["tagStatus"]: r["rulePriority"] for r in _lifecycle_json(template)["rules"]}
    assert rules["untagged"] < rules["any"]


def test_image_count_rule_carries_no_count_unit(template) -> None:
    """`countUnit` on an imageCountMoreThan rule is rejected by ECR's validator.

    It is a natural thing to add by symmetry with the sinceImagePushed rule, and
    the resulting error names neither the key nor the rule.
    """
    for rule in _lifecycle_json(template)["rules"]:
        if rule["selection"]["countType"] == "imageCountMoreThan":
            assert "countUnit" not in rule["selection"]
        if rule["selection"]["countType"] == "sinceImagePushed":
            assert rule["selection"]["countUnit"] == "days"


def test_keep_count_leaves_room_for_rollback(template) -> None:
    assert template.default("KeepLastNImages") == 30
    assert template.param("KeepLastNImages")["MinValue"] == 1, (
        "Zero would expire every image immediately, including the one currently "
        "running."
    )


# --- conditional wiring ------------------------------------------------------

def test_raw_policy_replaces_the_generated_one(template) -> None:
    body = template.prop("Repository", "LifecyclePolicy")["Fn::If"][1]
    inner = body["LifecyclePolicyText"]["Fn::If"]
    assert inner[0] == "HasRawLifecyclePolicy"
    assert inner[1] == {"Ref": "LifecyclePolicyText"}, (
        "A supplied raw policy must win outright — merging it with the generated "
        "rules would produce priority collisions."
    )


def test_supplying_a_raw_policy_is_enough_to_enable_lifecycle_management(template) -> None:
    """Setting LifecyclePolicyText alone must work.

    Requiring the caller to also flip EnableLifecyclePolicy is the kind of
    two-switch interface where the policy silently does not apply.
    """
    condition = template.conditions["HasLifecyclePolicy"]
    assert "Fn::Or" in condition


def test_kms_key_only_applies_under_kms_encryption(template) -> None:
    kms = template.prop("Repository", "EncryptionConfiguration.KmsKey")
    assert kms == {"Fn::If": ["UsesKms", {"Ref": "KmsKeyArn"}, {"Ref": "AWS::NoValue"}]}, (
        "Passing an empty KmsKey alongside AES256 fails validation."
    )


def test_cross_account_access_is_pull_only(template) -> None:
    policy = template.prop("Repository", "RepositoryPolicyText")["Fn::If"][1]
    actions = set(policy["Statement"][0]["Action"])
    assert "ecr:BatchGetImage" in actions
    assert "ecr:PutImage" not in actions, (
        "A consuming account with push rights can overwrite the tag it is about "
        "to deploy. Push belongs to whoever builds the image."
    )


def test_cross_account_policy_is_absent_when_no_accounts_listed(template) -> None:
    assert template.prop("Repository", "RepositoryPolicyText")["Fn::If"][2] == {"Ref": "AWS::NoValue"}


# --- interface ---------------------------------------------------------------

def test_there_is_no_environment_parameter_at_all(template) -> None:
    """One repository per image, not per environment — see the README.

    Every other template in the library takes `Environment`. This one does not,
    because an image is built once and promoted: dev, staging and prod deploy the
    same digest. A per-environment repository means prod runs bytes that were
    never tested anywhere, and adding the parameter "for consistency" is the
    first step toward that.
    """
    assert "Environment" not in template.parameters
    name = template.prop("Repository", "RepositoryName")
    assert name == {"Fn::Sub": "${NamePrefix}/${RepositorySuffix}"}
    assert "Environment" not in json.dumps(name)


def test_outputs_cover_push_and_iam(template) -> None:
    assert template.outputs["RepositoryUri"]["Value"] == {"Fn::GetAtt": ["Repository", "RepositoryUri"]}
    assert template.outputs["RepositoryArn"]["Value"] == {"Fn::GetAtt": ["Repository", "Arn"]}
