from __future__ import annotations

import os
from pathlib import Path
import sys
from collections.abc import Sequence

from envctl_engine.runtime import cli as runtime_cli
from envctl_engine.runtime.launcher_support import (
    LauncherError,
    install_or_uninstall,
    launcher_doctor_text,
    launcher_usage_text,
    parse_install_options,
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
            repo_root = resolve_repo_root(repo_arg=repo_arg, cwd=Path.cwd())
            print(
                launcher_doctor_text(
                    binary_path=_binary_path(),
                    repo_root=repo_root,
                    runtime_entrypoint="envctl_engine.runtime.cli",
                    launcher_root=root,
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
