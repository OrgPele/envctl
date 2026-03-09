#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
import sys


def build_manifest(*, generated_at: str) -> dict[str, object]:
    return {
        "generated_at": generated_at,
        "engine_default": "python",
        "fallback": {
            "env_var": "ENVCTL_ENGINE_SHELL_FALLBACK",
            "description": "Set true to force shell engine fallback during migration window",
        },
        "modes": {
            "main": {
                "start": "python_complete",
                "resume": "python_complete",
                "restart": "python_complete",
                "stop": "python_complete",
                "stop-all": "python_complete",
                "blast-all": "python_complete",
            },
            "trees": {
                "start": "python_complete",
                "plan": "python_complete",
                "resume": "python_complete",
                "restart": "python_complete",
                "stop": "python_complete",
                "stop-all": "python_complete",
                "blast-all": "python_complete",
            },
        },
        "commands": {
            "config": "python_complete",
            "dashboard": "python_complete",
            "doctor": "python_complete",
            "test": "python_complete",
            "logs": "python_complete",
            "health": "python_complete",
            "errors": "python_complete",
            "delete-worktree": "python_complete",
            "blast-worktree": "python_complete",
            "pr": "python_complete",
            "commit": "python_complete",
            "review": "python_complete",
            "migrate": "python_complete",
            "list-commands": "python_complete",
            "list-targets": "python_complete",
            "help": "python_complete",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Repository root (default: current dir).")
    parser.add_argument(
        "--output",
        default="contracts/python_engine_parity_manifest.json",
        help="Manifest output path relative to repo root.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print generated JSON to stdout instead of writing to file.")
    parser.add_argument(
        "--timestamp",
        default=None,
        help="Override generated_at timestamp for deterministic output.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    generated_at = args.timestamp or datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    payload = build_manifest(generated_at=generated_at)
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
