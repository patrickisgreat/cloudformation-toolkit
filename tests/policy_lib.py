"""The security policy engine: rules, findings, and the exemption ledger.

Terraform has `terraform test` with mocked providers. CloudFormation has no
equivalent, so this repo builds one: rules are plain Python functions over a
parsed template, and every template in the library is swept by every rule on
each test run — offline, with no account.

A rule returns findings. A finding is a (resource, reason) pair. Anything a rule
flags either gets fixed or gets an entry in `policy_exemptions.yaml` carrying a
written justification. An exemption without a reason is a lie, so the loader
rejects it; an exemption that no longer matches anything is dead weight, so the
suite fails on that too.

Values in a template are frequently intrinsics rather than literals — a bucket's
encryption toggle is usually `!Ref EnableX`, not `true`. `resolves_safely()`
handles that by following `Ref` to the parameter's *default*, which is exactly
the claim these rules are making: **the defaults are safe**. A caller who
deliberately passes an unsafe value is making an informed choice; a caller who
passes nothing must land somewhere defensible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from cfn_loader import Template

MISSING = object()


@dataclass(frozen=True)
class Finding:
    resource: str
    reason: str


Rule = Callable[[Template], list[Finding]]

RULES: dict[str, "RuleSpec"] = {}


@dataclass
class RuleSpec:
    id: str
    title: str
    why: str
    fn: Rule


def rule(rule_id: str, title: str, why: str):
    """Register a policy rule.

    `why` is not decoration: it is printed on failure, and it is the thing that
    tells whoever just tripped the rule whether to fix the template or write an
    exemption.
    """

    def decorate(fn: Rule) -> Rule:
        RULES[rule_id] = RuleSpec(rule_id, title, why, fn)
        return fn

    return decorate


# --- value resolution -------------------------------------------------------


def resolve(t: Template, value: Any) -> Any:
    """Best-effort resolution of a property value to a literal.

    * `{"Ref": "SomeParam"}` -> that parameter's declared default
    * `{"Fn::If": [c, a, b]}` -> the tuple `(a, b)`, so callers can require both
      branches to be acceptable
    * anything else -> returned unchanged

    Returns MISSING when a Ref points at something with no default (a required
    parameter or a resource), because then the template makes no claim about it.
    """
    if isinstance(value, dict) and len(value) == 1:
        (key, inner), = value.items()
        if key == "Ref":
            if inner in t.parameters:
                return t.parameters[inner].get("Default", MISSING)
            return MISSING
        if key == "Fn::If" and isinstance(inner, list) and len(inner) == 3:
            return (resolve(t, inner[1]), resolve(t, inner[2]))
    return value


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def resolves_true(t: Template, value: Any) -> bool:
    """Does this value mean 'on' by default, on every branch it can take?"""
    resolved = resolve(t, value)
    if resolved is MISSING:
        return False
    if isinstance(resolved, tuple):
        return all(resolves_true(t, branch) for branch in resolved)
    return _truthy(resolved)


def resolves_in(t: Template, value: Any, allowed: set) -> bool:
    """Does this value land inside `allowed` on every branch it can take?"""
    resolved = resolve(t, value)
    if resolved is MISSING:
        return False
    if isinstance(resolved, tuple):
        return all(resolves_in(t, branch, allowed) for branch in resolved)
    return resolved in allowed


def literals(node: Any) -> list[str]:
    """Every string literal reachable from a node, for regex sweeps."""
    found: list[str] = []
    if isinstance(node, str):
        found.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            found.extend(literals(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(literals(value))
    return found


def as_list(value: Any) -> list:
    if value is None or value is MISSING:
        return []
    return value if isinstance(value, list) else [value]


def statements(policy: Any) -> list[dict]:
    """Every IAM statement inside a policy document, however it is nested."""
    if not isinstance(policy, dict):
        return []
    return [s for s in as_list(policy.get("Statement")) if isinstance(s, dict)]


def iam_documents(t: Template) -> list[tuple[str, str, dict]]:
    """Every IAM policy document in the template, as (resource, kind, document).

    Policy documents hide in a dozen shapes — `Policies[].PolicyDocument` on a
    role, `PolicyDocument` on a managed policy, `AssumeRolePolicyDocument`,
    resource policies on buckets/queues/topics/keys. Sweeping by key name finds
    them all without a per-resource-type map that would rot.

    `kind` is the property name the document was found under, because the same
    statement means different things depending on where it sits: `Resource: "*"`
    in an identity policy means *every resource in the account*, while in a KMS
    key policy it means *this key* and is the only value AWS accepts.
    """
    docs: list[tuple[str, str, dict]] = []
    keys = {
        "PolicyDocument", "AssumeRolePolicyDocument", "KeyPolicy",
        "RepositoryPolicyText", "Policy", "ResourcePolicy",
    }

    def walk(resource_id: str, node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys and isinstance(value, dict) and "Statement" in value:
                    docs.append((resource_id, key, value))
                walk(resource_id, value)
        elif isinstance(node, list):
            for value in node:
                walk(resource_id, value)

    for logical_id, resource in t.resources.items():
        walk(logical_id, resource.get("Properties", {}) or {})
    return docs


# Property names whose documents are attached *to* the resource they govern, so
# `Resource: "*"` is self-referential rather than account-wide.
SELF_SCOPED_POLICY_KINDS = {"KeyPolicy"}


# --- the exemption ledger ---------------------------------------------------


@dataclass(frozen=True)
class Exemption:
    template: str
    rule: str
    resource: str
    reason: str

    def matches(self, template_key: str, rule_id: str, finding: Finding) -> bool:
        return (
            self.template == template_key
            and self.rule == rule_id
            and self.resource in (finding.resource, "*")
        )


_MIN_REASON_WORDS = 6


def load_exemptions(path: Path) -> list[Exemption]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("exemptions") or []
    exemptions: list[Exemption] = []
    for index, entry in enumerate(entries):
        missing = [k for k in ("template", "rule", "resource", "reason") if not entry.get(k)]
        if missing:
            raise SystemExit(
                f"{path}: exemption #{index + 1} is missing {', '.join(missing)}"
            )
        if entry["rule"] not in RULES:
            raise SystemExit(
                f"{path}: exemption #{index + 1} names unknown rule {entry['rule']!r}"
            )
        if len(str(entry["reason"]).split()) < _MIN_REASON_WORDS:
            raise SystemExit(
                f"{path}: exemption #{index + 1} ({entry['template']} / {entry['rule']}) "
                "needs a real justification, not a placeholder — say why the rule does "
                "not apply here."
            )
        exemptions.append(
            Exemption(entry["template"], entry["rule"], entry["resource"], entry["reason"])
        )
    return exemptions


ACCOUNT_ID_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
# Anchored at the end of the name so the *head noun* decides. `DatabasePassword`
# and `GitHubToken` are values; `SecretSuffix`, `SecretDescription`, and
# `SecretStringTemplate` are metadata about a secret and are meant to be visible.
# An unanchored match flags all of them and teaches authors to ignore the rule.
SECRETISH_RE = re.compile(
    r"(password|passwd|secret|token|apikey|privatekey|credentials?)$",
    re.IGNORECASE,
)
