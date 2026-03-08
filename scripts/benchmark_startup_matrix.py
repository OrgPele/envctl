#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


DEFAULT_DEBUG_ENV = {
    "ENVCTL_DEBUG_UI_MODE": "deep",
    "ENVCTL_DEBUG_RESTORE_TIMING": "1",
    "ENVCTL_DEBUG_REQUIREMENTS_TRACE": "1",
    "ENVCTL_DEBUG_DOCKER_COMMAND_TIMING": "1",
    "ENVCTL_DEBUG_STARTUP_BREAKDOWN": "1",
}


def _run_case(
    *,
    envctl: Path,
    repo: Path,
    args: list[str],
    env: dict[str, str],
    timeout_seconds: float,
) -> dict[str, object]:
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            [str(envctl), "--repo", str(repo), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        completed = subprocess.CompletedProcess(
            args=[str(envctl), "--repo", str(repo), *args],
            returncode=124,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "",
        )
    duration_ms = round((time.monotonic() - started) * 1000.0, 2)
    run_id = ""
    session_id = ""
    for line in completed.stdout.splitlines():
        if line.startswith("run_id:"):
            run_id = line.split(":", 1)[1].strip()
        elif line.startswith("session_id:"):
            session_id = line.split(":", 1)[1].strip()
    return {
        "args": args,
        "duration_ms": duration_ms,
        "returncode": completed.returncode,
        "run_id": run_id or None,
        "session_id": session_id or None,
        "timed_out": timed_out,
        "stdout_tail": completed.stdout.splitlines()[-40:],
        "stderr_tail": completed.stderr.splitlines()[-40:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark envctl startup and inspection matrix.")
    parser.add_argument("--envctl", default="/Users/kfiramar/projects/envctl/bin/envctl")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()

    envctl = Path(args.envctl).expanduser().resolve()
    repo = Path(args.repo).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve() if args.out else (repo / ".envctl-benchmark.json")

    env = dict(os.environ)
    env.update(DEFAULT_DEBUG_ENV)
    env["PATH"] = str(Path("/usr/bin")) + ":" + str(Path("/opt/homebrew/bin")) + ":" + str(Path.home() / ".local/bin") + ":" + env.get("PATH", "")

    cases = {
        "main_warm": ["--headless", "--main"],
        "main_cold": ["--headless", "--main", "--no-resume"],
        "trees_warm": ["--headless", "--trees", "--all"],
        "trees_cold": ["--headless", "--trees", "--all", "--no-resume"],
        "plan_warm": ["--headless", "--plan", "all"],
        "plan_cold": ["--headless", "--plan", "all", "--no-resume"],
        "health": ["health", "--trees", "--json"],
        "logs": ["logs", "--trees", "--json"],
        "errors": ["errors", "--trees", "--json"],
        "clear_logs": ["clear-logs", "--trees", "--json"],
        "stop_all": ["stop-all", "--trees", "--headless"],
        "blast_all": ["blast-all", "--trees", "--headless"],
    }

    payload = {
        "repo": str(repo),
        "envctl": str(envctl),
        "generated_at_epoch_ms": round(time.time() * 1000.0),
        "cases": {},
    }
    for name, command_args in cases.items():
        payload["cases"][name] = _run_case(
            envctl=envctl,
            repo=repo,
            args=command_args,
            env=env,
            timeout_seconds=args.timeout_seconds,
        )

    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
