#!/usr/bin/env python3
"""Merge a CloudFormation parameter file with `--param K=V` overrides.

`aws cloudformation deploy` takes `--parameter-overrides Key=Value ...` but
cannot merge a file with ad-hoc overrides, which is exactly what you want when
an environment's committed parameters are right except for the one value you are
testing. This emits one `Key=Value` token per line for the caller to splat.

    merge_params.py environments/dev/params/api.json DesiredCount=4
    merge_params.py --none DesiredCount=4     # overrides only, no file

Later wins, so overrides beat the file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: merge_params.py <params.json|--none> [Key=Value ...]", file=sys.stderr)
        return 2

    source, overrides = argv[0], argv[1:]
    merged: dict[str, str] = {}

    if source != "--none":
        entries = json.loads(Path(source).read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            print(f"{source}: expected a JSON list of parameter objects", file=sys.stderr)
            return 1
        for entry in entries:
            try:
                merged[entry["ParameterKey"]] = entry["ParameterValue"]
            except (TypeError, KeyError):
                print(f"{source}: entry {entry!r} needs ParameterKey and ParameterValue", file=sys.stderr)
                return 1

    for override in overrides:
        if "=" not in override:
            print(f"--param {override!r} must be Key=Value", file=sys.stderr)
            return 1
        key, value = override.split("=", 1)
        merged[key] = value

    for key, value in merged.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
