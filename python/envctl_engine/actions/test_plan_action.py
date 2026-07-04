from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import Iterable, Mapping

from envctl_engine.actions.action_pytest_parallel_support import (
    PytestParallelPolicy,
    parallelized_pytest_args,
)
from envctl_engine.config.local_artifacts import is_envctl_local_artifact_path

_PREFIX_TESTS: tuple[tuple[str, str, str], ...] = (
    ("python/envctl_engine/planning/", "tests/python/planning", "planning engine change"),
    ("python/envctl_engine/actions/", "tests/python/actions", "action command change"),
    ("python/envctl_engine/config/", "tests/python/config", "configuration change"),
    ("python/envctl_engine/startup/", "tests/python/startup", "startup change"),
    ("python/envctl_engine/runtime/", "tests/python/runtime", "runtime command change"),
    ("python/envctl_engine/requirements/", "tests/python/requirements", "requirements change"),
    ("python/envctl_engine/ui/", "tests/python/ui", "UI command change"),
)

_PROMPT_PREFIX = "python/envctl_engine/runtime/prompt_templates/"
_PROMPT_TEST = "tests/python/runtime/test_prompt_install_support_templates.py"
_DOC_TOOLING_PREFIXES = ("docs/", "README.md", "AGENTS.md", ".serena/")
_DOC_TOOLING_TESTS = (
    "tests/python/shared/test_validation_workflow_contract.py tests/python/shared/test_serena_config.py"
)
_TEST_COMMAND_ENV_REMOVE = {
    "ENVCTL_EXECUTION_ROOT",
    "ENVCTL_INVOCATION_CWD",
    "ENVCTL_ROOT_DIR",
    "ENVCTL_USE_REPO_WRAPPER",
    "ENVCTL_WRAPPER_ORIGINAL_ARGV0",
    "ENVCTL_WRAPPER_PYTHON_REEXEC",
    "RUN_ENGINE_PATH",
    "RUN_LAUNCHER_CONTEXT",
    "RUN_LAUNCHER_NAME",
    "RUN_REPO_ROOT",
    "RUN_SH_RUNTIME_DIR",
}


def build_test_plan(
    *,
    repo_root: Path,
    project_root: Path,
    project_name: str,
    changed_files: Iterable[str] | None = None,
) -> dict[str, object]:
    repo_root = Path(repo_root).resolve()
    project_root = Path(project_root).resolve()
    raw_changed_files = changed_files if changed_files is not None else _collect_changed_files(project_root)
    files = _normalize_changed_files(raw_changed_files)
    commands: list[dict[str, object]] = []
    seen_commands: set[str] = set()

    def add(command: str, *, confidence: str, reason: str, files_for_reason: Iterable[str]) -> None:
        if command in seen_commands:
            return
        seen_commands.add(command)
        commands.append(
            {
                "command": command,
                "confidence": confidence,
                "reason": reason,
                "matched_files": list(files_for_reason),
            }
        )

    for prefix, test_path, reason in _PREFIX_TESTS:
        matched = [path for path in files if path.startswith(prefix)]
        if matched:
            add(f"uv run --extra dev pytest -q {test_path}", confidence="high", reason=reason, files_for_reason=matched)

    prompt_matches = [path for path in files if path.startswith(_PROMPT_PREFIX)]
    if prompt_matches:
        add(
            f"uv run --extra dev pytest -q {_PROMPT_TEST}",
            confidence="high",
            reason="prompt template change",
            files_for_reason=prompt_matches,
        )

    script_matches = [path for path in files if path.startswith("scripts/") or path.endswith(".json")]
    if script_matches:
        add(
            "uv run --extra dev pytest -q tests/python/runtime/test_release_shipability_gate.py "
            "tests/python/runtime/test_release_shipability_gate_cli.py",
            confidence="medium",
            reason="contract-affecting script or JSON change",
            files_for_reason=script_matches,
        )

    docs_matches = [path for path in files if path.startswith(_DOC_TOOLING_PREFIXES)]
    if docs_matches:
        add(
            f"uv run --extra dev pytest -q {_DOC_TOOLING_TESTS}",
            confidence="medium",
            reason="documentation or agent tooling contract change",
            files_for_reason=docs_matches,
        )

    ruff_files = [
        path
        for path in files
        if path.endswith(".py")
        and (path.startswith("python/") or path.startswith("tests/") or path.startswith("scripts/"))
    ]
    if ruff_files:
        add(
            "uv run --extra dev ruff check " + " ".join(shlex.quote(path) for path in ruff_files),
            confidence="high",
            reason="Python files changed",
            files_for_reason=ruff_files,
        )

    if not commands:
        add(
            "uv run --extra dev pytest -q tests/python",
            confidence="low",
            reason="no focused mapping matched changed files",
            files_for_reason=files,
        )

    touched_areas = {path.split("/", 3)[2] for path in files if path.startswith("python/envctl_engine/")}
    contract_affecting = bool(script_matches)
    broad = len(touched_areas) > 1 or contract_affecting
    reason = "contract-affecting changes" if contract_affecting else "multiple envctl engine areas changed"
    return {
        "contract_version": "envctl.test_plan.v1",
        "project": project_name,
        "repo_root": str(repo_root),
        "project_root": str(project_root),
        "changed_files": files,
        "commands": commands,
        "full_gate": {
            "recommended": broad,
            "reason": reason if broad else "focused checks cover the changed area",
            "command": "uv run --extra dev pytest -q tests/python",
        },
    }


def run_test_plan_action(context: object, *, json_output: bool = False, dry_run: bool = False) -> int:
    repo_root = Path(getattr(context, "repo_root")).resolve()
    project_root = Path(getattr(context, "project_root")).resolve()
    project_name = str(getattr(context, "project_name", project_root.name))
    payload = build_test_plan(repo_root=repo_root, project_root=project_root, project_name=project_name)
    exit_code = 0
    if not dry_run:
        run_payload, exit_code = _run_plan_commands(
            payload,
            cwd=project_root,
            env=_context_mapping(context, "env", os.environ),
            config_raw=_context_mapping(context, "config_raw", {}),
            route_flags=_context_mapping(context, "route_flags", {}),
        )
        payload["run"] = run_payload
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if not dry_run:
            run_result = payload.get("run")
            result_items = run_result.get("results") if isinstance(run_result, Mapping) else None
            if not isinstance(result_items, list):
                result_items = []
            for result in result_items:
                if isinstance(result, Mapping):
                    print(f"{result.get('status', 'unknown')}: {result.get('command', '')}")
                    for name in ("stdout", "stderr"):
                        text = result.get(name)
                        if isinstance(text, str) and text:
                            print(f"{name}:")
                            print(text, end="" if text.endswith("\n") else "\n")
        else:
            for command in _command_items(payload):
                print(command.get("command", ""))
    return exit_code


def _run_plan_commands(
    payload: Mapping[str, object],
    *,
    cwd: Path,
    env: Mapping[str, object] | None = None,
    config_raw: Mapping[str, object] | None = None,
    route_flags: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], int]:
    commands = [str(item.get("command") or "").strip() for item in _command_items(payload)]
    results: list[dict[str, object]] = []
    exit_code = 0
    pytest_parallel = PytestParallelPolicy(
        env=env or {},
        config_raw=config_raw or {},
        route_flags=route_flags or {},
        include_focused_env=True,
    )
    for index, command in enumerate(commands):
        if not command:
            continue
        command_args = shlex.split(command)
        executed_args = _execution_args(command_args, cwd=cwd)
        executed_args = parallelized_pytest_args(executed_args, cwd=cwd, policy=pytest_parallel)
        started = time.monotonic()
        completed = subprocess.run(
            executed_args,
            cwd=str(cwd),
            env=_test_command_env(),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            text=True,
        )
        duration = round(time.monotonic() - started, 3)
        result = _command_result(
            command=command,
            executed_args=executed_args,
            returncode=completed.returncode,
            duration=duration,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        results.append(result)
        if completed.returncode != 0:
            exit_code = completed.returncode
            skipped = commands[index + 1 :]
            return {
                "status": "failed",
                "results": results,
                "skipped_commands": skipped,
            }, exit_code
    return {
        "status": "passed",
        "results": results,
        "skipped_commands": [],
    }, exit_code


def _execution_args(command_args: list[str], *, cwd: Path) -> list[str]:
    if command_args[:4] != ["uv", "run", "--extra", "dev"] or len(command_args) < 5:
        return command_args
    tool = command_args[4]
    tool_args = command_args[5:]
    venv_bin = Path(cwd) / ".venv" / "bin"
    if tool == "pytest":
        python = venv_bin / "python"
        if python.is_file():
            return [str(python), "-m", "pytest", *tool_args]
    tool_path = venv_bin / tool
    if tool_path.is_file():
        return [str(tool_path), *tool_args]
    return command_args


def _context_mapping(context: object, name: str, default: Mapping[str, object]) -> Mapping[str, object]:
    value = getattr(context, name, default)
    return value if isinstance(value, Mapping) else default


def _command_result(
    *,
    command: str,
    executed_args: list[str],
    returncode: int,
    duration: float,
    stdout: str | None = None,
    stderr: str | None = None,
) -> dict[str, object]:
    status = "passed" if returncode == 0 else "failed"
    result: dict[str, object] = {
        "command": command,
        "returncode": returncode,
        "status": status,
        "duration_seconds": duration,
    }
    executed_command = shlex.join(executed_args)
    if executed_command != command:
        result["executed_command"] = executed_command
    if returncode != 0:
        result["stdout"] = stdout or ""
        result["stderr"] = stderr or ""
    if returncode < 0:
        signal_number = abs(returncode)
        result["status"] = "terminated_by_signal"
        result["signal"] = signal_number
        result["signal_name"] = _signal_name(signal_number)
    return result


def _test_command_env() -> dict[str, str]:
    env_map = dict(os.environ)
    for key in _TEST_COMMAND_ENV_REMOVE:
        env_map.pop(key, None)
    return env_map


def _signal_name(signal_number: int) -> str:
    try:
        return signal.Signals(signal_number).name
    except ValueError:
        return f"SIG{signal_number}"


def _command_items(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    commands = payload.get("commands")
    if not isinstance(commands, list):
        return []
    return [item for item in commands if isinstance(item, Mapping)]


def _collect_changed_files(project_root: Path) -> tuple[str, ...]:
    groups = (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    paths: list[str] = []
    for args in groups:
        completed = subprocess.run(args, cwd=str(project_root), text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            continue
        paths.extend(completed.stdout.splitlines())
    return tuple(paths)


def _normalize_changed_files(paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = str(raw or "").strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if not path or is_envctl_local_artifact_path(path) or path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    return sorted(normalized)
