from __future__ import annotations

from pathlib import Path
from typing import Mapping


def _target_path(
    *,
    cli_name: str,
    preset: str,
    home: Path,
    env: Mapping[str, str] | None = None,
) -> Path:
    if cli_name == "codex":
        return _codex_envctl_prompt_root(home=home, env=env) / f"{preset}.md"
    if cli_name == "claude":
        return home / ".claude" / "commands" / f"{preset}.md"
    if cli_name == "opencode":
        return home / ".config" / "opencode" / "commands" / f"{preset}.md"
    raise RuntimeError(f"Unsupported CLI target: {cli_name}")


def _codex_envctl_prompt_root(*, home: Path, env: Mapping[str, str] | None = None) -> Path:
    raw_xdg = str((env or {}).get("XDG_CONFIG_HOME", "")).strip()
    config_home = Path(raw_xdg).expanduser() if raw_xdg else home / ".config"
    return config_home / "envctl" / "codex" / "prompts"


def _legacy_codex_prompt_path(*, preset: str, home: Path) -> Path:
    return home / ".codex" / "prompts" / f"{preset}.md"


def _codex_skill_root(*, home: Path) -> Path:
    return home / ".codex" / "skills"


def _user_home(runtime: object) -> Path:
    env = getattr(runtime, "env", {})
    return _user_home_from_env(env if isinstance(env, dict) else {})


def _user_home_from_env(env: Mapping[str, str] | None) -> Path:
    raw_home = str((env or {}).get("HOME", "")).strip()
    if raw_home:
        return Path(raw_home).expanduser()
    return Path.home()
