#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final


SAFE_PRESET: Final[tuple[str, ...]] = (
    "python/envctl_engine/config",
    "python/envctl_engine/test_output",
    "python/envctl_engine/requirements",
    "python/envctl_engine/debug",
)

CORE_PRESET: Final[tuple[str, ...]] = (
    "python/envctl_engine/shared",
    "python/envctl_engine/state",
)

RISKY_PRESET: Final[tuple[str, ...]] = (
    "python/envctl_engine/actions",
    "python/envctl_engine/startup",
    "python/envctl_engine/runtime",
    "python/envctl_engine/planning",
    "python/envctl_engine/ui",
)

PRESETS: Final[dict[str, tuple[str, ...]]] = {
    "safe": SAFE_PRESET,
    "core": CORE_PRESET,
    "risky": RISKY_PRESET,
    "all": SAFE_PRESET + CORE_PRESET + RISKY_PRESET,
}

SOURCE_TEST_DIR_MAP: Final[dict[str, str]] = {
    "python/envctl_engine/actions": "tests/python/actions",
    "python/envctl_engine/config": "tests/python/config",
    "python/envctl_engine/debug": "tests/python/debug",
    "python/envctl_engine/planning": "tests/python/planning",
    "python/envctl_engine/requirements": "tests/python/requirements",
    "python/envctl_engine/runtime": "tests/python/runtime",
    "python/envctl_engine/shared": "tests/python/shared",
    "python/envctl_engine/shell": "tests/python/shell",
    "python/envctl_engine/startup": "tests/python/startup",
    "python/envctl_engine/state": "tests/python/state",
    "python/envctl_engine/test_output": "tests/python/test_output",
    "python/envctl_engine/ui": "tests/python/ui",
    "python/envctl_engine": "tests/python",
    "python": "tests/python",
}

SCRIPT_TEST_MAP: Final[dict[str, tuple[str, ...]]] = {
    "scripts/analyze_debug_bundle.py": ("tests/python/debug/test_debug_bundle_analyzer.py",),
    "scripts/generate_python_engine_parity_manifest.py": (
        "tests/python/runtime/test_engine_runtime_command_parity.py",
    ),
    "scripts/generate_python_runtime_gap_plan.py": ("tests/python/runtime/test_runtime_feature_inventory.py",),
    "scripts/generate_python_runtime_gap_report.py": ("tests/python/runtime/test_runtime_feature_inventory.py",),
    "scripts/generate_runtime_feature_matrix.py": ("tests/python/runtime/test_runtime_feature_inventory.py",),
    "scripts/python_cleanup.py": ("tests/python/shared/test_python_cleanup_script.py",),
    "scripts/release_shipability_gate.py": ("tests/python/runtime/test_release_shipability_gate.py",),
}


@dataclass(frozen=True)
class PlannedCommand:
    stage: str
    argv: list[str]
    cwd: str
    description: str


def _repo_root(path: str) -> Path:
    repo_root = Path(path).resolve()
    if not repo_root.exists():
        raise SystemExit(f"Repository root does not exist: {repo_root}")
    return repo_root


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _resolved_paths(repo_root: Path, explicit_paths: list[str], presets: list[str]) -> list[str]:
    values = list(explicit_paths)
    for preset in presets:
        values.extend(PRESETS[preset])
    if not values:
        values.extend(PRESETS["all"])
    resolved: list[str] = []
    for value in values:
        path = (repo_root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        if not path.exists():
            raise SystemExit(f"Target path does not exist: {value}")
        try:
            resolved.append(str(path.relative_to(repo_root)))
        except ValueError:
            resolved.append(str(path))
    return _dedupe_preserve_order(resolved)


def _relative_repo_path(repo_root: Path, value: str) -> str:
    path = Path(value)
    resolved = (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        return str(resolved.relative_to(repo_root))
    except ValueError:
        return str(resolved)


def _best_source_test_dir(relative_path: str) -> str:
    matches = [
        source
        for source in SOURCE_TEST_DIR_MAP
        if relative_path == source or relative_path.startswith(source + "/")
    ]
    if not matches:
        return "tests/python"
    best = max(matches, key=len)
    return SOURCE_TEST_DIR_MAP[best]


def _test_module_from_path(path: str) -> str:
    path_obj = Path(path)
    without_suffix = path_obj.with_suffix("")
    return ".".join(without_suffix.parts)


def _test_targets(repo_root: Path, paths: list[str]) -> list[str]:
    targets: list[str] = []
    for path in paths:
        relative_path = _relative_repo_path(repo_root, path)
        if relative_path.startswith("tests/python/"):
            targets.append(relative_path)
            continue
        if relative_path in SCRIPT_TEST_MAP:
            targets.extend(SCRIPT_TEST_MAP[relative_path])
            continue
        if relative_path.startswith("scripts/"):
            targets.append("tests/python/shared")
            continue
        if relative_path.startswith("python/"):
            targets.append(_best_source_test_dir(relative_path))
    return _dedupe_preserve_order(targets) or ["tests/python"]


def build_plan(
    *,
    repo_root: Path,
    paths: list[str],
    include_format: bool,
    include_typecheck: bool,
    include_dead_code: bool,
    include_tests: bool,
    fix: bool,
    min_confidence: int,
) -> list[PlannedCommand]:
    base_python = [sys.executable, "-m"]
    commands: list[PlannedCommand] = []

    ruff_check = base_python + ["ruff", "check", *paths]
    if fix:
        ruff_check.append("--fix")
    commands.append(
        PlannedCommand(
            stage="ruff-check",
            argv=ruff_check,
            cwd=str(repo_root),
            description="Lint Python paths with Ruff",
        )
    )

    if include_format:
        ruff_format = base_python + ["ruff", "format", *paths]
        if not fix:
            ruff_format.append("--check")
        commands.append(
            PlannedCommand(
                stage="ruff-format",
                argv=ruff_format,
                cwd=str(repo_root),
                description="Format Python paths with Ruff",
            )
        )

    if include_typecheck:
        commands.append(
            PlannedCommand(
                stage="basedpyright",
                argv=base_python + ["basedpyright", *paths],
                cwd=str(repo_root),
                description="Run basedpyright on target paths",
            )
        )

    if include_dead_code:
        commands.append(
            PlannedCommand(
                stage="vulture",
                argv=base_python + ["vulture", *paths, "tests/python", "--min-confidence", str(min_confidence)],
                cwd=str(repo_root),
                description="Scan for dead code with Vulture",
            )
        )

    if include_tests:
        for target in _test_targets(repo_root, paths):
            target_path = repo_root / target
            if target_path.is_file():
                argv = [sys.executable, "-m", "unittest", _test_module_from_path(target)]
            else:
                argv = [sys.executable, "-m", "unittest", "discover", "-s", target, "-p", "test_*.py"]
            commands.append(
                PlannedCommand(
                    stage=f"tests:{target}",
                    argv=argv,
                    cwd=str(repo_root),
                    description=f"Run targeted unittest suite for {target}",
                )
            )
    return commands


def _run_plan(plan: list[PlannedCommand]) -> int:
    for item in plan:
        print(f"[{item.stage}] {item.description}")
        print("$", shlex.join(item.argv))
        completed = subprocess.run(item.argv, cwd=item.cwd, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def _print_report(plan: list[PlannedCommand], *, json_output: bool) -> int:
    payload = {
        "mode": "report-only",
        "command_count": len(plan),
        "commands": [asdict(item) for item in plan],
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    print("python-cleanup dry run")
    print(f"planned commands: {len(plan)}")
    for item in plan:
        print(f"- {item.stage}: {item.description}")
        print(f"  cwd: {item.cwd}")
        print(f"  cmd: {shlex.join(item.argv)}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan or execute phased Python cleanup across a repository.")
    parser.add_argument("--repo", default=".", help="Repository root (default: current directory).")
    parser.add_argument("--path", dest="paths", action="append", default=[], help="Target path (repeatable).")
    parser.add_argument(
        "--preset",
        action="append",
        choices=sorted(PRESETS),
        default=[],
        help="Named cleanup preset (repeatable). Defaults to all when no paths/presets are given.",
    )
    parser.add_argument("--skip-format", action="store_true", help="Skip Ruff format/check stage.")
    parser.add_argument("--skip-typecheck", action="store_true", help="Skip basedpyright stage.")
    parser.add_argument("--skip-dead-code", action="store_true", help="Skip Vulture stage.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip targeted unittest stage.")
    parser.add_argument("--min-confidence", type=int, default=80, help="Vulture minimum confidence threshold.")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Actually apply Ruff fixes/formatting instead of report-only.",
    )
    parser.add_argument("--execute", action="store_true", help="Execute the planned commands instead of printing them.")
    parser.add_argument("--json", action="store_true", help="Emit dry-run plan as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = _repo_root(args.repo)
    paths = _resolved_paths(repo_root, args.paths, args.preset)
    plan = build_plan(
        repo_root=repo_root,
        paths=paths,
        include_format=not args.skip_format,
        include_typecheck=not args.skip_typecheck,
        include_dead_code=not args.skip_dead_code,
        include_tests=not args.skip_tests,
        fix=bool(args.fix),
        min_confidence=int(args.min_confidence),
    )
    if not args.execute:
        return _print_report(plan, json_output=bool(args.json))
    return _run_plan(plan)


if __name__ == "__main__":
    raise SystemExit(main())
