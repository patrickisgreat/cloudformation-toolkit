"""Assertions for foundation/access-analyzer.

Small template, two claims worth defending: the free half is unconditional,
and the paid half cannot arrive by default.
"""

from __future__ import annotations


def test_external_access_analyzer_is_unconditional(template) -> None:
    """The free analyzer is the reason this template exists - making it
    optional would just be a switch for turning off findings."""
    assert "Condition" not in template.resource("Analyzer")
    assert template.prop("Analyzer", "Type") == {
        "Fn::If": ["IsOrganizationScope", "ORGANIZATION", "ACCOUNT"]
    }


def test_the_paid_analyzer_is_opt_in(template) -> None:
    assert template.default("EnableUnusedAccessAnalyzer") == "false", (
        "unused-access analysis bills per IAM role/user per month; a "
        "recurring cost must never be a default"
    )
    assert template.condition_on("UnusedAccessAnalyzer") == "HasUnusedAccessAnalyzer"


def test_unused_access_scope_follows_the_analyzer_scope(template) -> None:
    """An account-scoped external analyzer with an organization-scoped unused
    analyzer would be a confusing half-org posture; both follow one knob."""
    unused_type = template.prop("UnusedAccessAnalyzer", "Type")
    assert unused_type == {
        "Fn::If": ["IsOrganizationScope", "ORGANIZATION_UNUSED_ACCESS", "ACCOUNT_UNUSED_ACCESS"]
    }


def test_unused_age_reaches_the_analyzer_configuration(template) -> None:
    config = template.prop(
        "UnusedAccessAnalyzer", "AnalyzerConfiguration.UnusedAccessConfiguration.UnusedAccessAge"
    )
    assert config == {"Ref": "UnusedAccessAgeDays"}
    assert template.default("UnusedAccessAgeDays") == 90


def test_analyzers_are_account_level_so_no_environment(template) -> None:
    """Access Analyzer watches an account (or the whole organization); there
    is no dev/prod dimension to it, so unlike service templates it takes no
    `Environment`. Per-environment posture is per-account posture - see
    foundation/org-account.
    """
    assert "Environment" not in template.parameters


def test_conditional_output_carries_the_condition(template) -> None:
    assert template.outputs["UnusedAccessAnalyzerArn"].get("Condition") == "HasUnusedAccessAnalyzer"
