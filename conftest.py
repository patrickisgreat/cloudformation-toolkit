"""Shared pytest fixtures for the whole repo.

Two kinds of test live here:

* `tests/` — repo-wide sweeps: structural conventions and the security policy
  baseline, applied to every template in the library.
* `templates/<group>/<name>/tests/` — per-template assertions, the direct analog
  of a `terraform test` suite. Those get the `template` fixture below, which
  resolves the `template.yaml` that owns the test file, so a test never has to
  spell out its own path.

Everything runs offline against the parsed template. No AWS account, no
credentials, no `validate-template` round trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cfn_loader import Template, load_template  # noqa: E402

TEMPLATES_DIR = REPO_ROOT / "templates"
STACKS_DIR = REPO_ROOT / "stacks"


def template_dirs(include_scaffold: bool = False) -> list[Path]:
    """Every library template directory, sorted by group then name."""
    dirs = sorted(
        p.parent for p in TEMPLATES_DIR.glob("*/*/template.yaml")
    )
    if not include_scaffold:
        dirs = [d for d in dirs if d.parent.name != "_template"]
    return dirs


def stack_dirs() -> list[Path]:
    return sorted(p.parent for p in STACKS_DIR.glob("*/template.yaml"))


def all_dirs() -> list[Path]:
    """Templates and stacks together — what the policy baseline applies to."""
    return template_dirs() + stack_dirs()


def load(path: Path) -> Template:
    return Template(load_template(path), path)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


@pytest.fixture(scope="module")
def template(request) -> Template:
    """The template.yaml that owns the calling test file (`../template.yaml`)."""
    path = Path(request.path).parent.parent / "template.yaml"
    assert path.exists(), f"expected a template at {path}"
    return load(path)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parameterise the repo-wide sweeps over every template.

    A test that takes `any_template` gets the parsed template; one that takes
    `template_dir` gets the directory, for checks about files on disk. Both run
    over library templates *and* stacks — a stack is a template too, and holding
    it to a lower standard is how the composition layer rots.

    IDs are the directory path (`containers/fargate-service`), so a failure names
    the template directly instead of an index.
    """
    dirs = all_dirs()
    if "any_template" in metafunc.fixturenames:
        metafunc.parametrize(
            "any_template",
            [load(d / "template.yaml") for d in dirs],
            ids=[_rel(d) for d in dirs],
        )
    if "template_dir" in metafunc.fixturenames:
        metafunc.parametrize("template_dir", dirs, ids=[_rel(d) for d in dirs])
