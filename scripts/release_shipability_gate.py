#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_python_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    python_root = repo_root / "python"
    if str(python_root) not in sys.path:
        sys.path.insert(0, str(python_root))


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    parser = argparse.ArgumentParser(description="Validate envctl Python cutover shipability gates.")
    parser.add_argument("--repo", default=".", help="Repository root to evaluate (default: current dir).")
    parser.add_argument("--required-path", action="append", default=[], help="Required path (repeatable).")
    parser.add_argument("--required-scope", action="append", default=[], help="Required scope for untracked-file checks.")
    tests_group = parser.add_mutually_exclusive_group()
    tests_group.add_argument("--check-tests", dest="check_tests", action="store_true", help="Run Python + BATS suites as part of the gate.")
    tests_group.add_argument("--skip-tests", dest="check_tests", action="store_false", help="Skip Python + BATS suites during gate evaluation.")
    parser.add_argument("--skip-parity-sync", action="store_true", help="Skip manifest/runtime parity-sync check.")
    parser.add_argument(
        "--skip-shell-prune-contract",
        action="store_true",
        help="Skip shell ownership ledger prune-contract checks.",
    )
    parser.add_argument(
        "--shell-prune-max-unmigrated",
        type=int,
        default=None,
        help="Optional strict maximum for unmigrated shell ledger entries.",
    )
    parser.add_argument(
        "--shell-prune-max-partial-keep",
        type=int,
        default=None,
        help="Optional strict maximum for python_partial_keep_temporarily shell ledger entries.",
    )
    parser.add_argument(
        "--shell-prune-max-intentional-keep",
        type=int,
        default=None,
        help="Optional strict maximum for shell_intentional_keep shell ledger entries.",
    )
    parser.add_argument(
        "--shell-prune-phase",
        default=None,
        help="Optional phase label included in shell-prune budget enforcement output.",
    )
    parser.add_argument(
        "--require-shell-budget-complete",
        action="store_true",
        help="Fail when any shell budget input is omitted (unmigrated/partial-keep/intentional-keep).",
    )
    parser.set_defaults(check_tests=False)
    args = parser.parse_args(argv)
    shell_prune_max_unmigrated = args.shell_prune_max_unmigrated
    shell_prune_max_partial_keep = args.shell_prune_max_partial_keep
    shell_prune_max_intentional_keep = args.shell_prune_max_intentional_keep
    shell_prune_phase = args.shell_prune_phase
    require_shell_budget_complete = bool(args.require_shell_budget_complete)
    phase_text = str(shell_prune_phase or "").strip().lower()
    if not require_shell_budget_complete and shell_prune_max_unmigrated is not None and phase_text == "cutover":
        require_shell_budget_complete = True

    _ensure_python_path()
    from envctl_engine.shell.release_gate import evaluate_shipability

    repo_root = Path(args.repo).resolve()
    required_paths = args.required_path or None
    required_scopes = args.required_scope or None
    result = evaluate_shipability(
        repo_root=repo_root,
        required_paths=required_paths,
        required_scopes=required_scopes,
        check_tests=bool(args.check_tests),
        enforce_parity_sync=not args.skip_parity_sync,
        enforce_shell_prune_contract=not args.skip_shell_prune_contract,
        shell_prune_max_unmigrated=shell_prune_max_unmigrated,
        shell_prune_max_partial_keep=shell_prune_max_partial_keep,
        shell_prune_max_intentional_keep=shell_prune_max_intentional_keep,
        shell_prune_phase=shell_prune_phase,
        require_shell_budget_complete=require_shell_budget_complete,
    )
    print(f"shipability.passed: {str(result.passed).lower()}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
