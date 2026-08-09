"""Assertions for serverless/http-api."""

from __future__ import annotations


def test_api_gateway_is_permitted_to_invoke_the_function(template) -> None:
    """The most common HTTP API misconfiguration, made unconditional.

    Without this permission every request returns 500 "Internal Server Error"
    with nothing in the function's logs, because the function is never invoked.
    """
    assert template.condition_on("InvokePermission") is None
    assert template.prop("InvokePermission", "Principal") == "apigateway.amazonaws.com"
    assert template.prop("InvokePermission", "SourceArn") == {
        "Fn::Sub": "arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${Api}/*"
    }, (
        "The SourceArn must name this API. Without it, any API Gateway in the "
        "account can invoke the function."
    )


def test_throttling_is_always_configured(template) -> None:
    settings = template.prop("Stage", "DefaultRouteSettings")
    assert settings["ThrottlingRateLimit"] == {"Ref": "ThrottlingRateLimit"}
    assert settings["ThrottlingBurstLimit"] == {"Ref": "ThrottlingBurstLimit"}
    assert template.default("ThrottlingRateLimit") == 100, (
        "An unthrottled HTTP API forwards a scraper's traffic to your function "
        "and bills per invocation."
    )


def test_access_logs_capture_integration_failures(template) -> None:
    """`status` alone cannot distinguish a failing function from an unreachable one."""
    fmt = template.prop("Stage", "AccessLogSettings.Format")
    for field in ("$context.integrationStatus", "$context.integrationErrorMessage", "$context.requestId"):
        assert field in fmt, f"the access log format must include {field}"
    assert template.deletion_policy("AccessLogGroup") == "Retain"


def test_authorizer_wiring_is_all_or_nothing(template) -> None:
    assert template.prop("DefaultRoute", "AuthorizationType") == {
        "Fn::If": ["HasJwtAuthorizer", "JWT", "NONE"]
    }
    assert template.prop("DefaultRoute", "AuthorizerId") == {
        "Fn::If": ["HasJwtAuthorizer", {"Ref": "Authorizer"}, {"Ref": "AWS::NoValue"}]
    }, "AuthorizationType: NONE with an AuthorizerId set is rejected"


def test_jwt_authorizer_checks_the_audience_too(template) -> None:
    config = template.prop("Authorizer", "JwtConfiguration")
    assert config["Issuer"] == {"Ref": "JwtIssuer"}
    assert config["Audience"] == {"Ref": "JwtAudience"}, (
        "An authorizer that validates the issuer but not the audience accepts "
        "any token that issuer ever minted, for any application."
    )


def test_custom_domain_requires_modern_tls(template) -> None:
    config = template.prop("Domain", "DomainNameConfigurations.0")
    assert config["SecurityPolicy"] == "TLS_1_2"
    assert config["EndpointType"] == "REGIONAL"


def test_custom_domain_outputs_both_alias_fields(template) -> None:
    """A Route 53 alias record needs the target *and* its hosted zone ID."""
    assert template.outputs["CustomDomainTarget"]["Value"] == {
        "Fn::GetAtt": ["Domain", "RegionalDomainName"]
    }
    assert template.outputs["CustomDomainHostedZoneId"]["Value"] == {
        "Fn::GetAtt": ["Domain", "RegionalHostedZoneId"]
    }
    for name in ("CustomDomainTarget", "CustomDomainHostedZoneId"):
        assert template.outputs[name].get("Condition") == "HasCustomDomain"


def test_cors_is_absent_unless_an_origin_is_supplied(template) -> None:
    assert template.prop("Api", "CorsConfiguration")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
