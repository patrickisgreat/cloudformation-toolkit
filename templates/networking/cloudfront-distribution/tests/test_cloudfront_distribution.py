"""Assertions for networking/cloudfront-distribution."""

from __future__ import annotations

NOVALUE = {"Ref": "AWS::NoValue"}


# 1. Secure defaults -----------------------------------------------------------

def test_viewers_are_redirected_to_https(template) -> None:
    assert (
        template.prop("Distribution", "DistributionConfig.DefaultCacheBehavior.ViewerProtocolPolicy")
        == "redirect-to-https"
    ), (
        "allow-all serves the same content over plain HTTP, which undoes the "
        "certificate the distribution is holding. redirect keeps old http:// "
        "links working; https-only would break them with a 403."
    )


def test_custom_domains_require_modern_tls(template) -> None:
    cert = template.prop("Distribution", "DistributionConfig.ViewerCertificate")
    assert cert["MinimumProtocolVersion"]["Fn::If"] == ["HasCustomDomain", "TLSv1.2_2021", NOVALUE], (
        "With a custom certificate the TLS floor is ours to set, and anything "
        "below TLSv1.2_2021 accepts ciphers that fail compliance scans."
    )
    assert cert["CloudFrontDefaultCertificate"]["Fn::If"] == ["HasCustomDomain", NOVALUE, True], (
        "Without a custom domain the *.cloudfront.net certificate must be "
        "declared, or the distribution has no certificate at all."
    )


def test_s3_is_the_default_origin_type_and_uses_oac(template) -> None:
    assert template.default("OriginType") == "s3"
    origin = template.prop("Distribution", "DistributionConfig.Origins.0")
    assert origin["OriginAccessControlId"]["Fn::If"][0] == "IsS3Origin"
    assert origin["S3OriginConfig"]["Fn::If"][1] == {"OriginAccessIdentity": ""}, (
        "An empty OriginAccessIdentity is the documented way to say 'OAC only'. "
        "A legacy OAI here would bypass the sigv4 signing OAC provides."
    )
    assert template.condition_on("OriginAccessControl") == "IsS3Origin"


def test_custom_origins_are_reached_over_tls_only(template) -> None:
    config = template.prop("Distribution", "DistributionConfig.Origins.0.CustomOriginConfig")
    custom_branch = config["Fn::If"][2]
    assert custom_branch["OriginProtocolPolicy"] == "https-only", (
        "match-viewer or http-only downgrades the origin leg to plain HTTP, "
        "making the viewer-facing TLS policy theater."
    )
    assert custom_branch["OriginSSLProtocols"] == ["TLSv1.2"]


def test_price_class_defaults_to_the_cheapest(template) -> None:
    assert template.default("PriceClass") == "PriceClass_100", (
        "PriceClass_All raises the per-GB rate for traffic from the most "
        "expensive regions. Viewers outside the class still get served, just "
        "from a farther edge - so the cheap class is the right default."
    )


# 2. Conditional wiring --------------------------------------------------------

def test_spa_fallback_is_off_by_default_and_rewrites_both_error_codes(template) -> None:
    assert template.default("EnableSpaFallback") == "false", (
        "Rewriting 403/404 to index.html turns every broken asset link into a "
        "soft 200. Only an SPA wants that, so it is opt-in."
    )
    responses = template.prop("Distribution", "DistributionConfig.CustomErrorResponses")
    condition, enabled, disabled = responses["Fn::If"]
    assert condition == "HasSpaFallback"
    assert disabled == NOVALUE
    assert sorted(r["ErrorCode"] for r in enabled) == [403, 404], (
        "A private S3 origin returns 403, not 404, for missing keys - "
        "rewriting only 404 breaks the SPA it was meant to serve."
    )
    assert all(r["ResponsePagePath"] == "/index.html" for r in enabled)


def test_aliases_and_certificate_come_as_a_pair(template) -> None:
    """CloudFront rejects an alias the certificate does not cover, so one
    without the other must degrade to the default *.cloudfront.net setup
    rather than fail the deploy."""
    condition = template.conditions["HasCustomDomain"]
    checks = condition["Fn::And"]
    assert len(checks) == 2
    aliases = template.prop("Distribution", "DistributionConfig.Aliases")
    assert aliases["Fn::If"][0] == "HasCustomDomain"
    cert = template.prop("Distribution", "DistributionConfig.ViewerCertificate")
    assert cert["AcmCertificateArn"]["Fn::If"][0] == "HasCustomDomain"


def test_waf_hook_is_wired_and_off_by_default(template) -> None:
    assert template.default("WebAclArn") == ""
    assert template.prop("Distribution", "DistributionConfig.WebACLId")["Fn::If"] == [
        "HasWebAcl", {"Ref": "WebAclArn"}, NOVALUE,
    ]


# 3. Pass-through --------------------------------------------------------------

def test_cache_policy_reaches_the_default_behavior(template) -> None:
    assert template.prop(
        "Distribution", "DistributionConfig.DefaultCacheBehavior.CachePolicyId"
    ) == {"Ref": "CachePolicyId"}
    assert template.default("CachePolicyId") == "658327ea-f89d-4fab-a63d-7e88639e58f6", (
        "The managed CachingOptimized policy - right for the default S3/static "
        "origin. An API origin overrides this with CachingDisabled."
    )


# 4. Interface -----------------------------------------------------------------

def test_only_the_prefix_and_origin_are_required(template) -> None:
    assert template.required_parameters == ["NamePrefix", "OriginDomainName"]


def test_alias_target_outputs_come_in_the_pair_route53_needs(template) -> None:
    """A Route 53 alias record needs a DNS name *and* a hosted zone ID; export
    both so callers never hardcode CloudFront's well-known zone."""
    assert template.output("DistributionDomainName")
    assert template.output("DistributionHostedZoneId")["Value"] == "Z2FDTNDATAQYW2"
    assert template.output("OriginAccessControlId").get("Condition") == "IsS3Origin", (
        "An output referencing a conditional resource must carry the same "
        "Condition, or a custom-origin stack fails to create."
    )
