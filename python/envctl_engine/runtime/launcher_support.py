from __future__ import annotations

from importlib import metadata as importlib_metadata
import os
import sys
from textwrap import indent
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from envctl_engine.runtime.help_text import render_help_text as render_runtime_help_text
from envctl_engine.shared.python_project_metadata import (
    pyproject_project_string_field_from_payload,
    pyproject_project_table_from_payload,
    read_pyproject,
)
from envctl_engine.shared.repo_roots import (
    canonical_envctl_project_root,
    find_repo_root,
    is_repo_root as shared_is_repo_root,
    main_repo_root_for_linked_worktree as shared_main_repo_root_for_linked_worktree,
    repo_root_with_readable_main_config_from_worktree as shared_repo_root_with_readable_main_config_from_worktree,
)


class LauncherError(RuntimeError):
    pass


USAGE_TEXT = """envctl launcher help

This help is printed by the lightweight repo wrapper/package launcher before it
hands off to the full Python runtime. Use this wrapper section when PATH/repo
selection is the question; the complete runtime command map is included below.
Use `envctl <command> --help` for focused command-specific usage.

Usage:
  envctl [--repo <path>] [engine args...]
  envctl doctor [--repo <path>] [--json]
  envctl install [--shell-file <path>] [--dry-run]
  envctl uninstall [--shell-file <path>] [--dry-run]
  envctl [--repo <path>] --version
  envctl --help

Repo wrapper / package launcher responsibilities:
  - resolve which repository envctl should operate on (`--repo <path>` or cwd)
  - print the package/repo version without bootstrapping a project
  - install or remove the shell PATH shim for the envctl executable
  - run launcher-level doctor checks for binary/repo resolution
  - forward normal engine args to the Python runtime after repo resolution

Runtime CLI capabilities:
  - start/resume/restart services and show the dashboard
  - run specific headless actions such as test, logs, health, errors, pr, commit, review, and migrate
  - manage envctl implementation worktrees through plan/ensure/delete/blast commands
  - install AI workflow presets and launch Codex tmux/OMX implementation sessions
  - collect diagnostics with doctor, preflight, debug-pack, debug-report, and debug-last

Examples:
  envctl
  envctl --main --headless
  envctl --repo /path/to/your/repo --resume
  envctl --repo /path/to/your/repo pr --project feature-a-1
  envctl <command> --help
  envctl --version
  envctl doctor --repo /path/to/your/repo --json
"""

_BLOCK_START = "# >>> envctl PATH >>>"
_BLOCK_END = "# <<< envctl PATH <<<"
ORIGINAL_WRAPPER_ARGV0_ENVVAR = "ENVCTL_WRAPPER_ORIGINAL_ARGV0"


@dataclass(frozen=True, slots=True)
class InstallOptions:
    shell_file: Path
    dry_run: bool = False


def launcher_usage_text() -> str:
    return "\n".join(
        (
            USAGE_TEXT.rstrip(),
            "",
            "Runtime command map (after the launcher resolves the repo, these are the forwarded engine commands):",
            indent(render_runtime_help_text(None), "  "),
            "",
        )
    )


def resolve_envctl_version(*, project_root: Path | None = None) -> str:
    if project_root is None:
        try:
            return str(importlib_metadata.version("envctl"))
        except importlib_metadata.PackageNotFoundError:
            pass
        except Exception as exc:
            raise LauncherError(f"Could not determine envctl version from installed package metadata: {exc}") from exc

    preferred_paths = _candidate_version_files(project_root)
    for pyproject_path in preferred_paths:
        if not pyproject_path.is_file():
            continue
        try:
            payload = read_pyproject(pyproject_path)
        except (OSError, ValueError) as exc:
            raise LauncherError(f"Could not determine envctl version from {pyproject_path}: {exc}") from exc
        if pyproject_project_table_from_payload(payload) is None:
            raise LauncherError(f"Could not determine envctl version from {pyproject_path}: missing [project] table")
        version = pyproject_project_string_field_from_payload(payload, "version")
        if version is None:
            raise LauncherError(f"Could not determine envctl version from {pyproject_path}: missing project.version")
        return version

    try:
        return str(importlib_metadata.version("envctl"))
    except importlib_metadata.PackageNotFoundError:
        pass
    except Exception as exc:
        raise LauncherError(f"Could not determine envctl version from installed package metadata: {exc}") from exc

    raise LauncherError("Could not determine envctl version from installed package metadata or pyproject.toml.")


def _candidate_version_files(project_root: Path | None) -> list[Path]:
    candidates: list[Path] = []
    roots: list[Path] = []
    if project_root is not None:
        roots.append(project_root.expanduser())
    try:
        source_root = Path(__file__).resolve().parents[3]
    except (IndexError, OSError):
        source_root = None
    if source_root is not None and source_root not in roots:
        roots.append(source_root)
    for root in roots:
        candidate = root / "pyproject.toml"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def find_shadowed_installed_envctl(current_binary: Path, env: Mapping[str, str] | None = None) -> Path | None:
    env_map: Mapping[str, str] = {} if env is None else env
    current_resolved = _resolved_path(current_binary)
    seen: set[Path] = {current_resolved}
    for candidate in _path_envctl_candidates(env_map):
        resolved = _resolved_path(candidate)
        if resolved in seen:
            continue
        return resolved
    return None


def _path_envctl_candidates(env: Mapping[str, str]) -> list[Path]:
    path_value = env.get("PATH", "")
    if not path_value:
        return []
    candidates: list[Path] = []
    for entry in path_value.split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry).expanduser() / "envctl"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            candidates.append(candidate)
    return candidates


def _resolved_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _effective_invocation_argv0(current_binary: Path, argv0: str, env: Mapping[str, str] | None = None) -> str:
    if env is None:
        return argv0
    env_map = env
    preserved = env_map.get(ORIGINAL_WRAPPER_ARGV0_ENVVAR)
    if not preserved:
        return argv0
    separators = [os.path.sep]
    if os.path.altsep:
        separators.append(os.path.altsep)
    if not any(separator in argv0 for separator in separators):
        return argv0
    candidate = Path(argv0).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if _resolved_path(candidate) != _resolved_path(current_binary):
        return argv0
    return preserved


def is_explicit_wrapper_path(
    current_binary: Path,
    argv0: str,
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> bool:
    env_map: Mapping[str, str] = {} if env is None else env
    invocation = _effective_invocation_argv0(current_binary, argv0, env=env)
    if not invocation:
        return False
    separators = [os.path.sep]
    if os.path.altsep:
        separators.append(os.path.altsep)
    if not any(separator in invocation for separator in separators):
        return False
    candidate = Path(invocation).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() if cwd is None else cwd) / candidate
    current_resolved = _resolved_path(current_binary)
    candidate_resolved = _resolved_path(candidate)
    if candidate_resolved != current_resolved:
        return False
    # Shebang-launched scripts on macOS can receive the PATH-resolved shim path as argv[0]
    # even when the user typed a bare `envctl`. Treat a PATH entry that differs from the
    # real wrapper path as bare-name intent so the installed-command safety behavior stays on.
    if candidate.is_absolute() and candidate != current_resolved:
        if any(path_candidate == candidate for path_candidate in _path_envctl_candidates(env_map)):
            return False
    return True


def select_envctl_reexec_target(
    current_binary: Path,
    argv0: str,
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    alternate: Path | None = None,
) -> Path | None:
    env_map: Mapping[str, str] = {} if env is None else env
    if env_map.get("ENVCTL_USE_REPO_WRAPPER") == "1":
        return None
    separators = [os.path.sep]
    if os.path.altsep:
        separators.append(os.path.altsep)
    invocation = _effective_invocation_argv0(current_binary, argv0, env=env_map)
    if invocation and not any(separator in invocation for separator in separators):
        if alternate is not None:
            return alternate
        return find_shadowed_installed_envctl(current_binary, env=env_map)
    if is_explicit_wrapper_path(current_binary, argv0, env=env_map, cwd=cwd):
        return None
    if alternate is not None:
        return alternate
    return find_shadowed_installed_envctl(current_binary, env=env_map)


def is_repo_root(path: Path) -> bool:
    return shared_is_repo_root(path)


def find_repo_root_from_cwd(cwd: Path) -> Path | None:
    return find_repo_root(cwd)


def main_repo_root_for_linked_worktree(worktree_root: Path) -> Path | None:
    return shared_main_repo_root_for_linked_worktree(worktree_root)


def repo_root_with_readable_main_config_from_worktree(worktree_root: Path) -> Path | None:
    return shared_repo_root_with_readable_main_config_from_worktree(worktree_root)


def resolve_repo_root(*, repo_arg: str | None, cwd: Path) -> Path:
    if repo_arg:
        candidate = Path(repo_arg).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        candidate = candidate.resolve()
        detected = find_repo_root(candidate)
        if detected is None:
            raise LauncherError(f"Invalid --repo path: {repo_arg}")
        return canonical_envctl_project_root(detected)
    detected = find_repo_root_from_cwd(cwd)
    if detected is None:
        raise LauncherError("Could not resolve repository root. Use --repo <path>.")
    return canonical_envctl_project_root(detected)


def launcher_doctor_payload(
    *,
    binary_path: str,
    repo_root: Path,
    runtime_entrypoint: str,
    launcher_root: Path,
) -> dict[str, str]:
    return {
        "launcher": "envctl",
        "binary_path": str(binary_path),
        "launcher_root": str(launcher_root),
        "repo_root": str(repo_root),
        "runtime_entrypoint": str(runtime_entrypoint),
        "python_executable": str(sys.executable),
        "envctl_engine_path": _envctl_engine_path(),
    }


def launcher_doctor_text(*, binary_path: str, repo_root: Path, runtime_entrypoint: str, launcher_root: Path) -> str:
    payload = launcher_doctor_payload(
        binary_path=binary_path,
        repo_root=repo_root,
        runtime_entrypoint=runtime_entrypoint,
        launcher_root=launcher_root,
    )
    return "\n".join(
        (
            f"Launcher: {payload['launcher']}",
            f"Binary Path: {payload['binary_path']}",
            f"Launcher Root: {payload['launcher_root']}",
            f"Repo Root: {payload['repo_root']}",
            f"Runtime Entry: {payload['runtime_entrypoint']}",
            f"Python Executable: {payload['python_executable']}",
            f"Envctl Engine Path: {payload['envctl_engine_path']}",
        )
    )


def _envctl_engine_path() -> str:
    try:
        import envctl_engine
    except Exception:
        return ""
    module_file = str(getattr(envctl_engine, "__file__", "") or "").strip()
    if not module_file:
        return ""
    try:
        return str(Path(module_file).resolve())
    except OSError:
        return module_file


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
        _ = shell_file.write_text("\n".join(payload) + "\n", encoding="utf-8")
        return ""
    if _BLOCK_START not in existing:
        return shell_file.read_text(encoding="utf-8") if options.dry_run and shell_file.exists() else ""
    filtered = _remove_block(existing)
    if options.dry_run:
        rendered = "\n".join(filtered)
        return rendered + ("\n" if rendered else "")
    _ = shell_file.write_text(("\n".join(filtered) + "\n") if filtered else "", encoding="utf-8")
    return ""
