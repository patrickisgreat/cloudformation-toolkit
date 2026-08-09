"""Assertions for containers/alb."""

from __future__ import annotations


def _attributes(template) -> dict:
    return {
        entry["Key"]: entry["Value"]
        for entry in template.prop("LoadBalancer", "LoadBalancerAttributes")
    }


# --- routing posture ---------------------------------------------------------

def test_https_listener_denies_by_default(template) -> None:
    """Nothing reaches a backend without an explicit rule.

    A default action that forwards means every unmatched host and path lands on
    whichever service happens to be the default — including scanner traffic and
    requests for services that were deleted.
    """
    action = template.prop("HttpsListener", "DefaultActions.0")
    assert action["Type"] == "fixed-response"
    assert action["FixedResponseConfig"]["StatusCode"] == "404"


def test_http_listener_redirects_when_tls_is_configured(template) -> None:
    action = template.prop("HttpListener", "DefaultActions.0")
    redirect = action["Fn::If"][1]
    assert redirect["Type"] == "redirect"
    config = redirect["RedirectConfig"]
    assert config["StatusCode"] == "HTTP_301"
    assert config["Protocol"] == "HTTPS"
    assert config["Host"] == "#{host}"
    assert config["Path"] == "/#{path}", (
        "A redirect that drops the path sends every deep link to the homepage."
    )
    assert config["Query"] == "#{query}"


def test_http_listener_falls_back_to_404_without_tls(template) -> None:
    fallback = template.prop("HttpListener", "DefaultActions.0")["Fn::If"][2]
    assert fallback["Type"] == "fixed-response", (
        "With no certificate there is nothing to redirect to, so port 80 must "
        "still deny by default rather than forward."
    )


def test_redirect_requires_a_certificate(template) -> None:
    """Redirecting to HTTPS with no HTTPS listener is a redirect loop to nowhere."""
    condition = template.conditions["ShouldRedirect"]
    assert "Fn::And" in condition


def test_combined_listener_output_hides_the_tls_branch(template) -> None:
    value = template.outputs["ListenerArn"]["Value"]
    assert value == {
        "Fn::If": ["HasCertificate", {"Ref": "HttpsListener"}, {"Ref": "HttpListener"}]
    }, (
        "Services attach rules to this output. Making them choose between two "
        "listener outputs pushes a conditional into every consumer."
    )


# --- secure defaults ---------------------------------------------------------

def test_tls_policy_excludes_everything_below_1_2(template) -> None:
    assert template.default("SslPolicy") == "ELBSecurityPolicy-TLS13-1-2-2021-06"
    for policy in template.allowed_values("SslPolicy"):
        assert "TLS13" in policy or "FS-1-2" in policy, (
            f"{policy} would permit TLS below 1.2."
        )


def test_invalid_header_fields_are_dropped(template) -> None:
    assert _attributes(template)["routing.http.drop_invalid_header_fields.enabled"] == "true"


def test_desync_mitigation_is_at_least_defensive(template) -> None:
    assert template.default("DesyncMitigationMode") == "defensive", (
        "`monitor` records request-smuggling shapes and forwards them anyway."
    )


def test_world_open_ingress_is_limited_to_web_ports(template) -> None:
    ingress = template.prop("SecurityGroup", "SecurityGroupIngress")
    ports = {(rule["FromPort"], rule["ToPort"]) for rule in ingress}
    assert ports == {(80, 80), (443, 443)}, (
        "IngressCidr defaults to 0.0.0.0/0, so the port set is the whole "
        "restriction. Anything beyond 80/443 here is publicly exposed."
    )
    for rule in ingress:
        assert rule["Description"], "every rule needs a Description to be removable later"
        assert rule["CidrIp"] == {"Ref": "IngressCidr"}


def test_egress_is_intentionally_unset(template) -> None:
    """Declaring any egress rule removes CloudFormation's default allow-all.

    The ALB must reach its targets on a port this template does not know, so
    restriction lives on the target's security group instead. Asserting the
    absence keeps someone from "tightening" this into an outage.
    """
    assert not template.has_prop("SecurityGroup", "SecurityGroupEgress")


# --- behaviour ---------------------------------------------------------------

def test_idle_timeout_is_adjustable_well_past_the_default(template) -> None:
    assert template.default("IdleTimeoutSeconds") == 60
    assert template.param("IdleTimeoutSeconds")["MaxValue"] == 4000, (
        "Streaming responses routinely exceed 60s; the ceiling has to allow for "
        "them or the fix is 'move off the ALB'."
    )


def test_access_log_keys_disappear_together(template) -> None:
    attributes = _attributes(template)
    assert attributes["access_logs.s3.enabled"] == {"Fn::If": ["HasAccessLogs", "true", "false"]}
    for key in ("access_logs.s3.bucket", "access_logs.s3.prefix"):
        assert attributes[key]["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
            f"{key} with an empty value is rejected when logging is disabled."
        )


def test_waf_association_is_opt_in(template) -> None:
    assert template.condition_on("WebAclAssociation") == "HasWebAcl"
    assert template.prop("WebAclAssociation", "ResourceArn") == {"Ref": "LoadBalancer"}


# --- interface ---------------------------------------------------------------

def test_alias_record_outputs_are_present(template) -> None:
    """A Route 53 alias needs both the DNS name and the canonical zone ID."""
    assert template.outputs["LoadBalancerDnsName"]["Value"] == {"Fn::GetAtt": ["LoadBalancer", "DNSName"]}
    assert template.outputs["LoadBalancerHostedZoneId"]["Value"] == {
        "Fn::GetAtt": ["LoadBalancer", "CanonicalHostedZoneID"]
    }


def test_subnets_are_typed_so_the_console_validates_them(template) -> None:
    assert template.param("SubnetIds")["Type"] == "List<AWS::EC2::Subnet::Id>", (
        "A typed parameter is validated before the deploy starts; a plain "
        "CommaDelimitedList fails 10 minutes in."
    )
    assert template.param("VpcId")["Type"] == "AWS::EC2::VPC::Id"
