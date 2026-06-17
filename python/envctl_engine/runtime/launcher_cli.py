from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from collections.abc import Sequence

from envctl_engine.runtime import cli as runtime_cli
from envctl_engine.runtime.launcher_support import (
    LauncherError,
    find_repo_root_from_cwd,
    install_or_uninstall,
    launcher_doctor_payload,
    launcher_doctor_text,
    launcher_usage_text,
    parse_install_options,
    resolve_envctl_version,
    resolve_repo_root,
)

_PR_PREVIEW_CONTROLLER_TOKENS = {
    "pr-preview-controller",
    "pr-preview",
    "github-pr-preview",
    "--pr-preview-controller",
    "--pr-preview",
    "--github-pr-preview",
}
_BOOTSTRAP_SAFE_WITHOUT_REPO = {
    "help",
    "--help",
    "-h",
    "list-commands",
    "--list-commands",
    "show-config",
    "--show-config",
    "install-prompts",
    "--install-prompts",
    "codex-tmux",
    "--codex-tmux",
    "ensure-worktree",
    "--ensure-worktree",
    "supabase-user",
    "--supabase-user",
    "qa-user",
    "--qa-user",
    "playwright",
    "--playwright",
    *list(_PR_PREVIEW_CONTROLLER_TOKENS),
}


def _extract_repo_arg(argv: Sequence[str]) -> tuple[list[str], str | None]:
    if _argv_invokes_pr_preview_controller(argv):
        return list(argv), None
    filtered: list[str] = []
    repo_arg: str | None = None
    index = 0
    while index < len(argv):
        token = str(argv[index])
        if token == "--repo":
            if index + 1 >= len(argv):
                raise LauncherError("Missing value for --repo")
            value = str(argv[index + 1]).strip()
            if not value:
                raise LauncherError("Missing value for --repo")
            repo_arg = value
            index += 2
            continue
        if token.startswith("--repo="):
            value = token.split("=", 1)[1].strip()
            if not value:
                raise LauncherError("Missing value for --repo")
            repo_arg = value
            index += 1
            continue
        filtered.append(token)
        index += 1
    return filtered, repo_arg


def _argv_invokes_pr_preview_controller(argv: Sequence[str]) -> bool:
    index = 0
    while index < len(argv):
        token = str(argv[index])
        if token in _PR_PREVIEW_CONTROLLER_TOKENS:
            return True
        if token in {"--command", "--action"}:
            return index + 1 < len(argv) and str(argv[index + 1]) in _PR_PREVIEW_CONTROLLER_TOKENS
        if token.startswith("--command=") or token.startswith("--action="):
            return token.split("=", 1)[1] in _PR_PREVIEW_CONTROLLER_TOKENS
        index += 1
    return False


def _argv_can_skip_repo_resolution(argv: Sequence[str]) -> bool:
    if _argv_invokes_pr_preview_controller(argv):
        return True
    command = str(argv[0]) if argv else "start"
    return command in _BOOTSTRAP_SAFE_WITHOUT_REPO


def _extract_json_flag(argv: Sequence[str]) -> tuple[list[str], bool]:
    filtered: list[str] = []
    json_output = False
    for token in argv:
        if str(token) == "--json":
            json_output = True
            continue
        filtered.append(str(token))
    return filtered, json_output


def _envctl_root() -> Path:
    env_root = os.environ.get("ENVCTL_ROOT_DIR")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _binary_path() -> str:
    argv0 = sys.argv[0]
    try:
        return str(Path(argv0).resolve())
    except OSError:
        return argv0


def _resolve_execution_root(*, repo_arg: str | None, cwd: Path) -> Path:
    if repo_arg:
        candidate = Path(repo_arg).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        detected = find_repo_root_from_cwd(candidate.resolve())
        if detected is None:
            raise LauncherError(f"Invalid --repo path: {repo_arg}")
        return detected.resolve()
    detected = find_repo_root_from_cwd(cwd)
    if detected is None:
        raise LauncherError("Could not resolve repository root. Use --repo <path>.")
    return detected.resolve()


def _forward_to_engine(root: Path, repo_root: Path, execution_root: Path, argv: Sequence[str]) -> int:
    env = dict(os.environ)
    env["ENVCTL_ROOT_DIR"] = str(root)
    env["RUN_LAUNCHER_NAME"] = "envctl"
    env["RUN_LAUNCHER_CONTEXT"] = "envctl"
    env["RUN_REPO_ROOT"] = str(repo_root)
    env["ENVCTL_EXECUTION_ROOT"] = str(execution_root)
    env["RUN_ENGINE_PATH"] = "python:envctl_engine.runtime.cli"
    env["ENVCTL_INVOCATION_CWD"] = str(Path.cwd().resolve())
    return int(runtime_cli.run(list(argv), env=env))


def run(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = _envctl_root()
    try:
        argv, repo_arg = _extract_repo_arg(argv)
        if argv and argv[0] == "--version":
            if len(argv) != 1:
                raise LauncherError("--version does not accept additional arguments")
            print(f"envctl {resolve_envctl_version(project_root=root)}")
            return 0
        if argv and argv[0] in {"--help", "-h"}:
            print(launcher_usage_text(), end="")
            return 0
        command = argv[0] if argv else ""
        if command in {"install", "uninstall"}:
            options = parse_install_options(list(argv[1:]))
            rendered = install_or_uninstall(mode=command, options=options, bin_dir=root / "bin")
            if rendered:
                print(rendered, end="")
            return 0
        if command == "doctor":
            argv, json_output = _extract_json_flag(argv)
            if len(argv) != 1:
                raise LauncherError("doctor only accepts --repo and --json at the launcher level")
            repo_root = resolve_repo_root(repo_arg=repo_arg, cwd=Path.cwd())
            payload = launcher_doctor_payload(
                binary_path=_binary_path(),
                repo_root=repo_root,
                runtime_entrypoint="envctl_engine.runtime.cli",
                launcher_root=root,
            )
            if json_output:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(
                    launcher_doctor_text(
                        binary_path=payload["binary_path"],
                        repo_root=Path(payload["repo_root"]),
                        runtime_entrypoint=payload["runtime_entrypoint"],
                        launcher_root=Path(payload["launcher_root"]),
                    )
                )
            return 0
        cwd = Path.cwd()
        if repo_arg is None and _argv_can_skip_repo_resolution(argv):
            repo_root = cwd.resolve()
            execution_root = cwd.resolve()
        else:
            repo_root = resolve_repo_root(repo_arg=repo_arg, cwd=cwd)
            execution_root = _resolve_execution_root(repo_arg=repo_arg, cwd=cwd)
        return _forward_to_engine(root, repo_root, execution_root, argv)
    except LauncherError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
