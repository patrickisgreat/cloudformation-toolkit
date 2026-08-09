"""Security policy baseline, enforced over every template in the library.

Read `policy_lib.py` first — it explains the rule/finding/exemption model and
why rules resolve `Ref`s to parameter *defaults*.

Each rule below states what it checks and why the default was chosen. When a rule
fires, the failure message is written for someone who just tripped it and does
not yet know what they broke, which is the same standard `docs/TESTING.md` sets
for assertion messages.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cfn_loader import Template
from policy_lib import (
    ACCOUNT_ID_RE,
    MISSING,
    RULES,
    SECRETISH_RE,
    SELF_SCOPED_POLICY_KINDS,
    Exemption,
    Finding,
    as_list,
    iam_documents,
    literals,
    load_exemptions,
    resolve,
    resolves_in,
    resolves_true,
    rule,
    statements,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXEMPTIONS_PATH = Path(__file__).parent / "policy_exemptions.yaml"


def _key(t: Template) -> str:
    """The path a template is identified by in the exemption ledger."""
    return str(t.path.parent.relative_to(REPO_ROOT))


def _get(t: Template, logical_id: str, path: str, default=MISSING):
    return t.prop(logical_id, path, default=default)


# --- storage ----------------------------------------------------------------


@rule(
    "S3_ENCRYPTION",
    "S3 buckets declare server-side encryption",
    "S3 applies SSE-S3 implicitly, but an implicit default is not a reviewable "
    "one: it does not appear in the template, so nobody can tell whether the "
    "author considered it. Declare it.",
)
def s3_encryption(t: Template) -> list[Finding]:
    return [
        Finding(rid, "no BucketEncryption block")
        for rid in t.of_type("AWS::S3::Bucket")
        if _get(t, rid, "BucketEncryption", None) is None
    ]


@rule(
    "S3_PUBLIC_ACCESS_BLOCK",
    "S3 buckets block all four kinds of public access",
    "A bucket that is private today becomes public the first time someone "
    "attaches a well-meaning ACL. The account-level block is not guaranteed to "
    "be on, so every bucket sets its own.",
)
def s3_public_access(t: Template) -> list[Finding]:
    flags = (
        "BlockPublicAcls", "BlockPublicPolicy",
        "IgnorePublicAcls", "RestrictPublicBuckets",
    )
    findings = []
    for rid in t.of_type("AWS::S3::Bucket"):
        for flag in flags:
            value = _get(t, rid, f"PublicAccessBlockConfiguration.{flag}", None)
            if not resolves_true(t, value):
                findings.append(Finding(rid, f"PublicAccessBlockConfiguration.{flag} is not true"))
    return findings


@rule(
    "S3_TLS_ONLY",
    "S3 buckets deny non-TLS requests via a bucket policy",
    "Bucket encryption protects data at rest. Without an aws:SecureTransport "
    "deny, the same object is still readable over plain HTTP in transit.",
)
def s3_tls_only(t: Template) -> list[Finding]:
    policies_by_bucket: dict[str, list[dict]] = {}
    for rid, resource in t.of_type("AWS::S3::BucketPolicy").items():
        bucket = (resource.get("Properties") or {}).get("Bucket")
        target = bucket.get("Ref") if isinstance(bucket, dict) else bucket
        if isinstance(target, str):
            policies_by_bucket.setdefault(target, []).append(
                (resource.get("Properties") or {}).get("PolicyDocument") or {}
            )

    findings = []
    for rid in t.of_type("AWS::S3::Bucket"):
        docs = policies_by_bucket.get(rid, [])
        if not any(_denies_insecure_transport(doc) for doc in docs):
            findings.append(
                Finding(rid, "no bucket policy denying requests where aws:SecureTransport is false")
            )
    return findings


def _denies_insecure_transport(doc: dict) -> bool:
    for statement in statements(doc):
        if statement.get("Effect") != "Deny":
            continue
        condition = statement.get("Condition") or {}
        for operator in ("Bool", "BoolIfExists"):
            value = (condition.get(operator) or {}).get("aws:SecureTransport")
            if str(value).lower() == "false":
                return True
    return False


@rule(
    "STATEFUL_DELETION_POLICY",
    "Stateful resources declare DeletionPolicy and UpdateReplacePolicy",
    "CloudFormation's default is Delete. A stack rollback, a rename, or an "
    "immutable-property change will silently destroy the data unless the "
    "template says otherwise — and the failure is unrecoverable.",
)
def stateful_deletion_policy(t: Template) -> list[Finding]:
    stateful = (
        "AWS::S3::Bucket",
        "AWS::RDS::DBInstance",
        "AWS::RDS::DBCluster",
        "AWS::DynamoDB::Table",
        "AWS::DynamoDB::GlobalTable",
        "AWS::EFS::FileSystem",
        "AWS::ElastiCache::ReplicationGroup",
        "AWS::OpenSearchService::Domain",
        "AWS::DocDB::DBCluster",
        "AWS::Redshift::Cluster",
        "AWS::KMS::Key",
    )
    findings = []
    for rid, resource in t.of_type(*stateful).items():
        for key in ("DeletionPolicy", "UpdateReplacePolicy"):
            if not resource.get(key):
                findings.append(Finding(rid, f"no {key}"))
    return findings


@rule(
    "EFS_ENCRYPTION",
    "EFS file systems are encrypted at rest",
    "EFS is not encrypted unless asked, and the property is immutable — "
    "retrofitting it means creating a new file system and copying the data.",
)
def efs_encryption(t: Template) -> list[Finding]:
    return [
        Finding(rid, "Encrypted is not true")
        for rid in t.of_type("AWS::EFS::FileSystem")
        if not resolves_true(t, _get(t, rid, "Encrypted", None))
    ]


# --- messaging --------------------------------------------------------------


@rule(
    "SQS_ENCRYPTION",
    "SQS queues are encrypted at rest",
    "Queue bodies routinely carry the payloads that made the request "
    "interesting — identifiers, addresses, prompts. Encrypt them.",
)
def sqs_encryption(t: Template) -> list[Finding]:
    findings = []
    for rid in t.of_type("AWS::SQS::Queue"):
        managed = _get(t, rid, "SqsManagedSseEnabled", None)
        kms = _get(t, rid, "KmsMasterKeyId", None)
        if not resolves_true(t, managed) and kms is None:
            findings.append(Finding(rid, "neither SqsManagedSseEnabled nor KmsMasterKeyId is set"))
    return findings


@rule(
    "SNS_ENCRYPTION",
    "SNS topics are encrypted at rest",
    "Same reasoning as SQS: the message body is the payload. SNS needs a KMS "
    "key (there is no SNS-managed SSE toggle).",
)
def sns_encryption(t: Template) -> list[Finding]:
    return [
        Finding(rid, "no KmsMasterKeyId")
        for rid in t.of_type("AWS::SNS::Topic")
        if _get(t, rid, "KmsMasterKeyId", None) is None
    ]


# --- observability ----------------------------------------------------------


@rule(
    "LOG_RETENTION",
    "Log groups set an explicit retention",
    "A log group with no RetentionInDays keeps logs forever and bills forever. "
    "Retention is a decision; make it in the template.",
)
def log_retention(t: Template) -> list[Finding]:
    return [
        Finding(rid, "no RetentionInDays")
        for rid in t.of_type("AWS::Logs::LogGroup")
        if _get(t, rid, "RetentionInDays", None) is None
    ]


# --- identity ---------------------------------------------------------------


@rule(
    "IAM_NO_ADMIN",
    "No IAM statement grants every action on every resource",
    "`Action: '*'` on `Resource: '*'` is account takeover written as YAML. If a "
    "role genuinely needs breadth, enumerate the services.",
)
def iam_no_admin(t: Template) -> list[Finding]:
    findings = []
    for rid, _kind, doc in iam_documents(t):
        for statement in statements(doc):
            if statement.get("Effect") != "Allow":
                continue
            actions = [a for a in as_list(statement.get("Action")) if isinstance(a, str)]
            resources = [r for r in as_list(statement.get("Resource")) if isinstance(r, str)]
            if "*" in actions and "*" in resources:
                findings.append(Finding(rid, "Allow Action:* on Resource:*"))
    return findings


@rule(
    "IAM_NO_UNSCOPED_WILDCARD",
    "Service-wide wildcard actions are scoped to specific resources",
    "`s3:*` on `Resource: '*'` reads as narrow and is not — it covers every "
    "bucket in the account. Wildcard verbs are fine; wildcard verbs on wildcard "
    "resources are not.",
)
def iam_no_unscoped_wildcard(t: Template) -> list[Finding]:
    findings = []
    for rid, kind, doc in iam_documents(t):
        # In a document attached to the resource it governs — a KMS key policy —
        # `Resource: "*"` means "this key", and AWS rejects any other value.
        # Flagging it would push authors toward an exemption for the only legal
        # spelling, which is how a policy suite loses its credibility.
        if kind in SELF_SCOPED_POLICY_KINDS:
            continue
        for statement in statements(doc):
            if statement.get("Effect") != "Allow":
                continue
            actions = [a for a in as_list(statement.get("Action")) if isinstance(a, str)]
            resources = as_list(statement.get("Resource"))
            unscoped = any(r == "*" for r in resources if isinstance(r, str))
            if not unscoped:
                continue
            wildcards = [a for a in actions if a.endswith(":*")]
            # A handful of actions genuinely have no resource to scope to; the
            # IAM docs list them as "resource type: not applicable".
            if wildcards and not statement.get("Condition"):
                findings.append(
                    Finding(rid, f"Allow {', '.join(sorted(wildcards))} on Resource:* with no Condition")
                )
    return findings


@rule(
    "SECRET_PARAM_NOECHO",
    "Secret-shaped parameters set NoEcho",
    "Without NoEcho, the value is readable forever in describe-stacks, the "
    "console, and every CI log that prints a parameter table.",
)
def secret_param_noecho(t: Template) -> list[Finding]:
    findings = []
    for name, spec in t.parameters.items():
        if not SECRETISH_RE.search(name):
            continue
        # A parameter with an enumerated value set is a switch, not a secret —
        # `EnableSecretsManagerEndpoint: true|false` says nothing worth hiding.
        if spec.get("AllowedValues"):
            continue
        if not spec.get("NoEcho"):
            findings.append(Finding(name, "secret-shaped parameter without NoEcho: true"))
    return findings


@rule(
    "NO_HARDCODED_ACCOUNT_ID",
    "No AWS account IDs are baked into templates",
    "A template with an account ID in it only works in one account, which "
    "defeats the point of a reusable library. Use AWS::AccountId or a parameter.",
)
def no_hardcoded_account_id(t: Template) -> list[Finding]:
    findings = []
    for logical_id, resource in t.resources.items():
        for text in literals(resource):
            match = ACCOUNT_ID_RE.search(text)
            # AWS publishes a handful of well-known service account IDs (ELB
            # access-log delivery, for one) that are constants, not our account.
            if match and match.group() not in _WELL_KNOWN_AWS_ACCOUNTS:
                findings.append(Finding(logical_id, f"hardcoded account id {match.group()}"))
    return findings


# ELB access-log delivery accounts, per region. These are AWS's, published in
# the ELB docs, and are the correct literal to use in a bucket policy.
_WELL_KNOWN_AWS_ACCOUNTS = {
    "127311923021",  # us-east-1
    "033677994240",  # us-east-2
    "027434742980",  # us-west-1
    "797873946194",  # us-west-2
    "156460612806",  # eu-west-1
    "054676820928",  # eu-central-1
    "582318560864",  # ap-northeast-1
    "114774131450",  # ap-southeast-1
    "783225319266",  # ap-southeast-2
}


# --- network ----------------------------------------------------------------


@rule(
    "SG_NO_OPEN_INGRESS",
    "Security groups open 0.0.0.0/0 only on public web ports",
    "An internet-facing load balancer on 80/443 is the point. An open database "
    "port, SSH port, or model-server port is an incident.",
)
def sg_no_open_ingress(t: Template) -> list[Finding]:
    public_ports = {80, 443}
    findings = []

    def check(owner: str, entry: dict) -> None:
        # Resolve through Ref, so a parameter that *defaults* to 0.0.0.0/0 is
        # caught. A template that hides world-open ingress behind an
        # innocent-looking `IngressCidr` parameter is the common case, not the
        # hardcoded literal.
        cidr = resolve(t, entry.get("CidrIp"))
        cidr6 = resolve(t, entry.get("CidrIpv6"))
        if cidr != "0.0.0.0/0" and cidr6 != "::/0":
            return
        from_port = resolve(t, entry.get("FromPort"))
        to_port = resolve(t, entry.get("ToPort"))
        try:
            ports = {int(from_port), int(to_port)}
        except (TypeError, ValueError):
            findings.append(Finding(owner, "world-open ingress on a non-literal port range"))
            return
        if not ports <= public_ports:
            findings.append(
                Finding(owner, f"world-open ingress on ports {sorted(ports)} (only 80/443 allowed)")
            )

    for rid in t.of_type("AWS::EC2::SecurityGroup"):
        for entry in as_list(_get(t, rid, "SecurityGroupIngress", [])):
            if isinstance(entry, dict):
                check(rid, entry)
    for rid in t.of_type("AWS::EC2::SecurityGroupIngress"):
        check(rid, t.props(rid))
    return findings


@rule(
    "SG_RULE_DESCRIPTION",
    "Every security group rule carries a Description",
    "Six months on, an undescribed rule is undeletable: nobody can prove what "
    "it was for, so it stays. The description is what makes cleanup possible.",
)
def sg_rule_description(t: Template) -> list[Finding]:
    findings = []
    for rid in t.of_type("AWS::EC2::SecurityGroup"):
        for key in ("SecurityGroupIngress", "SecurityGroupEgress"):
            for index, entry in enumerate(as_list(_get(t, rid, key, []))):
                if isinstance(entry, dict) and not entry.get("Description"):
                    findings.append(Finding(rid, f"{key}[{index}] has no Description"))
    for type_name in ("AWS::EC2::SecurityGroupIngress", "AWS::EC2::SecurityGroupEgress"):
        for rid in t.of_type(type_name):
            if not _get(t, rid, "Description", None):
                findings.append(Finding(rid, "no Description"))
    return findings


@rule(
    "CLOUDFRONT_TLS",
    "CloudFront distributions require modern TLS and redirect HTTP",
    "A distribution that accepts TLS 1.0 or serves plain HTTP undoes the "
    "certificate it is holding.",
)
def cloudfront_tls(t: Template) -> list[Finding]:
    modern = {"TLSv1.2_2019", "TLSv1.2_2021", "TLSv1.3_2025"}
    https = {"redirect-to-https", "https-only"}
    findings = []
    for rid in t.of_type("AWS::CloudFront::Distribution"):
        viewer_cert = _get(t, rid, "DistributionConfig.ViewerCertificate", None)
        if isinstance(viewer_cert, dict) and not viewer_cert.get("CloudFrontDefaultCertificate"):
            if not resolves_in(t, viewer_cert.get("MinimumProtocolVersion"), modern):
                findings.append(Finding(rid, "ViewerCertificate.MinimumProtocolVersion is below TLS 1.2"))
        policy = _get(t, rid, "DistributionConfig.DefaultCacheBehavior.ViewerProtocolPolicy", None)
        if not resolves_in(t, policy, https):
            findings.append(Finding(rid, f"DefaultCacheBehavior.ViewerProtocolPolicy is {policy!r}"))
    return findings


# --- databases and caches ---------------------------------------------------


@rule(
    "RDS_ENCRYPTION",
    "RDS clusters and instances are encrypted at rest",
    "StorageEncrypted cannot be turned on in place — an unencrypted cluster has "
    "to be snapshotted, copied with a key, and restored. Get it right at create.",
)
def rds_encryption(t: Template) -> list[Finding]:
    findings = []
    for rid, resource in t.of_type("AWS::RDS::DBCluster", "AWS::RDS::DBInstance").items():
        props = resource.get("Properties", {}) or {}
        # An instance that is a member of an encrypted cluster inherits the
        # cluster's setting and must not declare its own.
        if props.get("DBClusterIdentifier"):
            continue
        if not resolves_true(t, props.get("StorageEncrypted")):
            findings.append(Finding(rid, "StorageEncrypted is not true"))
    return findings


@rule(
    "RDS_NOT_PUBLIC",
    "RDS instances are not publicly accessible",
    "PubliclyAccessible puts a database on a routable address. Reach it from "
    "inside the VPC, or through a bastion, never from the internet.",
)
def rds_not_public(t: Template) -> list[Finding]:
    return [
        Finding(rid, "PubliclyAccessible is true")
        for rid in t.of_type("AWS::RDS::DBInstance")
        if resolves_true(t, _get(t, rid, "PubliclyAccessible", None))
    ]


@rule(
    "DDB_ENCRYPTION",
    "DynamoDB tables declare encryption and point-in-time recovery",
    "PITR is the only thing standing between a bad migration and permanent data "
    "loss; it is off unless asked for, and it cannot be applied retroactively.",
)
def ddb_protection(t: Template) -> list[Finding]:
    findings = []
    for rid in t.of_type("AWS::DynamoDB::Table"):
        if not resolves_true(t, _get(t, rid, "SSESpecification.SSEEnabled", None)):
            findings.append(Finding(rid, "SSESpecification.SSEEnabled is not true"))
        pitr = _get(t, rid, "PointInTimeRecoverySpecification.PointInTimeRecoveryEnabled", None)
        if not resolves_true(t, pitr):
            findings.append(Finding(rid, "PointInTimeRecoveryEnabled is not true by default"))
    return findings


@rule(
    "ELASTICACHE_ENCRYPTION",
    "ElastiCache replication groups encrypt at rest and in transit",
    "A cache holds whatever the application put in it — sessions, tokens, "
    "rendered PII. Both toggles are create-time only.",
)
def elasticache_encryption(t: Template) -> list[Finding]:
    findings = []
    for rid in t.of_type("AWS::ElastiCache::ReplicationGroup"):
        for prop in ("AtRestEncryptionEnabled", "TransitEncryptionEnabled"):
            if not resolves_true(t, _get(t, rid, prop, None)):
                findings.append(Finding(rid, f"{prop} is not true"))
    return findings


@rule(
    "OPENSEARCH_ENCRYPTION",
    "OpenSearch domains encrypt at rest and node-to-node",
    "Search indexes are a copy of the source data with the access controls "
    "stripped off. Encrypt them the same way.",
)
def opensearch_encryption(t: Template) -> list[Finding]:
    findings = []
    for rid in t.of_type("AWS::OpenSearchService::Domain"):
        if not resolves_true(t, _get(t, rid, "EncryptionAtRestOptions.Enabled", None)):
            findings.append(Finding(rid, "EncryptionAtRestOptions.Enabled is not true"))
        if not resolves_true(t, _get(t, rid, "NodeToNodeEncryptionOptions.Enabled", None)):
            findings.append(Finding(rid, "NodeToNodeEncryptionOptions.Enabled is not true"))
    return findings


# --- keys, registries, compute ---------------------------------------------


@rule(
    "KMS_KEY_ROTATION",
    "Customer-managed KMS keys rotate automatically",
    "Annual rotation is one property and bounds the blast radius of a leaked "
    "key. There is no reason to leave it off.",
)
def kms_key_rotation(t: Template) -> list[Finding]:
    return [
        Finding(rid, "EnableKeyRotation is not true")
        for rid in t.of_type("AWS::KMS::Key")
        if not resolves_true(t, _get(t, rid, "EnableKeyRotation", None))
    ]


@rule(
    "ECR_IMMUTABLE_AND_SCANNED",
    "ECR repositories use immutable tags and scan on push",
    "Mutable tags let the digest behind `:latest` change under a running "
    "service, so what you tested is not what is serving traffic.",
)
def ecr_hardening(t: Template) -> list[Finding]:
    findings = []
    for rid in t.of_type("AWS::ECR::Repository"):
        if not resolves_in(t, _get(t, rid, "ImageTagMutability", None), {"IMMUTABLE"}):
            findings.append(Finding(rid, "ImageTagMutability is not IMMUTABLE by default"))
        scan = _get(t, rid, "ImageScanningConfiguration.ScanOnPush", None)
        if not resolves_true(t, scan):
            findings.append(Finding(rid, "ImageScanningConfiguration.ScanOnPush is not true"))
    return findings


@rule(
    "EBS_ENCRYPTION",
    "EBS volumes in launch templates are encrypted",
    "GPU and build hosts write model weights, checkpoints, and source to their "
    "root volume. Encrypt the volume that holds them.",
)
def ebs_encryption(t: Template) -> list[Finding]:
    findings = []
    for rid in t.of_type("AWS::EC2::LaunchTemplate"):
        mappings = _get(t, rid, "LaunchTemplateData.BlockDeviceMappings", [])
        for index, mapping in enumerate(as_list(mappings)):
            if not isinstance(mapping, dict):
                continue
            ebs = mapping.get("Ebs") or {}
            if not resolves_true(t, ebs.get("Encrypted")):
                findings.append(Finding(rid, f"BlockDeviceMappings[{index}].Ebs.Encrypted is not true"))
    return findings


# --- the sweep --------------------------------------------------------------

EXEMPTIONS: list[Exemption] = load_exemptions(EXEMPTIONS_PATH)


@pytest.mark.parametrize("rule_id", sorted(RULES), ids=sorted(RULES))
def test_policy_rule(any_template: Template, rule_id: str) -> None:
    spec = RULES[rule_id]
    key = _key(any_template)
    findings = [
        f for f in spec.fn(any_template)
        if not any(e.matches(key, rule_id, f) for e in EXEMPTIONS)
    ]
    if findings:
        detail = "\n".join(f"    {f.resource}: {f.reason}" for f in findings)
        pytest.fail(
            f"{key} violates {rule_id} ({spec.title}):\n{detail}\n\n"
            f"  Why this rule exists: {spec.why}\n"
            f"  Fix the template, or add a justified entry to "
            f"tests/policy_exemptions.yaml.",
            pytrace=False,
        )


def test_every_exemption_is_still_needed() -> None:
    """An exemption that no longer suppresses anything is stale — delete it.

    Without this, the ledger only grows, and a rule can be silently defanged by
    an exemption written for a template that has since been fixed.
    """
    from conftest import all_dirs, load  # local import: conftest is repo-root

    live = set()
    for directory in all_dirs():
        t = load(directory / "template.yaml")
        key = _key(t)
        for rule_id, spec in RULES.items():
            for finding in spec.fn(t):
                for exemption in EXEMPTIONS:
                    if exemption.matches(key, rule_id, finding):
                        live.add(exemption)

    stale = [e for e in EXEMPTIONS if e not in live]
    assert not stale, (
        "these exemptions no longer suppress any finding — the template was "
        "fixed, renamed, or deleted. Remove them from "
        "tests/policy_exemptions.yaml:\n"
        + "\n".join(f"    {e.template} / {e.rule} / {e.resource}" for e in stale)
    )
