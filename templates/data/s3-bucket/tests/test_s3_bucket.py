"""Assertions for data/s3-bucket."""

from __future__ import annotations

import pytest


def _rules(template) -> list:
    return template.prop("Bucket", "LifecycleConfiguration.Rules")


def _statement(template, sid: str):
    for statement in template.prop("BucketPolicy", "PolicyDocument.Statement"):
        if statement.get("Sid") == sid:
            return statement
        if "Fn::If" in statement and statement["Fn::If"][1].get("Sid") == sid:
            return statement["Fn::If"][1]
    return None


# --- the non-negotiables -----------------------------------------------------

@pytest.mark.parametrize(
    "flag", ["BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"]
)
def test_every_public_access_block_is_on_and_unconditional(template, flag: str) -> None:
    value = template.prop("Bucket", f"PublicAccessBlockConfiguration.{flag}")
    assert value is True, (
        f"{flag} must be a literal true, not a parameter. The account-level block "
        "is not guaranteed to be on, so every bucket sets its own and none of "
        "them offer a way to turn it off."
    )


def test_acls_are_disabled_entirely(template) -> None:
    ownership = template.prop("Bucket", "OwnershipControls.Rules.0.ObjectOwnership")
    assert ownership == "BucketOwnerEnforced", (
        "Essentially every public-bucket incident of the last decade routed "
        "through an ACL rather than a policy. BucketOwnerEnforced removes ACLs "
        "as a mechanism."
    )


def test_insecure_transport_is_denied_unconditionally(template) -> None:
    statement = _statement(template, "DenyInsecureTransport")
    assert statement is not None
    assert statement["Effect"] == "Deny"
    assert statement["Condition"]["Bool"]["aws:SecureTransport"] == "false"
    assert statement["Resource"] == [
        {"Fn::GetAtt": ["Bucket", "Arn"]},
        {"Fn::Sub": "${Bucket.Arn}/*"},
    ], (
        "The deny must cover both the bucket and its objects — a policy naming "
        "only the bucket ARN leaves every object reachable over plain HTTP."
    )


def test_bucket_survives_stack_deletion(template) -> None:
    assert template.deletion_policy("Bucket") == "Retain"
    assert template.resource("Bucket").get("UpdateReplacePolicy") == "Retain"


# --- naming ------------------------------------------------------------------

def test_bucket_name_is_globally_unique_by_construction(template) -> None:
    assert template.prop("Bucket", "BucketName") == {
        "Fn::Sub": "${NamePrefix}-${Environment}-${BucketSuffix}-${AWS::AccountId}-${AWS::Region}"
    }, (
        "Bucket names are unique across every AWS customer, not per account. "
        "Without the account and region suffix, a short name is already taken."
    )


# --- encryption --------------------------------------------------------------

def test_encryption_defaults_to_free_sse_s3(template) -> None:
    algorithm = template.prop(
        "Bucket", "BucketEncryption.ServerSideEncryptionConfiguration.0.ServerSideEncryptionByDefault.SSEAlgorithm"
    )
    assert algorithm == {"Fn::If": ["UsesKms", "aws:kms", "AES256"]}


def test_bucket_keys_are_enabled_whenever_kms_is_used(template) -> None:
    """One data key per bucket instead of one per object.

    On a write-heavy bucket this is the difference between a negligible KMS bill
    and a startling one, and it is a single property nobody remembers.
    """
    bucket_key = template.prop(
        "Bucket", "BucketEncryption.ServerSideEncryptionConfiguration.0.BucketKeyEnabled"
    )
    assert bucket_key == {"Fn::If": ["UsesKms", True, {"Ref": "AWS::NoValue"}]}


# --- lifecycle ---------------------------------------------------------------

def test_incomplete_uploads_are_always_cleaned_up(template) -> None:
    rule = _rules(template)[0]
    assert rule["Id"] == "abort-incomplete-multipart-uploads"
    assert rule["Status"] == "Enabled"
    assert "Fn::If" not in rule, (
        "Orphaned multipart parts are billed as storage and are invisible in the "
        "console object listing. There is no configuration where leaving them is "
        "correct, so this rule is unconditional."
    )


def test_versioning_is_on_and_bounded(template) -> None:
    assert template.default("Versioning") == "Enabled", (
        "Versioning is the only protection against an application bug that "
        "overwrites data."
    )
    noncurrent = next(r for r in _rules(template) if isinstance(r, dict) and "Fn::If" in r
                      and r["Fn::If"][1].get("Id") == "expire-noncurrent-versions")
    assert noncurrent["Fn::If"][0] == "IsVersioned", (
        "A noncurrent-version rule on an unversioned bucket is silently useless; "
        "worse, versioning with no expiry is unbounded storage growth."
    )
    assert template.default("ExpireNoncurrentVersionsAfterDays") == 30


def test_expensive_transitions_are_opt_in(template) -> None:
    for param in ("TransitionToInfrequentAccessDays", "TransitionToGlacierDays"):
        assert template.default(param) == 0, (
            f"{param} must default to off. STANDARD_IA has a 30-day minimum "
            "billing duration and a retrieval charge, so transitioning data that "
            "turns out to be warm costs more than leaving it in Standard."
        )


def test_object_expiry_is_opt_in(template) -> None:
    assert template.default("ExpireObjectsAfterDays") == 0, (
        "Deleting data by default is not a default anyone should inherit."
    )


# --- integrations ------------------------------------------------------------

def test_log_delivery_statements_are_scoped_to_this_account(template) -> None:
    """Without aws:SourceAccount, another account can name your bucket as its
    log destination and AWS will honour it."""
    for sid in ("AllowAlbLogDelivery", "AllowServiceLogDelivery"):
        statement = _statement(template, sid)
        assert statement is not None, f"{sid} is missing"
        assert statement["Condition"]["StringEquals"]["aws:SourceAccount"] == {"Ref": "AWS::AccountId"}
        assert statement["Action"] == "s3:PutObject", (
            f"{sid} must grant writes only — a log delivery principal has no "
            "reason to read the bucket."
        )


def test_eventbridge_is_the_notification_mechanism(template) -> None:
    assert template.prop("Bucket", "NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled") == {
        "Ref": "EnableEventBridge"
    }, (
        "EventBridge keeps the bucket unaware of its consumers, so adding a "
        "second trigger later does not mean modifying the bucket."
    )


def test_cors_is_absent_unless_an_origin_is_given(template) -> None:
    assert template.prop("Bucket", "CorsConfiguration")["Fn::If"][2] == {"Ref": "AWS::NoValue"}


# --- interface ---------------------------------------------------------------

def test_outputs_cover_iam_and_cloudfront(template) -> None:
    assert template.outputs["BucketArn"]["Value"] == {"Fn::GetAtt": ["Bucket", "Arn"]}
    assert template.outputs["BucketDomainName"]["Value"] == {
        "Fn::GetAtt": ["Bucket", "RegionalDomainName"]
    }, "a CloudFront origin needs the regional domain, not the global one"
