#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    from scripts._bootstrap import ensure_python_root
except ModuleNotFoundError:
    from _bootstrap import ensure_python_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Repository root (default: current dir).")
    parser.add_argument(
        "--report",
        default="contracts/python_runtime_gap_report.json",
        help="Gap report path relative to repo root.",
    )
    parser.add_argument(
        "--output",
        default="todo/plans/refactoring/python-runtime-gap-closure.md",
        help="Output markdown path relative to repo root.",
    )
    parser.add_argument(
        "--stdout", action="store_true", help="Print generated markdown to stdout instead of writing to file."
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    ensure_python_root(repo_root)

    from envctl_engine.runtime_feature_inventory import render_python_runtime_gap_closure_plan

    report_path = repo_root / args.report
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    rendered = render_python_runtime_gap_closure_plan(report_payload=report_payload)
    if not rendered.endswith("\n"):
        rendered += "\n"

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    output_path = repo_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
