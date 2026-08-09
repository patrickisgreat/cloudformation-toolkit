#!/usr/bin/env python3
"""Print a template's parameters the way you need them before a deploy.

`aws cloudformation describe-template-summary` needs an account. This does the
same job offline, grouped exactly as the console groups them, with the required
set called out first — because the only question you ever have before a deploy
is "what must I supply?".

    scripts/show_params.py templates/containers/fargate-service/template.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from cfn_loader import Template, load_template  # noqa: E402

BOLD, DIM, CYAN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[36m", "\033[33m", "\033[0m"
if not sys.stdout.isatty():
    BOLD = DIM = CYAN = YELLOW = RESET = ""


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: show_params.py <template.yaml>", file=sys.stderr)
        return 2

    path = Path(argv[0])
    t = Template(load_template(path), path)

    print(f"{BOLD}{path}{RESET}")
    print(f"{DIM}{t.description}{RESET}\n")

    required = t.required_parameters
    if required:
        print(f"{YELLOW}Required ({len(required)}){RESET}: {', '.join(required)}\n")
    else:
        print(f"{DIM}Every parameter has a default — this template deploys as-is.{RESET}\n")

    interface = t.metadata.get("AWS::CloudFormation::Interface") or {}
    groups = interface.get("ParameterGroups") or []
    grouped = {
        (g.get("Label", {}).get("default") or "Parameters"): g.get("Parameters", [])
        for g in groups
    }
    if not grouped:
        grouped = {"Parameters": list(t.parameters)}

    for label, names in grouped.items():
        print(f"{BOLD}{label}{RESET}")
        for name in names:
            spec = t.parameters.get(name)
            if spec is None:
                continue
            if "Default" in spec:
                value = spec["Default"]
                shown = f"= {value!r}" if value != "" else '= ""'
            else:
                shown = f"{YELLOW}(required){RESET}"
            print(f"  {CYAN}{name}{RESET} {DIM}{spec.get('Type', '')}{RESET} {shown}")
            print(f"      {spec.get('Description', '')}")
            if spec.get("AllowedValues"):
                print(f"      {DIM}allowed: {', '.join(map(str, spec['AllowedValues']))}{RESET}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
