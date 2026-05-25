from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.runtime.runtime_context import optional_process_runtime


_SESSION_PREFIX = "envctl-codex"
_DEFAULT_WINDOW = "codex"
_NAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_-]+")
_CODEX_BYPASS_ARGS = ("--dangerously-bypass-approvals-and-sandbox",)


@dataclass(slots=True, frozen=True)
class CodexTmuxLaunchPlan:
    repo_root: Path
    session_name: str
    window_name: str
    codex_command: tuple[str, ...]
    create_session: bool
    attach_via: str
    create_command: tuple[str, ...] | None
    attach_command: tuple[str, ...]


def run_codex_tmux_command(runtime: Any, route: object) -> int:
    flags = getattr(route, "flags", {}) or {}
    passthrough_args = tuple(str(token) for token in (getattr(route, "passthrough_args", []) or []) if str(token))
    json_output = bool(flags.get("json"))
    dry_run = bool(flags.get("dry_run"))

    if json_output and not dry_run:
        print("codex-tmux supports --json only together with --dry-run.", file=sys.stderr)
        return 1

    if bool(flags.get("omx")):
        missing = [name for name in ("omx",) if not bool(runtime._command_exists(name))]
        if missing:
            print(f"Missing required executables: {', '.join(missing)}", file=sys.stderr)
            return 1
        command = _omx_command_for_flags(flags, passthrough_args=passthrough_args)
        if dry_run:
            _print_omx_launch_plan(runtime, command=command, json_output=json_output)
            return 0
        return _attach_interactive(runtime, command, cwd=Path(runtime.config.base_dir).resolve())

    missing = [name for name in ("tmux", "codex") if not bool(runtime._command_exists(name))]
    if missing:
        print(f"Missing required executables: {', '.join(missing)}", file=sys.stderr)
        return 1

    codex_executable = _resolve_command_path("codex")
    plan = _build_launch_plan(runtime, passthrough_args=passthrough_args, codex_executable=codex_executable)
    if dry_run:
        _print_launch_plan(plan, json_output=json_output)
        return 0

    if plan.create_session and plan.create_command is not None:
        create_result = _run_probe(runtime, plan.create_command, cwd=plan.repo_root)
        if create_result.returncode != 0:
            print(_completed_process_error_text(create_result), file=sys.stderr)
            return 1
    elif passthrough_args:
        print(
            f"Reusing existing tmux session '{plan.session_name}'; extra Codex arguments were ignored.",
            file=sys.stderr,
        )

    if plan.attach_via == "switch-client":
        attach_result = _run_probe(runtime, plan.attach_command, cwd=plan.repo_root)
        if attach_result.returncode != 0:
            print(_completed_process_error_text(attach_result), file=sys.stderr)
            return 1
        return 0
    return _attach_interactive(runtime, plan.attach_command, cwd=plan.repo_root)



def _omx_command_for_flags(flags: dict[str, object], *, passthrough_args: tuple[str, ...]) -> tuple[str, ...]:
    command = ["omx"]
    workflow = ""
    if bool(flags.get("ultragoal")):
        workflow = "ultragoal"
        command.append("ultragoal")
    elif bool(flags.get("ralph")):
        workflow = "ralph"
        command.append("ralph")
    elif bool(flags.get("team")):
        workflow = "team"
        command.append("team")
    command.append("--tmux")
    if passthrough_args:
        command.extend(passthrough_args)
    elif workflow in {"ultragoal", "ralph"}:
        command.append("Implement MAIN_TASK.md end-to-end.")
    return tuple(command)


def _print_omx_launch_plan(runtime: Any, *, command: tuple[str, ...], json_output: bool) -> None:
    payload = {
        "repo_root": str(Path(runtime.config.base_dir).resolve()),
        "omx_command": list(command),
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"repo_root: {payload['repo_root']}")
    print(f"omx_command: {shlex.join(command)}")

def _build_launch_plan(
    runtime: Any,
    *,
    passthrough_args: tuple[str, ...],
    codex_executable: str = "codex",
) -> CodexTmuxLaunchPlan:
    repo_root = Path(runtime.config.base_dir).resolve()
    session_name = _session_name_for_repo(repo_root, env=getattr(runtime, "env", {}) or {})
    window_name = _window_name(env=getattr(runtime, "env", {}) or {})
    codex_command = (codex_executable, *_CODEX_BYPASS_ARGS, *passthrough_args)
    create_session = not _tmux_session_exists(runtime, session_name)
    attach_via = "switch-client" if str(getattr(runtime, "env", {}).get("TMUX", "")).strip() else "attach-session"
    create_command = None
    if create_session:
        create_command = (
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            "-n",
            window_name,
            "-c",
            str(repo_root),
            shlex.join(codex_command),
        )
    attach_command = ("tmux", attach_via, "-t", session_name)
    return CodexTmuxLaunchPlan(
        repo_root=repo_root,
        session_name=session_name,
        window_name=window_name,
        codex_command=codex_command,
        create_session=create_session,
        attach_via=attach_via,
        create_command=create_command,
        attach_command=attach_command,
    )


def _resolve_command_path(command: str) -> str:
    resolved = shutil.which(command)
    if not resolved:
        return command
    return str(Path(resolved).expanduser().resolve(strict=False))


def _print_launch_plan(plan: CodexTmuxLaunchPlan, *, json_output: bool) -> None:
    payload = {
        "repo_root": str(plan.repo_root),
        "session_name": plan.session_name,
        "window_name": plan.window_name,
        "codex_command": list(plan.codex_command),
        "create_session": plan.create_session,
        "attach_via": plan.attach_via,
        "create_command": list(plan.create_command) if plan.create_command is not None else None,
        "attach_command": list(plan.attach_command),
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"repo_root: {payload['repo_root']}")
    print(f"session_name: {payload['session_name']}")
    print(f"window_name: {payload['window_name']}")
    print(f"create_session: {payload['create_session']}")
    print(f"attach_via: {payload['attach_via']}")
    print(f"codex_command: {shlex.join(plan.codex_command)}")
    if plan.create_command is not None:
        print(f"create_command: {shlex.join(plan.create_command)}")
    print(f"attach_command: {shlex.join(plan.attach_command)}")


def _session_name_for_repo(repo_root: Path, *, env: dict[str, str]) -> str:
    override = str(env.get("ENVCTL_CODEX_TMUX_SESSION", "")).strip()
    if override:
        return _sanitize_name(override, fallback="codex")
    slug = _sanitize_name(repo_root.name, fallback="repo")
    digest = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:8]
    return f"{_SESSION_PREFIX}-{slug[:24]}-{digest}"


def _window_name(*, env: dict[str, str]) -> str:
    override = str(env.get("ENVCTL_CODEX_TMUX_WINDOW", "")).strip()
    return _sanitize_name(override, fallback=_DEFAULT_WINDOW) if override else _DEFAULT_WINDOW


def _sanitize_name(value: str, *, fallback: str) -> str:
    normalized = _NAME_SANITIZE_RE.sub("-", str(value).strip()).strip("-_")
    return normalized or fallback


def _tmux_session_exists(runtime: Any, session_name: str) -> bool:
    try:
        result = _run_probe(
            runtime,
            ("tmux", "has-session", "-t", session_name),
            cwd=Path(runtime.config.base_dir).resolve(),
        )
    except OSError:
        return False
    return result.returncode == 0


def _run_probe(runtime: Any, command: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(dict(getattr(runtime, "env", {}) or {}))
    process_runner = optional_process_runtime(runtime)
    if process_runner is not None and hasattr(process_runner, "run_probe"):
        return process_runner.run_probe(command, cwd=cwd, env=env, timeout=10.0)
    if process_runner is not None and hasattr(process_runner, "run"):
        return process_runner.run(command, cwd=cwd, env=env, timeout=10.0)
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _attach_interactive(runtime: Any, command: tuple[str, ...], *, cwd: Path) -> int:
    process_runner = optional_process_runtime(runtime)
    try:
        if process_runner is not None and hasattr(process_runner, "start_interactive_child"):
            process = process_runner.start_interactive_child(command, cwd=cwd, env=getattr(runtime, "env", {}))
        else:
            process = subprocess.Popen(
                list(command),
                cwd=str(cwd),
                env=dict(getattr(runtime, "env", {})),
                text=True,
            )
        return int(process.wait())
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _completed_process_error_text(result: subprocess.CompletedProcess[str]) -> str:
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    command = " ".join(str(part) for part in (getattr(result, "args", None) or ()))
    return f"Command failed: {command}".strip()
