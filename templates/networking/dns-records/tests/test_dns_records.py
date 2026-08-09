"""Assertions for networking/dns-records."""

from __future__ import annotations

import re


def test_alias_and_plain_records_are_separate_resources(template) -> None:
    """One resource with Fn::If would not work here.

    An alias record may not carry TTL or ResourceRecords, and CloudFormation
    enforces that structurally — a single resource declaring all of them is
    rejected before the conditions are ever evaluated.
    """
    assert template.condition_on("AliasRecord") == "IsAlias"
    assert template.condition_on("PlainRecord") == "IsPlainRecord"
    assert not template.has_prop("AliasRecord", "TTL")
    assert not template.has_prop("AliasRecord", "ResourceRecords")
    assert not template.has_prop("PlainRecord", "AliasTarget")


def test_alias_uses_the_targets_own_hosted_zone(template) -> None:
    """The record's zone and the target's zone are different things.

    Both parameters are zone IDs and only one of them is yours; using the wrong
    one produces a record that resolves to nothing, with no deploy-time error.
    """
    assert template.prop("AliasRecord", "AliasTarget.HostedZoneId") == {
        "Ref": "AliasTargetHostedZoneId"
    }
    assert template.prop("AliasRecord", "HostedZoneId") == {"Ref": "HostedZoneId"}


def test_alias_evaluates_target_health(template) -> None:
    assert template.prop("AliasRecord", "AliasTarget.EvaluateTargetHealth") is True


def test_record_name_must_be_fully_qualified(template) -> None:
    """Route 53 appends the zone name to a bare label, giving api.example.com.example.com."""
    pattern = template.param("RecordName")["AllowedPattern"]
    assert re.fullmatch(pattern, "api.example.com")
    assert re.fullmatch(pattern, "*.example.com")
    assert not re.fullmatch(pattern, "api"), "a bare label must be rejected"


def test_health_check_is_opt_in(template) -> None:
    assert template.default("EnableHealthCheck") == "false", (
        "On a single record a health check observes without changing anything; "
        "it only does work as part of a failover or weighted set."
    )
    assert template.condition_on("HealthCheck") == "ShouldCreateHealthCheck"
    assert template.outputs["HealthCheckId"].get("Condition") == "ShouldCreateHealthCheck"


def test_health_check_uses_https(template) -> None:
    config = template.prop("HealthCheck", "HealthCheckConfig")
    assert config["Type"] == "HTTPS"
    assert config["Port"] == 443
    assert config["FullyQualifiedDomainName"] == {"Ref": "RecordName"}
