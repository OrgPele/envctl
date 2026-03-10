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
    parser.add_argument(
        "--required-scope", action="append", default=[], help="Required scope for untracked-file checks."
    )
    tests_group = parser.add_mutually_exclusive_group()
    tests_group.add_argument(
        "--check-tests",
        dest="check_tests",
        action="store_true",
        help="Run the Python unittest suite as part of the gate.",
    )
    tests_group.add_argument(
        "--skip-tests",
        dest="check_tests",
        action="store_false",
        help="Skip Python unittest execution during gate evaluation.",
    )
    parser.add_argument("--skip-parity-sync", action="store_true", help="Skip manifest/runtime parity-sync check.")
    parser.set_defaults(check_tests=False)
    args = parser.parse_args(argv)

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
        enforce_runtime_readiness_contract=True,
    )
    print(f"shipability.passed: {str(result.passed).lower()}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
