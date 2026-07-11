from __future__ import annotations

from typing import Mapping

from envctl_engine.runtime.prompt_install_codex_skills import (
    _codex_skill_markdown_path,
    _codex_skill_metadata,
    _extract_codex_skill_prompt_body,
)
from envctl_engine.runtime.prompt_install_paths import (
    _legacy_codex_prompt_path,
    _target_path,
    _user_home_from_env,
)
from envctl_engine.runtime.prompt_install_templates import (
    _load_template,
    _parse_template,
    _render_direct_prompt_arguments,
    _render_opencode_template,
)


def codex_preset_uses_direct_submission(preset: str) -> bool:
    return bool(str(preset).strip())


def codex_skill_invocation_for_preset(*, preset: str, arguments: str = "") -> str:
    normalized_preset = str(preset).strip()
    if not normalized_preset:
        raise LookupError("Preset is required for Codex skill invocation")
    metadata = _codex_skill_metadata(normalized_preset)
    invocation = f"${metadata.skill_name}"
    normalized_arguments = str(arguments).strip()
    if not normalized_arguments:
        return invocation
    return f"{invocation} {normalized_arguments}"


def resolve_codex_direct_prompt_body(
    *,
    preset: str,
    env: Mapping[str, str] | None = None,
    arguments: str = "",
) -> str:
    normalized_preset = str(preset).strip()
    if not codex_preset_uses_direct_submission(normalized_preset):
        raise LookupError(f"Preset is not configured for direct Codex submission: {normalized_preset}")
    home = _user_home_from_env(env)
    skill_path = _codex_skill_markdown_path(preset=normalized_preset, home=home)
    target_path = _target_path(cli_name="codex", preset=normalized_preset, home=home, env=env)
    legacy_path = _legacy_codex_prompt_path(preset=normalized_preset, home=home)
    if skill_path.is_file():
        body = _extract_codex_skill_prompt_body(skill_path.read_text(encoding="utf-8"), preset=normalized_preset)
        return _render_direct_prompt_arguments(body, arguments=arguments)
    if target_path.is_file():
        raw = target_path.read_text(encoding="utf-8")
        template = _parse_template(name=normalized_preset, raw=raw)
    elif legacy_path.is_file():
        raw = legacy_path.read_text(encoding="utf-8")
        template = _parse_template(name=normalized_preset, raw=raw)
    else:
        template = _load_template(normalized_preset)
    return _render_direct_prompt_arguments(template.body, arguments=arguments)


def resolve_opencode_direct_prompt_body(
    *,
    preset: str,
    env: Mapping[str, str] | None = None,
    arguments: str = "",
) -> str:
    normalized_preset = str(preset).strip()
    if not normalized_preset:
        raise LookupError("Preset is required for direct OpenCode submission")
    home = _user_home_from_env(env)
    target_path = _target_path(cli_name="opencode", preset=normalized_preset, home=home, env=env)
    if target_path.is_file():
        raw = target_path.read_text(encoding="utf-8")
        template = _parse_template(name=normalized_preset, raw=raw)
    else:
        template = _load_template(normalized_preset)
    return _render_direct_prompt_arguments(_render_opencode_template(template), arguments=arguments)
