"""Assertions for networking/acm-certificate."""

from __future__ import annotations

import re


def test_validation_is_dns_and_not_configurable(template) -> None:
    """Email validation needs a human to click a link every 13 months.

    When nobody does, the certificate silently expires and the first symptom is
    a browser warning in production.
    """
    assert template.prop("Certificate", "ValidationMethod") == "DNS"
    assert not any("validation" in name.lower() for name in template.parameters)


def test_every_name_is_validated_in_the_hosted_zone(template) -> None:
    """A SAN with no matching DomainValidationOptions entry leaves the stack
    waiting for a record CloudFormation never wrote."""
    options = template.prop("Certificate", "DomainValidationOptions")
    assert options[0] == {
        "DomainName": {"Ref": "DomainName"},
        "HostedZoneId": {"Ref": "HostedZoneId"},
    }
    for entry in options[1:]:
        assert entry["Fn::If"][1]["HostedZoneId"] == {"Ref": "HostedZoneId"}
        assert entry["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_sans_and_validation_options_stay_in_step(template) -> None:
    sans = template.prop("Certificate", "SubjectAlternativeNames")
    conditions = [entry["Fn::If"][0] for entry in sans]
    assert conditions == ["HasWildcard", "HasAdditionalDomain"]
    options = template.prop("Certificate", "DomainValidationOptions")
    assert [entry["Fn::If"][0] for entry in options[1:]] == conditions


def test_wildcard_is_derived_from_the_primary_domain(template) -> None:
    assert template.prop("Certificate", "SubjectAlternativeNames.0")["Fn::If"][1] == {
        "Fn::Sub": "*.${DomainName}"
    }


def test_hosted_zone_is_a_typed_parameter(template) -> None:
    assert template.param("HostedZoneId")["Type"] == "AWS::Route53::HostedZone::Id", (
        "A typed parameter is validated before the deploy starts. An untyped "
        "one fails by hanging in CREATE_IN_PROGRESS until it times out."
    )


def test_domain_pattern_rejects_obvious_mistakes(template) -> None:
    pattern = template.param("DomainName")["AllowedPattern"]
    assert re.fullmatch(pattern, "api.example.com")
    assert re.fullmatch(pattern, "*.example.com")
    assert not re.fullmatch(pattern, "https://api.example.com"), (
        "A URL rather than a hostname is the common paste error."
    )
    assert not re.fullmatch(pattern, "API.example.com"), "ACM domains are lowercase"
