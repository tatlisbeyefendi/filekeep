"""The documentation is part of the product: keep it honest.

These tests fail when a flag exists in the code but not in the README, when a link
points at a file that is not there, or when the version in three places disagrees.
"""

from __future__ import annotations

import argparse
import re
import tomllib
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from filekeep import __version__
from filekeep.cli import build_parser

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
README_TR = REPO / "README.tr.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def all_option_strings(parser: argparse.ArgumentParser) -> set[str]:
    """Every flag in the parser tree, including subcommands nested twice (tag add/rm/ls)."""
    found: set[str] = set()

    def visit(current: argparse.ArgumentParser) -> None:
        for action in current._actions:
            found.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                for subparser in action.choices.values():
                    visit(subparser)

    visit(parser)
    return found


def subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def test_readme_exists_and_is_substantial() -> None:
    text = read(README)
    assert len(text.splitlines()) > 150
    assert text.startswith("# filekeep")


def test_turkish_readme_exists() -> None:
    text = read(README_TR)
    assert text.startswith("# filekeep")
    assert "README.md" in text
    assert "filekeep scan" in text


DOCUMENTS = ["README.md", "README.tr.md", "CONTRIBUTING.md", "CHANGELOG.md"]


@pytest.mark.parametrize("document", DOCUMENTS)
def test_relative_links_resolve(document: str) -> None:
    text = read(REPO / document)
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        if not (REPO / path).exists():
            broken.append(target)
    assert broken == []


def test_every_flag_is_documented() -> None:
    readme = read(README)
    missing = sorted(flag for flag in all_option_strings(build_parser()) if flag not in readme)
    assert missing == [], f"undocumented flags: {missing}"


def test_every_command_is_documented() -> None:
    readme = read(README)
    commands = subparsers(build_parser())
    missing = sorted(name for name in commands if f"`{name}`" not in readme)
    assert missing == []
    assert len(commands) >= 15


def test_readme_documents_the_safety_model() -> None:
    text = read(README)
    for phrase in ("--apply", "undo", "trash", "Dry run by default"):
        assert phrase in text


def test_version_matches_pyproject() -> None:
    data = tomllib.loads(read(REPO / "pyproject.toml"))
    assert data["project"]["version"] == __version__


def test_changelog_has_the_current_version() -> None:
    text = read(REPO / "CHANGELOG.md")
    assert f"## [{__version__}]" in text
    assert "Keep a Changelog" in text


def test_changelog_links_point_at_the_project() -> None:
    text = read(REPO / "CHANGELOG.md")
    assert "https://github.com/tatlisbeyefendi/filekeep" in text


def test_no_owner_placeholder_anywhere() -> None:
    offenders = []
    for path in REPO.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix in {".pyc", ".db"}:
            continue
        if path.name in {"index.db"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # built at runtime so this very file does not trip the check
        if "OWN" + "ER" in text or "YOUR_" + "USERNAME" in text:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_pyproject_metadata() -> None:
    data = tomllib.loads(read(REPO / "pyproject.toml"))
    project = data["project"]
    assert project["requires-python"] == ">=3.11"
    assert project["dependencies"] == []
    assert "dev" in project["optional-dependencies"]
    assert project["scripts"] == {
        "filekeep": "filekeep.cli:main",
        "fk": "filekeep.cli:main",
    }
    assert project["urls"]["Homepage"] == "https://github.com/tatlisbeyefendi/filekeep"
    assert "pytest" in " ".join(project["optional-dependencies"]["dev"])


def test_license_is_mit() -> None:
    text = read(REPO / "LICENSE")
    assert text.startswith("MIT License")
    assert "tatlisbeyefendi" in text


@pytest.mark.parametrize("name", ["docs/demo.svg", "docs/demo-dupes.svg"])
def test_demo_svg_is_valid_xml(name: str) -> None:
    tree = ElementTree.parse(REPO / name)
    root = tree.getroot()
    assert root.tag.endswith("svg")
    assert root.get("role") == "img"
    circles = root.findall(".//{http://www.w3.org/2000/svg}circle")
    assert len(circles) == 3
    text = read(REPO / name)
    assert "filekeep" in text


def test_demo_svgs_describe_real_output() -> None:
    text = read(REPO / "docs/demo.svg")
    assert "filekeep ls" in text
    assert "KIND" in text or "SIZE" in text
    dupes = read(REPO / "docs/demo-dupes.svg")
    assert "reclaimable" in dupes


def test_ci_workflow_covers_the_matrix() -> None:
    text = read(REPO / ".github" / "workflows" / "ci.yml")
    for version in ("3.11", "3.12", "3.13", "3.14"):
        assert f'"{version}"' in text
    assert "macos-latest" in text
    assert "windows-latest" in text
    assert "ruff format --check" in text


def test_issue_templates_exist() -> None:
    directory = REPO / ".github" / "ISSUE_TEMPLATE"
    assert (directory / "bug_report.yml").exists()
    assert (directory / "feature_request.yml").exists()
    assert (directory / "config.yml").exists()
    assert "blank_issues_enabled" in read(directory / "config.yml")


def test_contributing_mentions_the_rules() -> None:
    text = read(REPO / "CONTRIBUTING.md")
    assert "No new dependencies" in text
    assert "--apply" in text
    assert "make test" in text
