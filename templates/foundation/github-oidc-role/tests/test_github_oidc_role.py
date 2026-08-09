"""Assertions for foundation/github-oidc-role.

The trust policy is the entire security boundary here, so most of this file is
about it. A mistake in these conditions does not degrade security, it removes it.
"""

from __future__ import annotations


def _trust(template):
    return template.prop("Role", "AssumeRolePolicyDocument.Statement.0")


# --- the trust policy --------------------------------------------------------

def test_audience_is_pinned_to_sts(template) -> None:
    condition = _trust(template)["Condition"]
    assert condition["StringEquals"]["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com", (
        "Without the audience check, a token GitHub minted for a different relying "
        "party can be replayed against STS."
    )


def test_subject_is_scoped_to_one_repository(template) -> None:
    """The check that stops every repo on GitHub from assuming this role.

    GitHub is the OIDC issuer for every public repository in existence. A trust
    policy with an audience condition and no subject condition trusts all of
    them — it is the canonical catastrophic OIDC misconfiguration.
    """
    subjects = _trust(template)["Condition"]["StringLike"]["token.actions.githubusercontent.com:sub"]
    assert subjects, "the subject condition must not be empty"

    branch_subject = subjects[0]
    assert branch_subject == {
        "Fn::Sub": "repo:${GitHubOrg}/${GitHubRepo}:ref:refs/heads/${AllowedBranch}"
    }, "the first subject must pin org, repo, and ref together"


def test_org_and_repo_are_not_wildcardable(template) -> None:
    """A wildcard in the repo name would widen trust to the whole org."""
    import re

    for name in ("GitHubOrg", "GitHubRepo"):
        pattern = template.param(name)["AllowedPattern"]
        assert not re.fullmatch(pattern, "*"), f"{name} must reject a bare wildcard"
        assert not re.fullmatch(pattern, "my-org/*"), f"{name} must reject a path wildcard"
    assert re.fullmatch(template.param("GitHubRepo")["AllowedPattern"], "cloudformation-toolkit")


def test_pull_requests_are_not_trusted_by_default(template) -> None:
    assert template.default("AllowPullRequests") == "false", (
        "A pull request from a fork runs code its author controls. Trusting "
        "pull_request by default hands that author a deploy role."
    )


def test_optional_subjects_drop_out_rather_than_widen(template) -> None:
    subjects = _trust(template)["Condition"]["StringLike"]["token.actions.githubusercontent.com:sub"]
    optional = [s for s in subjects if isinstance(s, dict) and "Fn::If" in s]
    assert len(optional) == 2, "environment and pull_request subjects are both optional"
    for entry in optional:
        assert entry["Fn::If"][2] == {"Ref": "AWS::NoValue"}, (
            "An unused subject must vanish. Leaving an empty string in the list "
            "would not match anything, but a malformed one can widen the match."
        )


# --- session and permissions -------------------------------------------------

def test_session_defaults_to_one_hour(template) -> None:
    assert template.default("MaxSessionDurationSeconds") == 3600, (
        "The credential lives for the whole session. An hour covers essentially "
        "every deploy; longer sessions are a longer window for a leaked token."
    )
    assert template.param("MaxSessionDurationSeconds")["MinValue"] == 900


def test_deploy_policy_is_scoped_to_this_environments_stacks(template) -> None:
    policies = template.prop("Role", "Policies")
    deploy = policies[0]["Fn::If"][1]
    assert deploy["PolicyName"] == "cloudformation-deploy"

    drive = deploy["PolicyDocument"]["Statement"][0]
    assert drive["Resource"][0] == {
        "Fn::Sub": "arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/${Environment}-*/*"
    }, (
        "The deploy role for dev must not be able to update the prod stacks. The "
        "stack ARN pattern matches the naming bin/cfn uses."
    )


def test_artifact_access_requires_a_bucket(template) -> None:
    """Granting S3 access with an empty bucket ARN would produce a broken policy."""
    policies = template.prop("Role", "Policies")
    artifacts = policies[1]["Fn::If"]
    assert artifacts[0] == "ShouldGrantArtifactAccess"
    assert artifacts[2] == {"Ref": "AWS::NoValue"}


# --- conditional wiring ------------------------------------------------------

def test_oidc_provider_can_be_reused(template) -> None:
    """There is one GitHub OIDC provider per account; the second create fails."""
    assert template.condition_on("OidcProvider") == "ShouldCreateOidcProvider"
    federated = _trust(template)["Principal"]["Federated"]
    assert federated == {
        "Fn::If": ["ShouldCreateOidcProvider", {"Ref": "OidcProvider"}, {"Ref": "ExistingOidcProviderArn"}]
    }, "when not creating the provider, the role must trust the existing one"


def test_role_arn_is_exposed_for_the_workflow(template) -> None:
    assert template.outputs["RoleArn"]["Value"] == {"Fn::GetAtt": ["Role", "Arn"]}
    assert template.outputs["OidcProviderArn"].get("Condition") == "ShouldCreateOidcProvider"
