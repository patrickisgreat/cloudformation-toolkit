#!/usr/bin/env python3
"""Generate the template and stack catalogs in README.md from metadata.yaml.

Every template and stack owns its catalog row via a `metadata.yaml`:

    group: containers
    status: stable
    summary: One-line description for the catalog table.

The tables are written between the BEGIN_/END_ markers in README.md. Hand-editing
them is pointless — they get overwritten. This exists because a hand-maintained
table in a shared file is a merge-conflict generator: every parallel template PR
appends to the same lines, and rows get lost in the resolution.

    scripts/gen_catalog.py           # rewrite README.md in place
    scripts/gen_catalog.py --check   # exit 1 if README.md is out of date (CI)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
STACKS_DIR = REPO_ROOT / "stacks"
README = REPO_ROOT / "README.md"

TEMPLATE_MARKERS = ("<!-- BEGIN_CATALOG -->", "<!-- END_CATALOG -->")
STACK_MARKERS = ("<!-- BEGIN_STACKS -->", "<!-- END_STACKS -->")

REQUIRED_KEYS = ("group", "status", "summary")
VALID_STATUSES = ("experimental", "beta", "stable")

# Groups render in dependency order — you cannot run a service without a
# network, so `foundation` comes first and the breadth groups come last.
GROUP_ORDER = (
    "foundation",
    "containers",
    "serverless",
    "messaging",
    "data",
    "database",
    "ml",
    "networking",
    "observability",
    "cicd",
)

GROUP_TITLES = {
    "foundation": "Foundation — network, keys, identity, secrets",
    "containers": "Containers — registry, cluster, load balancing, Fargate",
    "serverless": "Serverless — functions, HTTP APIs, GraphQL, orchestration",
    "messaging": "Messaging — queues, topics, event routing",
    "data": "Data — object storage, streaming, catalog, ETL, query",
    "database": "Databases — relational, key-value, cache",
    "ml": "ML / LLM — managed inference, GPU serving, model artifacts",
    "networking": "Networking & edge — DNS, certificates, CDN, WAF",
    "observability": "Observability — alarms, dashboards",
    "cicd": "CI/CD — build and deployment pipelines",
}


def load_metadata(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a YAML mapping")
    return data


def collect(root: Path, depth: int) -> list[dict]:
    """Collect catalog entries from `root`, at `depth` directory levels down."""
    pattern = "/".join(["*"] * depth) + "/template.yaml"
    entries: list[dict] = []
    errors: list[str] = []

    for template in sorted(root.glob(pattern)):
        directory = template.parent
        rel = directory.relative_to(REPO_ROOT).as_posix()
        if directory.parent.name == "_template" or directory.name == "_template":
            continue

        meta_path = directory / "metadata.yaml"
        if not meta_path.exists():
            errors.append(f"{rel}: missing metadata.yaml")
            continue

        meta = load_metadata(meta_path)
        missing = [k for k in REQUIRED_KEYS if not meta.get(k)]
        if missing:
            errors.append(f"{rel}: metadata.yaml missing {', '.join(missing)}")
            continue
        if meta["status"] not in VALID_STATUSES:
            errors.append(
                f"{rel}: status {meta['status']!r} not one of {'/'.join(VALID_STATUSES)}"
            )
            continue

        entries.append({"path": rel, "name": directory.name, **meta})

    if errors:
        raise SystemExit("catalog metadata errors:\n  " + "\n  ".join(errors))
    return entries


def _status(value: str) -> str:
    return value if value == "stable" else f"**{value}**"


def render_template_table(entries: list[dict]) -> str:
    by_group: dict[str, list[dict]] = {}
    for entry in entries:
        by_group.setdefault(entry["group"], []).append(entry)

    def group_rank(group: str) -> tuple[int, str]:
        try:
            return (GROUP_ORDER.index(group), group)
        except ValueError:
            return (len(GROUP_ORDER), group)

    blocks: list[str] = []
    for group in sorted(by_group, key=group_rank):
        title = GROUP_TITLES.get(group, group.replace("-", " ").title())
        rows = [
            f"#### {title}",
            "",
            "| Template | Status | Description |",
            "|----------|--------|-------------|",
        ]
        for entry in sorted(by_group[group], key=lambda e: e["name"]):
            rows.append(
                f"| [`{entry['group']}/{entry['name']}`]({entry['path']}) "
                f"| {_status(entry['status'])} | {entry['summary']} |"
            )
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


def render_stack_table(entries: list[dict]) -> str:
    rows = [
        "| Stack | Status | What it deploys |",
        "|-------|--------|-----------------|",
    ]
    for entry in sorted(entries, key=lambda e: e["name"]):
        rows.append(
            f"| [`{entry['name']}`]({entry['path']}) "
            f"| {_status(entry['status'])} | {entry['summary']} |"
        )
    return "\n".join(rows)


def splice(text: str, markers: tuple[str, str], table: str) -> str:
    begin, end = markers
    try:
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
    except ValueError:
        raise SystemExit(
            f"README.md is missing the {begin} / {end} markers — add them around "
            "the catalog table."
        )
    return f"{head}{begin}\n{table}\n{end}{tail}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if README.md is out of date instead of rewriting it",
    )
    args = parser.parse_args()

    templates = collect(TEMPLATES_DIR, depth=2)
    stacks = collect(STACKS_DIR, depth=1)

    current = README.read_text(encoding="utf-8")
    updated = splice(current, TEMPLATE_MARKERS, render_template_table(templates))
    updated = splice(updated, STACK_MARKERS, render_stack_table(stacks))

    if current == updated:
        print(f"catalog up to date ({len(templates)} templates, {len(stacks)} stacks)")
        return 0

    if args.check:
        print(
            "README.md catalog is out of date. Run `./bin/cfn catalog` and commit "
            "the result.",
            file=sys.stderr,
        )
        return 1

    README.write_text(updated, encoding="utf-8")
    print(f"catalog regenerated ({len(templates)} templates, {len(stacks)} stacks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
