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
        "--output",
        default="contracts/runtime_feature_matrix.json",
        help="Output path relative to repo root.",
    )
    parser.add_argument(
        "--stdout", action="store_true", help="Print generated JSON to stdout instead of writing to file."
    )
    parser.add_argument("--timestamp", default=None, help="Override generated_at timestamp for deterministic output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    ensure_python_root(repo_root)

    from envctl_engine.runtime_feature_inventory import (
        build_runtime_feature_matrix,
        default_timestamp,
        validate_runtime_feature_matrix_payload,
    )

    payload = build_runtime_feature_matrix(
        repo_root=repo_root,
        generated_at=args.timestamp or default_timestamp(),
    )
    validate_runtime_feature_matrix_payload(payload, repo_root=repo_root)
    rendered = json.dumps(payload, indent=2) + "\n"

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
