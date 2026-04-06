from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from collections.abc import Sequence

from envctl_engine.runtime import cli as runtime_cli
from envctl_engine.runtime.launcher_support import (
    LauncherError,
    install_or_uninstall,
    launcher_doctor_payload,
    launcher_doctor_text,
    launcher_usage_text,
    parse_install_options,
    resolve_envctl_version,
    resolve_repo_root,
)


def _extract_repo_arg(argv: Sequence[str]) -> tuple[list[str], str | None]:
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


def _forward_to_engine(root: Path, repo_root: Path, argv: Sequence[str]) -> int:
    env = dict(os.environ)
    env["ENVCTL_ROOT_DIR"] = str(root)
    env["RUN_LAUNCHER_NAME"] = "envctl"
    env["RUN_LAUNCHER_CONTEXT"] = "envctl"
    env["RUN_REPO_ROOT"] = str(repo_root)
    env["RUN_ENGINE_PATH"] = "python:envctl_engine.runtime.cli"
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
        repo_root = resolve_repo_root(repo_arg=repo_arg, cwd=Path.cwd())
        return _forward_to_engine(root, repo_root, argv)
    except LauncherError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
