from __future__ import annotations

import re
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Final

from envctl_engine.runtime.prompt_install_models import PromptTemplate

_PROMPT_TEMPLATE_PACKAGE: Final = "envctl_engine.runtime.prompt_templates"
_PROMPT_TEMPLATE_SUFFIX: Final = ".md"
_PROMPT_TEMPLATE_EXCLUSION_PREFIX: Final = "_"
_PROMPT_ARGUMENT_PLACEHOLDER: Final = "$ARGUMENTS"
_CODEX_SKILL_ARGUMENT_SENTINEL: Final = "additional user instructions supplied with the invoking prompt"
_PROMPT_ARGUMENT_LINE_RE = re.compile(r"(?m)^(?P<indent>[ \t]*)\$ARGUMENTS[ \t]*$")


def _available_presets() -> frozenset[str]:
    return frozenset(path.name.rsplit(_PROMPT_TEMPLATE_SUFFIX, 1)[0] for path in _template_files())


def _unsupported_preset_message(preset: str) -> str:
    available = ", ".join(sorted(_available_presets()))
    if not available:
        return f"Unsupported preset: {preset}"
    return f"Unsupported preset: {preset}. Available presets: {available}"


def _template_files() -> tuple[Traversable, ...]:
    template_root = resources.files(_PROMPT_TEMPLATE_PACKAGE)
    files: list[Traversable] = []
    for entry in template_root.iterdir():
        if not entry.is_file() or not entry.name.endswith(_PROMPT_TEMPLATE_SUFFIX):
            continue
        if entry.name.startswith(_PROMPT_TEMPLATE_EXCLUSION_PREFIX):
            continue
        files.append(entry)
    return tuple(sorted(files, key=lambda item: item.name))


def _load_template(preset: str) -> PromptTemplate:
    template_name = f"{preset}{_PROMPT_TEMPLATE_SUFFIX}"
    template_root = resources.files(_PROMPT_TEMPLATE_PACKAGE)
    template_file = template_root.joinpath(template_name)
    if not template_file.is_file():
        raise LookupError(_unsupported_preset_message(preset))
    raw = template_file.read_text(encoding="utf-8")
    return _parse_template(name=preset, raw=raw)


def _parse_template(*, name: str, raw: str) -> PromptTemplate:
    if not raw.strip():
        raise ValueError(f"Template '{name}' is missing prompt body")
    return PromptTemplate(
        name=name,
        body=raw.lstrip("\n"),
    )


def _render_preset(*, cli_name: str, template: PromptTemplate) -> str:
    if cli_name == "codex":
        return _render_codex_template(template)
    if cli_name == "claude":
        return _render_claude_template(template)
    if cli_name == "opencode":
        return _render_opencode_template(template)
    raise RuntimeError(f"Unsupported CLI target: {cli_name}")


def _render_codex_template(template: PromptTemplate) -> str:
    return template.body


def _render_claude_template(template: PromptTemplate) -> str:
    return _render_non_codex_template(template)


def _render_opencode_template(template: PromptTemplate) -> str:
    return _render_non_codex_template(template)


def _render_non_codex_template(template: PromptTemplate) -> str:
    return re.sub(r"\$browser(?!-use)", "$browser-use", template.body)


def _render_direct_prompt_arguments(body: str, *, arguments: str) -> str:
    raw_body = str(body)
    replacement = str(arguments or "")
    if replacement and _CODEX_SKILL_ARGUMENT_SENTINEL in raw_body:
        return raw_body.replace(_CODEX_SKILL_ARGUMENT_SENTINEL, replacement, 1)

    def replace_standalone(match: re.Match[str]) -> str:
        return f"{match.group('indent')}{replacement}"

    rendered, count = _PROMPT_ARGUMENT_LINE_RE.subn(replace_standalone, raw_body, count=1)
    if count:
        return rendered
    if replacement:
        return f"{raw_body.rstrip()}\n\n{replacement}\n"
    return raw_body
