#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_TESTS_ROOT = Path("tests/python")
SKIP_MARKERS = {"skip", "skipif", "xfail"}
SLOW_MARKERS = {"slow"}


def _repo_root(value: str | None) -> Path:
    return Path(value or ".").resolve()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _category_for(path: Path, tests_root: Path) -> str:
    relative = path.relative_to(tests_root)
    return relative.parts[0] if len(relative.parts) > 1 else "."


def _marker_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _marker_name(node.func)
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Attribute) and node.value.attr == "mark":
            return node.attr
        if isinstance(node.value, ast.Name) and node.value.id == "pytest":
            return node.attr
    return None


def _test_name_records(path: Path, root: Path) -> tuple[list[str], Counter[str], list[dict[str, str]]]:
    markers: Counter[str] = Counter()
    test_names: list[str] = []
    flagged_tests: list[dict[str, str]] = []

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return test_names, markers, flagged_tests

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        test_names.append(node.name)
        node_markers = sorted(
            marker
            for marker in (_marker_name(decorator) for decorator in node.decorator_list)
            if marker is not None
        )
        markers.update(node_markers)
        flagged = [marker for marker in node_markers if marker in SKIP_MARKERS or marker in SLOW_MARKERS]
        if flagged:
            flagged_tests.append(
                {
                    "path": _relative(path, root),
                    "name": node.name,
                    "markers": ", ".join(flagged),
                }
            )

    return test_names, markers, flagged_tests


def collect_inventory(repo_root: Path, tests_root: Path = DEFAULT_TESTS_ROOT) -> dict[str, Any]:
    tests_path = repo_root / tests_root
    files = sorted(tests_path.rglob("*.py")) if tests_path.exists() else []
    line_counts = {path: _line_count(path) for path in files}
    category_file_counts: Counter[str] = Counter()
    category_line_counts: Counter[str] = Counter()
    marker_counts: Counter[str] = Counter()
    test_name_locations: dict[str, list[str]] = defaultdict(list)
    slow_or_skipped: list[dict[str, str]] = []

    for path in files:
        category = _category_for(path, tests_path)
        category_file_counts[category] += 1
        category_line_counts[category] += line_counts[path]
        names, markers, flagged_tests = _test_name_records(path, repo_root)
        marker_counts.update(markers)
        slow_or_skipped.extend(flagged_tests)
        for name in names:
            test_name_locations[name].append(_relative(path, repo_root))

    largest_files = [
        {"path": _relative(path, repo_root), "lines": line_counts[path]}
        for path in sorted(files, key=lambda item: (-line_counts[item], _relative(item, repo_root)))[:20]
    ]
    helper_modules = [
        _relative(path, repo_root)
        for path in files
        if path.name.endswith("_test_support.py") or path.name.endswith("test_support.py")
    ]
    duplicate_clusters = [
        {"name": name, "count": len(locations), "paths": locations}
        for name, locations in sorted(test_name_locations.items())
        if len(locations) > 1
    ]
    duplicate_clusters.sort(key=lambda item: (-item["count"], item["name"]))

    return {
        "tests_root": tests_root.as_posix(),
        "totals": {
            "files": len(files),
            "lines": sum(line_counts.values()),
            "helpers": len(helper_modules),
            "duplicate_test_name_clusters": len(duplicate_clusters),
            "slow_or_skipped_tests": len(slow_or_skipped),
        },
        "categories": [
            {
                "name": name,
                "files": category_file_counts[name],
                "lines": category_line_counts[name],
            }
            for name in sorted(category_file_counts)
        ],
        "largest_files": largest_files,
        "helper_modules": helper_modules,
        "pytest_markers": [
            {"name": name, "count": count}
            for name, count in sorted(marker_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "slow_or_skipped_tests": slow_or_skipped,
        "duplicate_test_name_clusters": duplicate_clusters,
    }


def render_markdown(inventory: dict[str, Any]) -> str:
    totals = inventory["totals"]
    lines = [
        "# Test Suite Inventory",
        "",
        f"- Tests root: `{inventory['tests_root']}`",
        f"- Python test files: {totals['files']}",
        f"- Total lines: {totals['lines']}",
        f"- Helper modules: {totals['helpers']}",
        f"- Duplicate test-name clusters: {totals['duplicate_test_name_clusters']}",
        f"- Slow/skipped/xfail tests: {totals['slow_or_skipped_tests']}",
        "",
        "## Categories",
        "",
        "| Category | Files | Lines |",
        "|---|---:|---:|",
    ]
    for category in inventory["categories"]:
        lines.append(f"| {category['name']} | {category['files']} | {category['lines']} |")

    lines.extend(["", "## Largest Files", ""])
    for entry in inventory["largest_files"][:10]:
        lines.append(f"- `{entry['path']}`: {entry['lines']} lines")

    lines.extend(["", "## Helper Modules", ""])
    for helper in inventory["helper_modules"][:30]:
        lines.append(f"- `{helper}`")
    if len(inventory["helper_modules"]) > 30:
        lines.append(f"- ... {len(inventory['helper_modules']) - 30} more")

    lines.extend(["", "## Pytest Markers", ""])
    if inventory["pytest_markers"]:
        for marker in inventory["pytest_markers"]:
            lines.append(f"- `{marker['name']}`: {marker['count']}")
    else:
        lines.append("- None detected")

    lines.extend(["", "## Duplicate Test Names", ""])
    if inventory["duplicate_test_name_clusters"]:
        for cluster in inventory["duplicate_test_name_clusters"][:20]:
            lines.append(f"- `{cluster['name']}` appears {cluster['count']} times")
    else:
        lines.append("- None detected")

    return "\n".join(lines) + "\n"


def check_inventory(
    inventory: dict[str, Any],
    *,
    max_file_lines: int | None,
    max_duplicate_clusters: int | None,
) -> list[str]:
    failures: list[str] = []
    if max_file_lines is not None:
        oversized = [entry for entry in inventory["largest_files"] if entry["lines"] > max_file_lines]
        for entry in oversized:
            failures.append(f"{entry['path']} has {entry['lines']} lines, above limit {max_file_lines}")
    if (
        max_duplicate_clusters is not None
        and inventory["totals"]["duplicate_test_name_clusters"] > max_duplicate_clusters
    ):
        failures.append(
            "duplicate test-name clusters: "
            f"{inventory['totals']['duplicate_test_name_clusters']} above limit {max_duplicate_clusters}"
        )
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize the Python test-suite shape.")
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to the current directory.")
    parser.add_argument("--tests-root", default=DEFAULT_TESTS_ROOT.as_posix(), help="Test root relative to the repo.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--check", action="store_true", help="Fail when configured inventory thresholds are exceeded.")
    parser.add_argument("--max-file-lines", type=int, default=None, help="Largest allowed test file in --check mode.")
    parser.add_argument(
        "--max-duplicate-clusters",
        type=int,
        default=None,
        help="Largest allowed duplicate test-name cluster count in --check mode.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = _repo_root(args.repo)
    inventory = collect_inventory(repo_root, Path(args.tests_root))
    output = json.dumps(inventory, indent=2, sort_keys=True) + "\n" if args.json else render_markdown(inventory)
    print(output, end="")

    if args.check:
        failures = check_inventory(
            inventory,
            max_file_lines=args.max_file_lines,
            max_duplicate_clusters=args.max_duplicate_clusters,
        )
        if failures:
            for failure in failures:
                print(f"test-suite-inventory: {failure}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
