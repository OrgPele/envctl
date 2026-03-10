from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class LauncherError(RuntimeError):
    pass


USAGE_TEXT = """Usage:
  envctl [--repo <path>] [engine args...]
  envctl doctor [--repo <path>]
  envctl install [--shell-file <path>] [--dry-run]
  envctl uninstall [--shell-file <path>] [--dry-run]
  envctl --help

Examples:
  envctl
  envctl --main
  envctl --repo /Users/kfiramar/projects/my-project --resume
  envctl doctor --repo /Users/kfiramar/projects/my-project
"""

_BLOCK_START = "# >>> envctl PATH >>>"
_BLOCK_END = "# <<< envctl PATH <<<"


@dataclass(frozen=True, slots=True)
class InstallOptions:
    shell_file: Path
    dry_run: bool = False


def launcher_usage_text() -> str:
    return USAGE_TEXT


def is_repo_root(path: Path) -> bool:
    return (path / ".git").is_dir() or (path / ".git").is_file()


def find_repo_root_from_cwd(cwd: Path) -> Path | None:
    current = cwd.resolve()
    while True:
        if is_repo_root(current):
            return current
        if current.parent == current:
            return None
        current = current.parent


def resolve_repo_root(*, repo_arg: str | None, cwd: Path) -> Path:
    if repo_arg:
        candidate = Path(repo_arg).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        candidate = candidate.resolve()
        if not is_repo_root(candidate):
            raise LauncherError(f"Invalid --repo path: {repo_arg}")
        return candidate
    detected = find_repo_root_from_cwd(cwd)
    if detected is None:
        raise LauncherError("Could not resolve repository root. Use --repo <path>.")
    return detected


def launcher_doctor_text(*, binary_path: str, repo_root: Path, runtime_entrypoint: str, launcher_root: Path) -> str:
    return "\n".join(
        (
            "Launcher: envctl",
            f"Binary Path: {binary_path}",
            f"Launcher Root: {launcher_root}",
            f"Repo Root: {repo_root}",
            f"Runtime Entry: {runtime_entrypoint}",
        )
    )


def default_shell_file(env: dict[str, str] | None = None) -> Path:
    env_map = dict(os.environ if env is None else env)
    shell_name = Path(env_map.get("SHELL", "")).name
    home = Path(env_map.get("HOME", str(Path.home())))
    if shell_name == "zsh":
        return home / ".zshrc"
    if shell_name == "bash":
        bash_profile = home / ".bash_profile"
        bashrc = home / ".bashrc"
        if bash_profile.exists() and not bashrc.exists():
            return bash_profile
        return bashrc
    return home / ".profile"


def format_path_line(*, bin_dir: Path, home: Path | None = None) -> str:
    resolved = bin_dir.resolve()
    home_dir = (Path.home() if home is None else home).resolve()
    rendered = str(resolved)
    home_prefix = str(home_dir) + "/"
    if rendered.startswith(home_prefix):
        rendered = "$HOME/" + rendered[len(home_prefix) :]
    return f'export PATH="{rendered}:$PATH"'


def parse_install_options(argv: list[str], *, env: dict[str, str] | None = None) -> InstallOptions:
    shell_file = default_shell_file(env)
    dry_run = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--shell-file":
            if index + 1 >= len(argv):
                raise LauncherError("Missing value for --shell-file")
            value = str(argv[index + 1]).strip()
            if not value:
                raise LauncherError("Missing value for --shell-file")
            shell_file = Path(value).expanduser()
            index += 2
            continue
        if token.startswith("--shell-file="):
            value = token.split("=", 1)[1].strip()
            if not value:
                raise LauncherError("Missing value for --shell-file")
            shell_file = Path(value).expanduser()
            index += 1
            continue
        if token == "--dry-run":
            dry_run = True
            index += 1
            continue
        raise LauncherError(f"Unknown option: {token}")
    return InstallOptions(shell_file=shell_file, dry_run=dry_run)


def _remove_block(lines: list[str]) -> list[str]:
    filtered: list[str] = []
    skipping = False
    for line in lines:
        if line == _BLOCK_START:
            skipping = True
            continue
        if line == _BLOCK_END:
            skipping = False
            continue
        if not skipping:
            filtered.append(line)
    return filtered


def install_or_uninstall(
    *,
    mode: str,
    options: InstallOptions,
    bin_dir: Path,
    home: Path | None = None,
) -> str:
    if mode not in {"install", "uninstall"}:
        raise LauncherError(f"Unsupported mode: {mode}")
    shell_file = options.shell_file.expanduser()
    existing = shell_file.read_text(encoding="utf-8").splitlines() if shell_file.exists() else []
    if mode == "install":
        if _BLOCK_START in existing:
            return ""
        block = [_BLOCK_START, format_path_line(bin_dir=bin_dir, home=home), _BLOCK_END]
        if options.dry_run:
            return "\n".join(block) + "\n"
        shell_file.parent.mkdir(parents=True, exist_ok=True)
        payload = list(existing)
        if payload:
            payload.append("")
        payload.extend(block)
        shell_file.write_text("\n".join(payload) + "\n", encoding="utf-8")
        return ""
    if _BLOCK_START not in existing:
        return shell_file.read_text(encoding="utf-8") if options.dry_run and shell_file.exists() else ""
    filtered = _remove_block(existing)
    if options.dry_run:
        rendered = "\n".join(filtered)
        return rendered + ("\n" if rendered else "")
    shell_file.write_text(("\n".join(filtered) + "\n") if filtered else "", encoding="utf-8")
    return ""
