from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from envctl_engine.config.local_artifacts import envctl_local_artifact_patterns

_BLOCK_START = "# >>> envctl managed global ignores >>>"
_BLOCK_END = "# <<< envctl managed global ignores <<<"


@dataclass(slots=True)
class GlobalIgnoreStatus:
    code: str
    updated: bool
    scope: str
    target_path: Path | None
    managed_patterns: tuple[str, ...]
    warning: str | None = None


def ensure_envctl_global_ignores(base_dir: Path) -> GlobalIgnoreStatus:
    patterns = envctl_local_artifact_patterns()
    excludes_path, lookup_warning = _configured_global_excludes_path(base_dir)
    if lookup_warning is not None:
        return GlobalIgnoreStatus(
            code="global_excludes_lookup_failed",
            updated=False,
            scope="git_global_excludes",
            target_path=None,
            managed_patterns=patterns,
            warning=lookup_warning,
        )
    if excludes_path is None:
        warning = (
            "Git global excludes are not configured. Configure core.excludesFile, then rerun envctl config "
            "to keep envctl local artifacts out of git status."
        )
        return GlobalIgnoreStatus(
            code="missing_global_excludes_configuration",
            updated=False,
            scope="git_global_excludes",
            target_path=None,
            managed_patterns=patterns,
            warning=warning,
        )
    try:
        updated = _update_envctl_managed_block(excludes_path, patterns)
    except OSError as exc:
        warning = f"Could not update global git excludes at {excludes_path}: {exc}"
        return GlobalIgnoreStatus(
            code="global_excludes_write_failed",
            updated=False,
            scope="git_global_excludes",
            target_path=excludes_path,
            managed_patterns=patterns,
            warning=warning,
        )
    return GlobalIgnoreStatus(
        code="updated_existing_global_excludes" if updated else "already_present",
        updated=updated,
        scope="git_global_excludes",
        target_path=excludes_path,
        managed_patterns=patterns,
        warning=None,
    )


def _configured_global_excludes_path(base_dir: Path) -> tuple[Path | None, str | None]:
    result = subprocess.run(
        ["git", "config", "--global", "--path", "--get", "core.excludesFile"],
        cwd=str(base_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = str(result.stderr or "").strip()
        if stderr:
            return None, f"Could not resolve Git global excludes target: {stderr}"
        return None, None
    value = result.stdout.strip()
    if not value:
        return None, None
    return Path(value).expanduser(), None


def _update_envctl_managed_block(path: Path, patterns: tuple[str, ...]) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    rendered_block = _render_managed_block(patterns)
    updated = _merge_managed_block(existing, rendered_block)
    if updated == existing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return True


def _render_managed_block(patterns: tuple[str, ...]) -> str:
    lines = [_BLOCK_START, *patterns, _BLOCK_END]
    return "\n".join(lines) + "\n"


def _merge_managed_block(existing: str, block_text: str) -> str:
    start = existing.find(_BLOCK_START)
    end = existing.find(_BLOCK_END, start) if start != -1 else -1
    if start != -1 and end != -1:
        suffix_start = end + len(_BLOCK_END)
        suffix = existing[suffix_start:]
        if suffix.startswith("\n"):
            suffix = suffix[1:]
        prefix = existing[:start].rstrip("\n")
        parts = [part for part in (prefix, block_text.rstrip("\n"), suffix.lstrip("\n")) if part]
        return "\n\n".join(parts).rstrip("\n") + "\n"
    stripped = existing.rstrip("\n")
    if not stripped:
        return block_text
    return stripped + "\n\n" + block_text
