"""Assertions for foundation/vpc. See docs/TESTING.md for the categories."""

from __future__ import annotations

import pytest


# --- secure and sane defaults -----------------------------------------------

def test_dns_is_on_so_endpoints_and_rds_resolve(template) -> None:
    assert template.prop("Vpc", "EnableDnsSupport") is True
    assert template.prop("Vpc", "EnableDnsHostnames") is True, (
        "Interface endpoints with PrivateDnsEnabled, and RDS/ElastiCache private "
        "addresses, all silently fail to resolve without DNS hostnames on the VPC."
    )


def test_private_subnets_do_not_auto_assign_public_ips(template) -> None:
    for subnet in ("PrivateSubnet1", "PrivateSubnet2", "PrivateSubnet3"):
        assert template.prop(subnet, "MapPublicIpOnLaunch") is False, (
            f"{subnet} must not auto-assign public IPs — a 'private' subnet whose "
            "instances get public addresses is public with extra steps."
        )


def test_public_subnets_auto_assign_public_ips(template) -> None:
    for subnet in ("PublicSubnet1", "PublicSubnet2", "PublicSubnet3"):
        assert template.prop(subnet, "MapPublicIpOnLaunch") is True


def test_default_nat_posture_is_the_cheapest_working_one(template) -> None:
    assert template.default("NatGatewayMode") == "single", (
        "Defaulting to per-az triples the monthly floor for every dev environment "
        "someone spins up; defaulting to none breaks any workload that talks to "
        "the public internet. Single is the cheapest thing that works."
    )


def test_free_gateway_endpoints_are_on_by_default(template) -> None:
    assert template.default("EnableS3Endpoint") == "true"
    assert template.default("EnableDynamoDbEndpoint") == "true", (
        "Gateway endpoints cost nothing and take traffic off the NAT gateway, so "
        "leaving them off is a pure loss."
    )


def test_paid_interface_endpoints_are_off_by_default(template) -> None:
    for param in (
        "EnableEcrEndpoints",
        "EnableLogsEndpoint",
        "EnableSecretsManagerEndpoint",
        "EnableSsmEndpoints",
    ):
        assert template.default(param) == "false", (
            f"{param} provisions endpoints at roughly $7/month per AZ. Anything "
            "with a recurring cost is opt-in."
        )


def test_flow_logs_retain_and_bound_retention(template) -> None:
    assert template.deletion_policy("FlowLogGroup") == "Retain"
    assert template.prop("FlowLogGroup", "RetentionInDays") == {"Ref": "FlowLogRetentionDays"}
    assert template.default("FlowLogRetentionDays") == 30


# --- conditional wiring ------------------------------------------------------

def test_third_az_resources_are_all_conditional(template) -> None:
    """Nothing in the third AZ may be created unconditionally.

    A resource that forgets `Condition: HasThreeAzs` fails at deploy time with a
    CIDR or AZ error only in two-AZ mode — the configuration most people use.
    """
    for logical_id in (
        "PublicSubnet3",
        "PrivateSubnet3",
        "PrivateRouteTable3",
        "PublicSubnet3RouteTableAssociation",
        "PrivateSubnet3RouteTableAssociation",
    ):
        assert template.condition_on(logical_id) == "HasThreeAzs", (
            f"{logical_id} must be guarded by HasThreeAzs."
        )


def test_nat_resources_scale_with_the_mode(template) -> None:
    assert template.condition_on("NatGateway1") == "HasNat"
    assert template.condition_on("NatGateway2") == "HasNatPerAz", (
        "The second NAT gateway exists only in per-az mode — creating it in "
        "single mode would double the cost of the cheap option."
    )
    assert template.condition_on("NatGateway3") == "HasNatInAz3", (
        "The third NAT gateway needs both per-az mode and a third AZ."
    )
    for eip, gateway in (("NatEip1", "NatGateway1"), ("NatEip2", "NatGateway2"), ("NatEip3", "NatGateway3")):
        assert template.condition_on(eip) == template.condition_on(gateway), (
            f"{eip} and {gateway} must share a condition, or the stack allocates an "
            "Elastic IP with nothing attached to it — which AWS bills for."
        )


def test_single_nat_mode_routes_every_az_through_the_one_gateway(template) -> None:
    route2 = template.prop("PrivateDefaultRoute2", "NatGatewayId")
    assert route2 == {"Fn::If": ["HasNatPerAz", {"Ref": "NatGateway2"}, {"Ref": "NatGateway1"}]}, (
        "In single mode, AZ 2's private subnet must fall back to NAT gateway 1; "
        "otherwise it has no egress at all."
    )


def test_private_routes_exist_only_when_there_is_a_nat(template) -> None:
    assert template.condition_on("PrivateDefaultRoute1") == "HasNat"
    assert template.condition_on("PrivateDefaultRoute3") == "HasPrivateRouteInAz3", (
        "AZ 3's default route needs both a NAT gateway and a third AZ to exist."
    )


def test_ssm_endpoints_come_as_a_pair(template) -> None:
    assert template.condition_on("SsmEndpoint") == "ShouldCreateSsmEndpoints"
    assert template.condition_on("SsmMessagesEndpoint") == "ShouldCreateSsmEndpoints", (
        "ECS Exec needs ssm and ssmmessages together. Creating one without the "
        "other fails at session time with an opaque TargetNotConnected."
    )


def test_endpoint_security_group_exists_whenever_an_interface_endpoint_does(template) -> None:
    assert template.condition_on("InterfaceEndpointSecurityGroup") == "HasInterfaceEndpoints"
    for endpoint in ("EcrApiEndpoint", "LogsEndpoint", "SecretsManagerEndpoint", "SsmEndpoint"):
        assert template.prop(endpoint, "SecurityGroupIds") == [
            {"Ref": "InterfaceEndpointSecurityGroup"}
        ]


# --- pass-through and interface ---------------------------------------------

def test_subnets_are_carved_from_the_vpc_cidr(template) -> None:
    """Public first, private second, no overlap — the ordering is load-bearing."""
    expected = {
        "PublicSubnet1": 0, "PublicSubnet2": 1, "PublicSubnet3": 2,
        "PrivateSubnet1": 3, "PrivateSubnet2": 4, "PrivateSubnet3": 5,
    }
    for subnet, index in expected.items():
        assert template.prop(subnet, "CidrBlock") == {
            "Fn::Select": [index, {"Fn::Cidr": [{"Ref": "VpcCidr"}, 6, 8]}]
        }, f"{subnet} must take block {index} of six carved from VpcCidr"


def test_subnets_are_spread_across_distinct_azs(template) -> None:
    for index, suffix in enumerate(("1", "2", "3")):
        for kind in ("Public", "Private"):
            assert template.prop(f"{kind}Subnet{suffix}", "AvailabilityZone") == {
                "Fn::Select": [index, {"Fn::GetAZs": ""}]
            }


def test_endpoint_security_group_only_admits_the_vpc(template) -> None:
    ingress = template.prop("InterfaceEndpointSecurityGroup", "SecurityGroupIngress")
    assert len(ingress) == 1
    assert ingress[0]["CidrIp"] == {"Ref": "VpcCidr"}, (
        "PrivateLink endpoints must be reachable from inside this VPC only."
    )
    assert ingress[0]["FromPort"] == 443 and ingress[0]["ToPort"] == 443


def test_vpc_cidr_pattern_rejects_ranges_too_small_to_carve(template) -> None:
    """The AllowedPattern has to reject anything Fn::Cidr cannot split six ways."""
    import re

    pattern = template.param("VpcCidr")["AllowedPattern"]
    assert re.fullmatch(pattern, "10.0.0.0/16")
    assert re.fullmatch(pattern, "172.31.0.0/20")
    assert not re.fullmatch(pattern, "10.0.0.0/25"), (
        "A /25 cannot be split into six /24s; Fn::Cidr fails at deploy time with "
        "an unhelpful message, so reject it at the parameter."
    )
    assert not re.fullmatch(pattern, "10.0.0.0/8"), (
        "A /8 is larger than a VPC is allowed to be (max /16)."
    )


@pytest.mark.parametrize(
    "output",
    ["VpcId", "VpcCidrBlock", "PublicSubnetIds", "PrivateSubnetIds", "PrivateRouteTableIds"],
)
def test_composition_outputs_exist(template, output: str) -> None:
    """Every consumer template wires itself with these. Renaming one is breaking."""
    assert output in template.outputs


def test_subnet_id_outputs_adapt_to_the_az_count(template) -> None:
    value = template.outputs["PrivateSubnetIds"]["Value"]
    assert "Fn::If" in value and value["Fn::If"][0] == "HasThreeAzs", (
        "The subnet list output must contain exactly the subnets that exist, or a "
        "consumer gets a dangling reference in two-AZ mode."
    )
