#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_python_path(repo_root: Path) -> None:
    python_root = repo_root / "python"
    if str(python_root) not in sys.path:
        sys.path.insert(0, str(python_root))


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    parser = argparse.ArgumentParser(description="Report shell ownership ledger entries with cutover budget status.")
    parser.add_argument("--repo", default=".", help="Repository root (default: current dir).")
    parser.add_argument("--limit", type=int, default=50, help="Maximum unmigrated rows to print.")
    parser.add_argument(
        "--max-unmigrated",
        type=int,
        default=None,
        help="Optional strict maximum for unmigrated shell ledger entries (default: 0).",
    )
    parser.add_argument(
        "--max-partial-keep",
        type=int,
        default=None,
        help="Optional strict maximum for python_partial_keep_temporarily entries (default: 0).",
    )
    parser.add_argument(
        "--max-intentional-keep",
        type=int,
        default=None,
        help="Optional strict maximum for shell_intentional_keep entries (default: 0).",
    )
    parser.add_argument(
        "--phase",
        default=None,
        help="Optional phase label for budget checks (default: cutover).",
    )
    parser.add_argument(
        "--json-output",
        default="",
        help="Optional output path (relative to repo root) for JSON report.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    _ensure_python_path(repo_root)

    from envctl_engine.shell.shell_prune import evaluate_shell_prune_contract, summarize_unmigrated_entries

    max_unmigrated = args.max_unmigrated if args.max_unmigrated is not None else 0
    max_partial_keep = args.max_partial_keep if args.max_partial_keep is not None else 0
    max_intentional_keep = args.max_intentional_keep if args.max_intentional_keep is not None else 0
    phase = args.phase if args.phase is not None else "cutover"

    result = evaluate_shell_prune_contract(
        repo_root,
        enforce_manifest_coverage=True,
        max_unmigrated=max_unmigrated,
        max_partial_keep=max_partial_keep,
        max_intentional_keep=max_intentional_keep,
        phase=phase,
    )
    rows = summarize_unmigrated_entries(repo_root, limit=max(args.limit, 0))

    print(f"ledger_path: {result.ledger_path}")
    print(f"ledger_generated_at: {result.ledger_generated_at}")
    print(f"ledger_hash: {result.ledger_hash}")
    print(f"shell_migration_status: {'pass' if result.passed else 'fail'}")
    print(f"unmigrated_count: {result.status_counts.get('unmigrated', 0)}")
    print(f"intentional_keep_count: {result.status_counts.get('shell_intentional_keep', 0)}")
    print(f"partial_keep_count: {result.status_counts.get('python_partial_keep_temporarily', 0)}")
    print(f"partial_keep_covered_count: {result.partial_keep_covered_count}")
    print(f"partial_keep_uncovered_count: {result.partial_keep_uncovered_count}")
    print(f"partial_keep_budget_actual: {result.partial_keep_budget_actual}")
    print(f"partial_keep_budget_basis: {result.partial_keep_budget_basis}")
    print(f"intentional_keep_budget_actual: {result.intentional_keep_budget_actual}")
    print(f"max_unmigrated: {max_unmigrated}")
    print(f"max_partial_keep: {max_partial_keep}")
    print(f"max_intentional_keep: {max_intentional_keep}")
    print(f"phase: {phase}")
    if rows:
        print("entries:")
        for row in rows:
            print(
                "- "
                + f"{row['status']} {row['shell_module']}::{row['shell_function']} "
                + f"owner={row['python_owner_module']}#{row['python_owner_symbol']}"
            )
    else:
        print("entries: none")

    payload = {
        "ledger_path": str(result.ledger_path),
        "ledger_generated_at": result.ledger_generated_at,
        "ledger_hash": result.ledger_hash,
        "status_counts": result.status_counts,
        "partial_keep_covered_count": result.partial_keep_covered_count,
        "partial_keep_uncovered_count": result.partial_keep_uncovered_count,
        "partial_keep_budget_actual": result.partial_keep_budget_actual,
        "partial_keep_budget_basis": result.partial_keep_budget_basis,
        "intentional_keep_budget_actual": result.intentional_keep_budget_actual,
        "max_intentional_keep": max_intentional_keep,
        "missing_python_complete_commands": result.missing_python_complete_commands,
        "errors": result.errors,
        "warnings": result.warnings,
        "entries": rows,
    }

    if args.json_output:
        out_path = repo_root / args.json_output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"json_report: {out_path}")

    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
