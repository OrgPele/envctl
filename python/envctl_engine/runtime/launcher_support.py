from __future__ import annotations

from importlib import metadata as importlib_metadata
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import tomllib


class LauncherError(RuntimeError):
    pass


USAGE_TEXT = """Usage:
  envctl [--repo <path>] [engine args...]
  envctl doctor [--repo <path>]
  envctl install [--shell-file <path>] [--dry-run]
  envctl uninstall [--shell-file <path>] [--dry-run]
  envctl [--repo <path>] --version
  envctl --help

Examples:
  envctl
  envctl --main
  envctl --repo /path/to/your/repo --resume
  envctl --version
  envctl doctor --repo /path/to/your/repo
"""

_BLOCK_START = "# >>> envctl PATH >>>"
_BLOCK_END = "# <<< envctl PATH <<<"
ORIGINAL_WRAPPER_ARGV0_ENVVAR = "ENVCTL_WRAPPER_ORIGINAL_ARGV0"


@dataclass(frozen=True, slots=True)
class InstallOptions:
    shell_file: Path
    dry_run: bool = False


def launcher_usage_text() -> str:
    return USAGE_TEXT


def resolve_envctl_version(*, project_root: Path | None = None) -> str:
    try:
        return str(importlib_metadata.version("envctl"))
    except importlib_metadata.PackageNotFoundError:
        pass
    except Exception as exc:
        raise LauncherError(f"Could not determine envctl version from installed package metadata: {exc}") from exc

    for pyproject_path in _candidate_version_files(project_root):
        if not pyproject_path.is_file():
            continue
        try:
            payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise LauncherError(f"Could not determine envctl version from {pyproject_path}: {exc}") from exc
        project = payload.get("project")
        if not isinstance(project, dict):
            raise LauncherError(f"Could not determine envctl version from {pyproject_path}: missing [project] table")
        version = project.get("version")
        if not isinstance(version, str) or not version.strip():
            raise LauncherError(f"Could not determine envctl version from {pyproject_path}: missing project.version")
        return version.strip()

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
    env_map = os.environ if env is None else env
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
    env_map = os.environ if env is None else env
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
    env_map = os.environ if env is None else env
    if env_map.get("ENVCTL_USE_REPO_WRAPPER") == "1":
        return None
    if is_explicit_wrapper_path(current_binary, argv0, env=env_map, cwd=cwd):
        return None
    if alternate is not None:
        return alternate
    return find_shadowed_installed_envctl(current_binary, env=env_map)


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
