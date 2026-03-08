#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import RouteError, parse_route


@dataclass(frozen=True)
class Case:
    name: str
    argv: tuple[str, ...]


@dataclass
class Snapshot:
    parse_error: bool
    mode: str
    command: str
    resume_requested: bool
    projects: list[str]
    flags: dict[str, object]
    error: str = ""


DEFAULT_CASES: tuple[Case, ...] = (
    Case("mode_trees", ("--trees",)),
    Case("mode_main", ("--main",)),
    Case("cmd_resume", ("--resume",)),
    Case("cmd_restart", ("restart",)),
    Case("cmd_health", ("health",)),
    Case("cmd_analyze", ("analyze",)),
    Case("cmd_migrate", ("migrate",)),
    Case("cmd_list_commands", ("--list-commands",)),
    Case("cmd_list_targets", ("--list-targets",)),
    Case("project_single", ("--project", "foo",)),
    Case("project_multi_csv", ("--projects", "foo,bar",)),
    Case("value_missing_project", ("--project", "--help",)),
    Case("value_missing_service", ("--service", "--help",)),
    Case("pair_missing_setup_worktrees", ("--setup-worktrees", "feat-x", "--help",)),
    Case("pair_missing_setup_worktree", ("--setup-worktree", "feat-x", "--help",)),
    Case("env_fresh_true", ("fresh=true",)),
    Case("env_resume_true", ("resume=true",)),
    Case("env_docker_true", ("docker=true",)),
    Case("env_docker_temp_true", ("docker-temp=true",)),
    Case("env_force_true", ("force=true",)),
    Case("env_seed_true", ("copy-db-storage=true",)),
    Case("env_seed_false", ("copy-db-storage=false",)),
    Case("env_parallel_true", ("parallel-trees=true",)),
    Case("env_parallel_false", ("parallel-trees=false",)),
    Case("env_parallel_max", ("parallel-trees-max=7",)),
    Case("env_frontend_test_runner", ("FRONTEND_TEST_RUNNER=vitest",)),
    Case("long_no_parallel", ("--no-parallel-trees",)),
    Case("short_unknown_ignored", ("-x",)),
    Case("blast_flags", ("blast-all", "--blast-keep-worktree-volumes", "--blast-remove-main-volumes",)),
)


def _bash_script() -> str:
    return """
set -euo pipefail
source \"$1/lib/engine/lib/run_all_trees_cli.sh\"
shift
run_all_trees_cli_init_config
run_all_trees_cli_parse_args \"$@\"
printf 'TREES_MODE=%s\n' \"${TREES_MODE}\"
printf 'RUN_SH_COMMAND=%s\n' \"${RUN_SH_COMMAND}\"
printf 'RUN_SH_COMMAND_LIST_COMMANDS=%s\n' \"${RUN_SH_COMMAND_LIST_COMMANDS}\"
printf 'RUN_SH_COMMAND_LIST_TARGETS=%s\n' \"${RUN_SH_COMMAND_LIST_TARGETS}\"
printf 'SHOW_HELP=%s\n' \"${SHOW_HELP}\"
printf 'RESUME_MODE=%s\n' \"${RESUME_MODE}\"
printf 'FRESH_INSTALL=%s\n' \"${FRESH_INSTALL}\"
printf 'DOCKER_MODE=%s\n' \"${DOCKER_MODE}\"
printf 'DOCKER_TEMP_MODE=%s\n' \"${DOCKER_TEMP_MODE}\"
printf 'FORCE_PORTS=%s\n' \"${FORCE_PORTS}\"
printf 'SEED_REQUIREMENTS_FROM_BASE=%s\n' \"${SEED_REQUIREMENTS_FROM_BASE}\"
printf 'RUN_SH_OPT_PARALLEL_TREES=%s\n' \"${RUN_SH_OPT_PARALLEL_TREES}\"
printf 'RUN_SH_OPT_PARALLEL_TREES_MAX=%s\n' \"${RUN_SH_OPT_PARALLEL_TREES_MAX}\"
printf 'FRONTEND_TEST_RUNNER=%s\n' \"${FRONTEND_TEST_RUNNER}\"
printf 'RUN_SH_COMMAND_ONLY=%s\n' \"${RUN_SH_COMMAND_ONLY}\"
printf 'RUN_SH_COMMAND_RESUME=%s\n' \"${RUN_SH_COMMAND_RESUME}\"
printf 'AUTO_RESUME=%s\n' \"${AUTO_RESUME}\"
printf 'RUN_SH_COMMAND_TARGETS='; (IFS=','; printf '%s' \"${RUN_SH_COMMAND_TARGETS[*]}\"); printf '\n'
printf 'RUN_ALL_TREES_ARG_ERRORS='; (IFS=$'\\x1f'; printf '%s' \"${RUN_ALL_TREES_ARG_ERRORS[*]}\"); printf '\n'
""".strip()


def _run_bash(case: Case) -> Snapshot:
    proc = subprocess.run(
        [
            "bash",
            "-lc",
            _bash_script(),
            "_",
            str(REPO_ROOT),
            *case.argv,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    raw: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key] = value

    errors_raw = raw.get("RUN_ALL_TREES_ARG_ERRORS", "")
    errors = [token for token in errors_raw.split("\x1f") if token]

    projects = [
        token.split(":", 1)[1]
        for token in raw.get("RUN_SH_COMMAND_TARGETS", "").split(",")
        if token.startswith("project:")
    ]

    command = raw.get("RUN_SH_COMMAND", "")
    if raw.get("RUN_SH_COMMAND_LIST_COMMANDS") == "true":
        command = "list-commands"
    elif raw.get("RUN_SH_COMMAND_LIST_TARGETS") == "true":
        command = "list-targets"
    elif raw.get("SHOW_HELP") == "true":
        command = "help"
    elif not command:
        command = "start"

    return Snapshot(
        parse_error=bool(errors),
        mode="trees" if raw.get("TREES_MODE") == "true" else "main",
        command=command,
        resume_requested=raw.get("RESUME_MODE") == "true",
        projects=projects,
        flags={
            "fresh": raw.get("FRESH_INSTALL") == "true",
            "docker": raw.get("DOCKER_MODE") == "true",
            "docker_temp": raw.get("DOCKER_TEMP_MODE") == "true",
            "force": raw.get("FORCE_PORTS") == "true",
            "seed_requirements_from_base": raw.get("SEED_REQUIREMENTS_FROM_BASE") == "true",
            "parallel_trees": raw.get("RUN_SH_OPT_PARALLEL_TREES") == "true",
            "parallel_trees_max": raw.get("RUN_SH_OPT_PARALLEL_TREES_MAX", ""),
            "frontend_test_runner": raw.get("FRONTEND_TEST_RUNNER", ""),
            "skip_startup": raw.get("RUN_SH_COMMAND_ONLY") == "true",
            "load_state": raw.get("RUN_SH_COMMAND_RESUME") == "true",
            "no_resume": raw.get("AUTO_RESUME") == "false",
        },
        error=errors[0] if errors else "",
    )


def _run_python(case: Case) -> Snapshot:
    try:
        route = parse_route(list(case.argv), env={})
    except RouteError as exc:
        return Snapshot(
            parse_error=True,
            mode="main",
            command="start",
            resume_requested=False,
            projects=[],
            flags={},
            error=str(exc),
        )

    return Snapshot(
        parse_error=False,
        mode=route.mode,
        command=route.command,
        resume_requested=route.command == "resume" or bool(route.flags.get("resume")),
        projects=list(route.projects),
        flags={
            "fresh": route.flags.get("fresh"),
            "docker": route.flags.get("docker"),
            "docker_temp": route.flags.get("docker_temp"),
            "force": route.flags.get("force"),
            "seed_requirements_from_base": route.flags.get("seed_requirements_from_base"),
            "parallel_trees": route.flags.get("parallel_trees"),
            "parallel_trees_max": route.flags.get("parallel_trees_max"),
            "frontend_test_runner": route.flags.get("frontend_test_runner"),
            "skip_startup": route.flags.get("skip_startup"),
            "load_state": route.flags.get("load_state"),
            "no_resume": route.flags.get("no_resume"),
        },
    )


def _diff_snapshots(bash: Snapshot, py: Snapshot) -> dict[str, dict[str, object]]:
    diffs: dict[str, dict[str, object]] = {}
    if bash.parse_error != py.parse_error:
        diffs["parse_error"] = {"bash": bash.parse_error, "python": py.parse_error}
    if bash.mode != py.mode:
        diffs["mode"] = {"bash": bash.mode, "python": py.mode}
    if bash.command != py.command:
        diffs["command"] = {"bash": bash.command, "python": py.command}
    if bash.resume_requested != py.resume_requested:
        diffs["resume_requested"] = {"bash": bash.resume_requested, "python": py.resume_requested}
    if bash.projects != py.projects:
        diffs["projects"] = {"bash": bash.projects, "python": py.projects}

    all_flag_keys = set(bash.flags).union(py.flags)
    for key in sorted(all_flag_keys):
        if bash.flags.get(key) != py.flags.get(key):
            diffs[f"flags.{key}"] = {"bash": bash.flags.get(key), "python": py.flags.get(key)}

    return diffs


def _normalize_command(command: str, *, resume_requested: bool) -> str:
    if command == "start" and resume_requested:
        return "resume"
    return command


def _effective_python_flag(key: str, value: object) -> object:
    default_values: dict[str, object] = {
        "parallel_trees": True,
        "parallel_trees_max": "4",
        "frontend_test_runner": "bun",
    }
    if value is not None:
        return value
    if key in default_values:
        return default_values[key]
    if key in {"fresh", "docker", "docker_temp", "force", "seed_requirements_from_base", "skip_startup", "load_state", "no_resume"}:
        return False
    return ""


def _diff_effective(*, bash: Snapshot, py: Snapshot) -> dict[str, dict[str, object]]:
    diffs: dict[str, dict[str, object]] = {}
    if bash.parse_error != py.parse_error:
        diffs["parse_error"] = {"bash": bash.parse_error, "python": py.parse_error}
        return diffs

    if bash.mode != py.mode:
        diffs["mode"] = {"bash": bash.mode, "python": py.mode}

    bash_command = _normalize_command(bash.command, resume_requested=bash.resume_requested)
    py_command = _normalize_command(py.command, resume_requested=py.resume_requested)
    if bash_command != py_command:
        diffs["command"] = {"bash": bash_command, "python": py_command}

    if bash.projects != py.projects:
        diffs["projects"] = {"bash": bash.projects, "python": py.projects}

    all_flag_keys = set(bash.flags).union(py.flags)
    for key in sorted(all_flag_keys):
        bash_value = bash.flags.get(key)
        py_value = _effective_python_flag(key, py.flags.get(key))
        if bash_value != py_value:
            diffs[f"flags.{key}"] = {"bash": bash_value, "python": py_value}

    return diffs


def audit(cases: Iterable[Case]) -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    for case in cases:
        bash = _run_bash(case)
        py = _run_python(case)
        diff = _diff_effective(bash=bash, py=py)
        if diff:
            mismatches.append(
                {
                    "case": case.name,
                    "argv": list(case.argv),
                    "diff": diff,
                    "bash": asdict(bash),
                    "python": asdict(py),
                }
            )
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Python command parser parity against shell parser")
    parser.add_argument("--json", action="store_true", help="Print mismatches as JSON")
    parser.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="Exit non-zero when mismatches are found",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Case name to run (repeatable). Defaults to full matrix.",
    )
    args = parser.parse_args()

    cases = list(DEFAULT_CASES)
    if args.case:
        selected = set(args.case)
        cases = [case for case in cases if case.name in selected]

    mismatches = audit(cases)

    if args.json:
        print(json.dumps({"mismatch_count": len(mismatches), "mismatches": mismatches}, indent=2, sort_keys=True))
    else:
        print(f"Ran {len(cases)} parser parity cases")
        print(f"Mismatches: {len(mismatches)}")
        for item in mismatches:
            print(f"- {item['case']}: {item['diff']}")

    if mismatches and args.fail_on_mismatch:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
