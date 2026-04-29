#!/usr/bin/env python3
"""Prepare an envctl release.

This script is invoked by the release CI to:

* compute the next version (either from a ``patch|minor|major`` bump or from an
  explicit ``--version`` override),
* update ``pyproject.toml`` and the version-bound badges in ``README.md``,
* write ``docs/changelog/RELEASE_NOTES_<version>.md`` from the source PR body.

The CI workflows then commit those changes, open a release PR, and publish a
GitHub Release with the same notes file once the PR merges.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
PYPROJECT_VERSION_LINE = re.compile(r'^(?P<lead>version\s*=\s*")(?P<version>[^"]+)(?P<trail>".*)$', re.MULTILINE)


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, raw: str) -> "SemVer":
        match = VERSION_PATTERN.match(raw.strip())
        if not match:
            raise ValueError(f"version {raw!r} is not a MAJOR.MINOR.PATCH triple")
        return cls(int(match["major"]), int(match["minor"]), int(match["patch"]))

    def bumped(self, kind: str) -> "SemVer":
        if kind == "patch":
            return SemVer(self.major, self.minor, self.patch + 1)
        if kind == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        if kind == "major":
            return SemVer(self.major + 1, 0, 0)
        raise ValueError(f"unknown bump kind {kind!r}; expected patch, minor, or major")


def read_pyproject_version(repo_root: Path) -> str:
    payload = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def write_pyproject_version(repo_root: Path, new_version: str) -> None:
    pyproject_path = repo_root / "pyproject.toml"
    text = pyproject_path.read_text(encoding="utf-8")
    new_text, count = PYPROJECT_VERSION_LINE.subn(rf'\g<lead>{new_version}\g<trail>', text, count=1)
    if count != 1:
        raise RuntimeError("could not locate `version = \"...\"` in pyproject.toml")
    pyproject_path.write_text(new_text, encoding="utf-8")


def update_readme_badges(repo_root: Path, old_version: str, new_version: str) -> None:
    """Update the three version-bound fragments asserted by ``test_release_version_metadata_is_consistent``."""

    if old_version == new_version:
        return
    readme_path = repo_root / "README.md"
    text = readme_path.read_text(encoding="utf-8")
    replacements = (
        (f"releases/tag/{old_version}", f"releases/tag/{new_version}"),
        (f"release-{old_version}", f"release-{new_version}"),
        (f"Release {old_version}", f"Release {new_version}"),
    )
    new_text = text
    for needle, replacement in replacements:
        if needle not in new_text:
            raise RuntimeError(f"README.md is missing expected fragment {needle!r}; cannot update badges safely")
        new_text = new_text.replace(needle, replacement)
    readme_path.write_text(new_text, encoding="utf-8")


def render_release_notes(version: str, body: str) -> str:
    cleaned_body = body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not cleaned_body:
        cleaned_body = (
            "Release notes were not provided in the source PR body. "
            "See the merged PR for the change set."
        )
    heading = f"# envctl {version}"
    if cleaned_body.lstrip().startswith(heading):
        # PR body already includes the canonical heading; keep it once.
        return cleaned_body.rstrip() + "\n"
    return f"{heading}\n\n{cleaned_body.rstrip()}\n"


def write_release_notes(repo_root: Path, version: str, body: str) -> Path:
    notes_dir = repo_root / "docs" / "changelog"
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_path = notes_dir / f"RELEASE_NOTES_{version}.md"
    notes_path.write_text(render_release_notes(version, body), encoding="utf-8")
    return notes_path


def resolve_version(repo_root: Path, *, bump: str | None, version: str | None) -> tuple[str, str]:
    current = read_pyproject_version(repo_root)
    if version is not None and bump is not None:
        raise SystemExit("error: --version and --bump are mutually exclusive")
    if version is not None:
        new = str(SemVer.parse(version))
    elif bump is not None:
        new = str(SemVer.parse(current).bumped(bump))
    else:
        raise SystemExit("error: one of --version or --bump is required")
    return current, new


def cmd_compute_version(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo(args)
    _, new = resolve_version(repo_root, bump=args.bump, version=args.version)
    print(new)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo(args)
    current, new_version = resolve_version(repo_root, bump=args.bump, version=args.version)

    if args.notes_body_file:
        body = Path(args.notes_body_file).read_text(encoding="utf-8")
    elif args.notes_body is not None:
        body = args.notes_body
    else:
        raise SystemExit("error: provide release notes via --notes-body-file or --notes-body")

    write_pyproject_version(repo_root, new_version)
    update_readme_badges(repo_root, current, new_version)
    notes_path = write_release_notes(repo_root, new_version, body)

    print(f"previous_version={current}")
    print(f"new_version={new_version}")
    print(f"notes_path={notes_path.relative_to(repo_root)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute and apply the next envctl release version.")
    parser.add_argument("--repo", default=".", help="Path to the repository root (default: current dir).")
    sub = parser.add_subparsers(dest="command", required=True)

    compute = sub.add_parser("compute-version", help="Print the next version on stdout without modifying any files.")
    compute.add_argument("--repo", default=None, help="Path to the repository root (default: inherited).")
    bump_or_version_compute = compute.add_mutually_exclusive_group(required=True)
    bump_or_version_compute.add_argument(
        "--bump", choices=("patch", "minor", "major"), help="Bump strategy applied to the current pyproject version."
    )
    bump_or_version_compute.add_argument(
        "--version", help="Explicit MAJOR.MINOR.PATCH version override (validated)."
    )
    compute.set_defaults(handler=cmd_compute_version)

    apply = sub.add_parser("apply", help="Apply the version bump and write the release notes file.")
    apply.add_argument("--repo", default=None, help="Path to the repository root (default: inherited).")
    bump_or_version_apply = apply.add_mutually_exclusive_group(required=True)
    bump_or_version_apply.add_argument("--bump", choices=("patch", "minor", "major"))
    bump_or_version_apply.add_argument("--version", help="Explicit MAJOR.MINOR.PATCH version override.")
    notes_group = apply.add_mutually_exclusive_group(required=True)
    notes_group.add_argument("--notes-body-file", help="Path to a file containing the release notes body.")
    notes_group.add_argument("--notes-body", help="Inline release notes body string.")
    apply.set_defaults(handler=cmd_apply)

    return parser


def _resolve_repo(args: argparse.Namespace) -> Path:
    repo = getattr(args, "repo", None) or "."
    return Path(repo).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
