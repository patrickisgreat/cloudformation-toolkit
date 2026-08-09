"""Assertions for the container-service stack.

A stack's job is wiring, so these tests are about wiring: that every child is a
library template rather than an inline resource, and that outputs are connected
to the right inputs. A mistyped GetAtt here fails 15 minutes into a deploy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

CHILDREN = {
    "Network": "templates/foundation/vpc/template.yaml",
    "Registry": "templates/containers/ecr-repository/template.yaml",
    "Cluster": "templates/containers/ecs-cluster/template.yaml",
    "Certificate": "templates/networking/acm-certificate/template.yaml",
    "LoadBalancer": "templates/containers/alb/template.yaml",
    "Service": "templates/containers/fargate-service/template.yaml",
    "Dns": "templates/networking/dns-records/template.yaml",
    "AlarmTopic": "templates/messaging/sns-topic/template.yaml",
    "Alarms": "templates/observability/service-alarms/template.yaml",
}


def test_every_resource_is_a_nested_library_template(template) -> None:
    """No inline resources.

    A resource defined only inside a composition cannot be reused and is not
    covered by any per-template test suite.
    """
    types = {resource["Type"] for resource in template.resources.values()}
    assert types == {"AWS::CloudFormation::Stack"}


@pytest.mark.parametrize("logical_id,path", sorted(CHILDREN.items()))
def test_child_template_paths_resolve(template, logical_id: str, path: str) -> None:
    """A relative TemplateURL that does not exist fails at `cfn package` time."""
    url = template.prop(logical_id, "TemplateURL")
    assert url == f"../../{path}", f"{logical_id} should point at {path}"
    assert (REPO_ROOT / path).exists(), f"{path} does not exist"


def test_tasks_run_private_and_the_load_balancer_is_public(template) -> None:
    """The single most important wiring decision in the stack."""
    assert template.prop("LoadBalancer", "Parameters.SubnetIds") == {
        "Fn::GetAtt": ["Network", "Outputs.PublicSubnetIds"]
    }
    assert template.prop("Service", "Parameters.SubnetIds") == {
        "Fn::GetAtt": ["Network", "Outputs.PrivateSubnetIds"]
    }
    assert template.prop("LoadBalancer", "Parameters.Scheme") == "internet-facing"


def test_service_is_reachable_only_through_the_load_balancer(template) -> None:
    assert template.prop("Service", "Parameters.AlbSecurityGroupId") == {
        "Fn::GetAtt": ["LoadBalancer", "Outputs.SecurityGroupId"]
    }
    assert template.prop("Service", "Parameters.ListenerArn") == {
        "Fn::GetAtt": ["LoadBalancer", "Outputs.ListenerArn"]
    }


def test_request_based_autoscaling_is_fully_wired(template) -> None:
    """It needs the load balancer's full name as well as the target group's;
    passing only one silently disables request scaling."""
    assert template.prop("Service", "Parameters.LoadBalancerFullName") == {
        "Fn::GetAtt": ["LoadBalancer", "Outputs.LoadBalancerFullName"]
    }
    assert template.prop("Service", "Parameters.TargetRequestsPerTask") == {
        "Ref": "TargetRequestsPerTask"
    }
    assert template.default("TargetRequestsPerTask") == 500


def test_dns_alias_uses_the_load_balancers_own_zone(template) -> None:
    assert template.prop("Dns", "Parameters.AliasTargetDnsName") == {
        "Fn::GetAtt": ["LoadBalancer", "Outputs.LoadBalancerDnsName"]
    }
    assert template.prop("Dns", "Parameters.AliasTargetHostedZoneId") == {
        "Fn::GetAtt": ["LoadBalancer", "Outputs.LoadBalancerHostedZoneId"]
    }, (
        "Passing the record's own zone here produces a record that resolves to "
        "nothing, with no deploy-time error."
    )


def test_certificate_and_listener_rule_use_the_same_domain(template) -> None:
    """A certificate for one host and a listener rule for another produces a
    service that serves TLS correctly and routes nothing."""
    assert template.prop("Certificate", "Parameters.DomainName") == {"Ref": "DomainName"}
    assert template.prop("Service", "Parameters.HostHeader") == {"Ref": "DomainName"}
    assert template.prop("LoadBalancer", "Parameters.CertificateArn") == {
        "Fn::GetAtt": ["Certificate", "Outputs.CertificateArn"]
    }


def test_alarms_watch_the_resources_this_stack_created(template) -> None:
    params = template.prop("Alarms", "Parameters")
    assert params["TargetGroupFullName"] == {"Fn::GetAtt": ["Service", "Outputs.TargetGroupFullName"]}
    assert params["EcsServiceName"] == {"Fn::GetAtt": ["Service", "Outputs.ServiceName"]}
    assert params["AlarmTopicArn"] == {"Fn::GetAtt": ["AlarmTopic", "Outputs.TopicArn"]}


def test_registry_is_not_environment_scoped(template) -> None:
    """The image is built once and promoted; see containers/ecr-repository."""
    assert "Environment" not in template.prop("Registry", "Parameters")


def test_outputs_let_a_database_be_attached(template) -> None:
    """The three values database/aurora-serverless-v2 needs."""
    for name in ("VpcId", "PrivateSubnetIds", "TaskSecurityGroupId"):
        assert name in template.outputs
    assert template.outputs["ServiceUrl"]["Value"] == {"Fn::Sub": "https://${DomainName}"}
