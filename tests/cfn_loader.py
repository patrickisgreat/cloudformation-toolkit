"""Parse CloudFormation YAML into plain Python, and query it ergonomically.

CloudFormation YAML is not YAML. It uses local tags (`!Ref`, `!GetAtt`, `!Sub`)
that PyYAML rejects outright, so every tool that wants to read a template has to
teach its parser about them first. This module does that once, then wraps the
result in a small query API so assertions read like sentences:

    template.prop("Bucket", "BucketEncryption.ServerSideEncryptionConfiguration")

Short-form tags are normalised to their long form (`!Ref X` -> `{"Ref": "X"}`),
so a test never has to care which spelling the template author used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

# `!Foo` short forms map onto `Fn::Foo`, except for these, which are not under
# the `Fn::` namespace in the long form.
_NOT_FN = {"Ref": "Ref", "Condition": "Condition"}

_TAGS = [
    "Ref", "Condition", "GetAtt", "Sub", "Join", "Select", "Split", "FindInMap",
    "If", "Equals", "Not", "And", "Or", "Base64", "Cidr", "ImportValue",
    "GetAZs", "Transform", "ForEach", "Length", "ToJsonString",
]


class CfnLoader(yaml.SafeLoader):
    """SafeLoader that understands CloudFormation's intrinsic-function tags."""


def _construct(tag_name: str):
    key = _NOT_FN.get(tag_name, f"Fn::{tag_name}")

    def constructor(loader: CfnLoader, node: yaml.Node) -> dict:
        if isinstance(node, yaml.ScalarNode):
            value: Any = loader.construct_scalar(node)
            # `!GetAtt Resource.Attribute` is sugar for the two-element list
            # form. Normalising here means tests only ever see the list.
            if tag_name == "GetAtt" and isinstance(value, str):
                value = value.split(".", 1)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        else:
            value = loader.construct_mapping(node, deep=True)
        return {key: value}

    return constructor


for _tag in _TAGS:
    CfnLoader.add_constructor(f"!{_tag}", _construct(_tag))


def _no_duplicate_keys(loader: CfnLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    """Reject duplicate mapping keys.

    Stock YAML silently keeps the last of a duplicated key. In a template that
    means a second `Properties:` or a repeated logical ID quietly deletes the
    first one, and the stack deploys something you did not write. Fail loudly.
    """
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"duplicate key {key!r}", key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


CfnLoader.construct_mapping = _no_duplicate_keys  # type: ignore[assignment]


def load_template(path: str | Path) -> dict:
    """Parse a CloudFormation template file into a dict."""
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=CfnLoader) or {}


_MISSING = object()


class Template:
    """A parsed template plus the queries tests actually want to make."""

    def __init__(self, body: dict, path: Path):
        self.body = body
        self.path = Path(path)
        self.name = self.path.parent.name
        self.group = self.path.parent.parent.name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Template {self.group}/{self.name}>"

    # -- top-level sections --------------------------------------------------

    @property
    def description(self) -> str:
        return self.body.get("Description", "")

    @property
    def parameters(self) -> dict:
        return self.body.get("Parameters", {}) or {}

    @property
    def resources(self) -> dict:
        return self.body.get("Resources", {}) or {}

    @property
    def outputs(self) -> dict:
        return self.body.get("Outputs", {}) or {}

    @property
    def conditions(self) -> dict:
        return self.body.get("Conditions", {}) or {}

    @property
    def mappings(self) -> dict:
        return self.body.get("Mappings", {}) or {}

    @property
    def metadata(self) -> dict:
        return self.body.get("Metadata", {}) or {}

    # -- parameters ----------------------------------------------------------

    def param(self, name: str) -> dict:
        assert name in self.parameters, f"{self}: no parameter {name!r}"
        return self.parameters[name]

    def default(self, name: str) -> Any:
        """The declared default of a parameter — what a caller gets for free.

        Most 'secure defaults' assertions are really assertions about this.
        """
        return self.param(name).get("Default", _MISSING)

    @property
    def required_parameters(self) -> list[str]:
        """Parameters a caller must supply (no Default declared)."""
        return [n for n, p in self.parameters.items() if "Default" not in p]

    def allowed_values(self, name: str) -> list:
        return self.param(name).get("AllowedValues", [])

    # -- resources -----------------------------------------------------------

    def resource(self, logical_id: str) -> dict:
        assert logical_id in self.resources, (
            f"{self}: no resource {logical_id!r} "
            f"(have: {', '.join(sorted(self.resources)) or 'none'})"
        )
        return self.resources[logical_id]

    def resource_type(self, logical_id: str) -> str:
        return self.resource(logical_id).get("Type", "")

    def of_type(self, *types: str) -> dict[str, dict]:
        """Every resource whose Type is one of `types`, keyed by logical ID."""
        wanted = set(types)
        return {k: v for k, v in self.resources.items() if v.get("Type") in wanted}

    def props(self, logical_id: str) -> dict:
        return self.resource(logical_id).get("Properties", {}) or {}

    def prop(self, logical_id: str, path: str, default: Any = _MISSING) -> Any:
        """Dotted lookup into a resource's Properties.

        List indices are numeric segments: `"Rules.0.Status"`. A missing segment
        raises unless a default is supplied, so a typo in a test fails as a typo
        rather than silently comparing against None.
        """
        node: Any = self.props(logical_id)
        walked: list[str] = []
        for part in path.split("."):
            walked.append(part)
            if isinstance(node, list):
                try:
                    node = node[int(part)]
                    continue
                except (ValueError, IndexError):
                    node = _MISSING
            elif isinstance(node, dict) and part in node:
                node = node[part]
                continue
            else:
                node = _MISSING

            if node is _MISSING:
                if default is not _MISSING:
                    return default
                raise AssertionError(
                    f"{self}: {logical_id} has no property "
                    f"{'.'.join(walked)} (looking up {path!r})"
                )
        return node

    def has_prop(self, logical_id: str, path: str) -> bool:
        # A sentinel distinct from _MISSING: passing _MISSING as `default` means
        # "no default", which makes prop() raise rather than return it.
        absent = object()
        return self.prop(logical_id, path, default=absent) is not absent

    def condition_on(self, logical_id: str) -> str | None:
        """The Condition guarding a resource, if any — how CFN does `count`."""
        return self.resource(logical_id).get("Condition")

    def deletion_policy(self, logical_id: str) -> str | None:
        return self.resource(logical_id).get("DeletionPolicy")

    # -- outputs -------------------------------------------------------------

    def output(self, name: str) -> dict:
        assert name in self.outputs, (
            f"{self}: no output {name!r} "
            f"(have: {', '.join(sorted(self.outputs)) or 'none'})"
        )
        return self.outputs[name]

    # -- traversal -----------------------------------------------------------

    def walk(self) -> Iterable[tuple[str, Any]]:
        """Yield every (dotted path, value) pair in the template body.

        Policy rules use this to sweep for things that can appear anywhere —
        hardcoded account IDs, wildcard IAM actions, plaintext secrets.
        """
        yield from _walk(self.body, "")


def _walk(node: Any, path: str) -> Iterable[tuple[str, Any]]:
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}.{index}")
