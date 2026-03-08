#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_python_path(repo_root: Path) -> None:
    python_root = repo_root / "python"
    if str(python_root) not in sys.path:
        sys.path.insert(0, str(python_root))


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    parser = argparse.ArgumentParser(description="Verify envctl shell prune contract against the ownership ledger.")
    parser.add_argument("--repo", default=".", help="Repository root (default: current dir).")
    parser.add_argument(
        "--skip-manifest-coverage",
        action="store_true",
        help="Skip parity-manifest python_complete command coverage checks.",
    )
    parser.add_argument(
        "--max-unmigrated",
        type=int,
        default=None,
        help="Optional strict maximum for unmigrated shell ledger entries.",
    )
    parser.add_argument(
        "--max-partial-keep",
        type=int,
        default=None,
        help="Optional strict maximum for python_partial_keep_temporarily shell ledger entries.",
    )
    parser.add_argument(
        "--max-intentional-keep",
        type=int,
        default=None,
        help="Optional strict maximum for shell_intentional_keep shell ledger entries (default: 0).",
    )
    parser.add_argument(
        "--phase",
        default=None,
        help="Optional phase label included in budget enforcement output.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    _ensure_python_path(repo_root)

    from envctl_engine.shell.shell_prune import evaluate_shell_prune_contract

    max_unmigrated = args.max_unmigrated if args.max_unmigrated is not None else 0
    max_partial_keep = args.max_partial_keep if args.max_partial_keep is not None else 0
    max_intentional_keep = args.max_intentional_keep if args.max_intentional_keep is not None else 0
    phase = args.phase if args.phase is not None else "cutover"

    result = evaluate_shell_prune_contract(
        repo_root,
        enforce_manifest_coverage=not args.skip_manifest_coverage,
        max_unmigrated=max_unmigrated,
        max_partial_keep=max_partial_keep,
        max_intentional_keep=max_intentional_keep,
        phase=phase,
    )
    print(f"shell_prune.passed: {str(result.passed).lower()}")
    print(f"shell_prune.ledger_path: {result.ledger_path}")
    print(f"shell_prune.ledger_generated_at: {result.ledger_generated_at}")
    print(f"shell_prune.ledger_hash: {result.ledger_hash}")
    print(f"shell_prune.unmigrated_count: {result.status_counts.get('unmigrated', 0)}")
    print(f"shell_prune.intentional_keep_count: {result.status_counts.get('shell_intentional_keep', 0)}")
    print(
        "shell_prune.partial_keep_count: "
        f"{result.status_counts.get('python_partial_keep_temporarily', 0)}"
    )
    print(f"shell_prune.partial_keep_covered_count: {result.partial_keep_covered_count}")
    print(f"shell_prune.partial_keep_uncovered_count: {result.partial_keep_uncovered_count}")
    print(f"shell_prune.partial_keep_budget_actual: {result.partial_keep_budget_actual}")
    print(f"shell_prune.partial_keep_budget_basis: {result.partial_keep_budget_basis}")
    print(f"shell_prune.intentional_keep_budget_actual: {result.intentional_keep_budget_actual}")
    if result.max_unmigrated is not None:
        print(f"shell_prune.max_unmigrated: {result.max_unmigrated}")
    if result.max_partial_keep is not None:
        print(f"shell_prune.max_partial_keep: {result.max_partial_keep}")
    if result.max_intentional_keep is not None:
        print(f"shell_prune.max_intentional_keep: {result.max_intentional_keep}")
    if result.phase:
        print(f"shell_prune.phase: {result.phase}")
    if result.missing_python_complete_commands:
        print(
            "shell_prune.missing_python_complete_commands: "
            + ",".join(result.missing_python_complete_commands)
        )
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
