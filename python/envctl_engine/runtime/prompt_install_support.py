from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Final


_SUPPORTED_CLIS: Final[tuple[str, ...]] = ("codex", "claude", "opencode")
_DEFAULT_PRESET = "implement_task"
_PROMPT_TEMPLATE_PACKAGE = "envctl_engine.runtime.prompt_templates"
_PROMPT_TEMPLATE_SUFFIX = ".md"


@dataclass(slots=True)
class PromptInstallResult:
    cli: str
    path: str
    status: str
    backup_path: str | None
    message: str


@dataclass(slots=True)
class PromptTemplate:
    name: str
    body: str


def dispatch_utility_command(runtime: Any, route: object) -> int:
    command = str(getattr(route, "command", "")).strip()
    if command == "install-prompts":
        return run_install_prompts_command(runtime, route)
    raise RuntimeError(f"Unsupported utility command: {command}")


def run_install_prompts_command(runtime: Any, route: object) -> int:
    flags = getattr(route, "flags", {})
    passthrough_args = list(getattr(route, "passthrough_args", []) or [])
    json_output = bool(flags.get("json"))
    dry_run = bool(flags.get("dry_run"))
    raw_cli = str(flags.get("cli") or "").strip()
    preset_label, presets, preset_error = _resolve_presets(flags=flags, passthrough_args=passthrough_args)

    if preset_error is not None:
        return _print_install_results(
            preset=preset_label,
            dry_run=dry_run,
            json_output=json_output,
            results=[
                PromptInstallResult(
                    cli="*",
                    path="",
                    status="failed",
                    backup_path=None,
                    message=preset_error,
                )
            ],
        )

    if not raw_cli:
        return _print_install_results(
            preset=preset_label,
            dry_run=dry_run,
            json_output=json_output,
            results=[
                PromptInstallResult(
                    cli="",
                    path="",
                    status="failed",
                    backup_path=None,
                    message="Missing required --cli",
                )
            ],
        )

    home = _user_home(runtime)
    selected_clis, invalid_results = _normalize_cli_targets(raw_cli)
    if not selected_clis and not invalid_results:
        invalid_results.append(
            PromptInstallResult(
                cli="",
                path="",
                status="failed",
                backup_path=None,
                message="No valid CLI targets were provided",
            )
        )
    results: list[PromptInstallResult] = list(invalid_results)
    for cli_name in selected_clis:
        for preset in presets:
            results.append(_install_prompt_for_cli(cli_name=cli_name, preset=preset, home=home, dry_run=dry_run))
    return _print_install_results(
        preset=preset_label,
        dry_run=dry_run,
        json_output=json_output,
        results=results,
    )


def _resolve_presets(
    *,
    flags: dict[str, object],
    passthrough_args: list[str],
) -> tuple[str, list[str], str | None]:
    raw_flag_preset = str(flags.get("preset") or "").strip()
    positional_args = [str(token).strip() for token in passthrough_args if str(token).strip()]
    if len(positional_args) > 1:
        extras = ", ".join(positional_args[1:])
        return "", [], f"Unexpected extra arguments for install-prompts: {extras}"
    raw_preset = raw_flag_preset or (positional_args[0] if positional_args else _DEFAULT_PRESET)
    preset = raw_preset.strip() or _DEFAULT_PRESET
    available = sorted(_available_presets())
    if preset == "all":
        return "all", available, None
    if preset not in available:
        return preset, [], _unsupported_preset_message(preset)
    return preset, [preset], None


def _normalize_cli_targets(raw_cli: str) -> tuple[list[str], list[PromptInstallResult]]:
    raw_tokens = [token.strip().lower() for token in raw_cli.split(",") if token.strip()]
    ordered_tokens: list[str] = []
    invalid_results: list[PromptInstallResult] = []
    seen: set[str] = set()
    expand_all = "all" in raw_tokens
    candidate_tokens = (
        list(_SUPPORTED_CLIS) if expand_all else [token for token in raw_tokens if token in _SUPPORTED_CLIS]
    )

    for token in raw_tokens:
        if token in {"all", *_SUPPORTED_CLIS}:
            continue
        invalid_results.append(
            PromptInstallResult(
                cli=token,
                path="",
                status="failed",
                backup_path=None,
                message=f"Unsupported CLI target: {token}",
            )
        )

    for token in candidate_tokens:
        if token in seen:
            continue
        seen.add(token)
        ordered_tokens.append(token)
    return ordered_tokens, invalid_results


def _install_prompt_for_cli(*, cli_name: str, preset: str, home: Path, dry_run: bool) -> PromptInstallResult:
    target_path = _target_path(cli_name=cli_name, preset=preset, home=home)
    backup_path = _backup_path_for_target(target_path) if target_path.exists() else None
    try:
        template = _load_template(preset)
        rendered = _render_preset(cli_name=cli_name, template=template)
    except (LookupError, OSError, ValueError) as exc:
        return PromptInstallResult(
            cli=cli_name,
            path=str(target_path),
            status="failed",
            backup_path=str(backup_path) if backup_path is not None else None,
            message=str(exc),
        )
    if dry_run:
        return PromptInstallResult(
            cli=cli_name,
            path=str(target_path),
            status="planned",
            backup_path=str(backup_path) if backup_path is not None else None,
            message=f"Would install {preset} for {cli_name}",
        )
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and backup_path is not None:
            target_path.replace(backup_path)
        target_path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        return PromptInstallResult(
            cli=cli_name,
            path=str(target_path),
            status="failed",
            backup_path=str(backup_path) if backup_path is not None else None,
            message=str(exc),
        )
    status = "overwritten" if backup_path is not None else "written"
    return PromptInstallResult(
        cli=cli_name,
        path=str(target_path),
        status=status,
        backup_path=str(backup_path) if backup_path is not None else None,
        message=f"Installed {preset} for {cli_name}",
    )


def _target_path(*, cli_name: str, preset: str, home: Path) -> Path:
    if cli_name == "codex":
        return home / ".codex" / "prompts" / f"{preset}.md"
    if cli_name == "claude":
        return home / ".claude" / "commands" / f"{preset}.md"
    if cli_name == "opencode":
        return home / ".config" / "opencode" / "commands" / f"{preset}.md"
    raise RuntimeError(f"Unsupported CLI target: {cli_name}")


def _user_home(runtime: Any) -> Path:
    env = getattr(runtime, "env", {})
    raw_home = str(env.get("HOME", "")).strip() if isinstance(env, dict) else ""
    if raw_home:
        return Path(raw_home).expanduser()
    return Path.home()


def _backup_path_for_target(target_path: Path) -> Path:
    return target_path.with_name(f"{target_path.stem}.bak-{_backup_timestamp()}{target_path.suffix}")


def _backup_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _available_presets() -> frozenset[str]:
    return frozenset(path.stem for path in _template_files())


def _unsupported_preset_message(preset: str) -> str:
    available = ", ".join(sorted(_available_presets()))
    if not available:
        return f"Unsupported preset: {preset}"
    return f"Unsupported preset: {preset}. Available presets: {available}"


def _template_files() -> tuple[resources.abc.Traversable, ...]:
    template_root = resources.files(_PROMPT_TEMPLATE_PACKAGE)
    files: list[resources.abc.Traversable] = []
    for entry in template_root.iterdir():
        if not entry.is_file() or not entry.name.endswith(_PROMPT_TEMPLATE_SUFFIX):
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
    return template.body


def _render_opencode_template(template: PromptTemplate) -> str:
    return template.body


def _print_install_results(
    *,
    preset: str,
    dry_run: bool,
    json_output: bool,
    results: list[PromptInstallResult],
) -> int:
    payload = {
        "command": "install-prompts",
        "preset": preset,
        "dry_run": dry_run,
        "results": [asdict(result) for result in results],
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for result in results:
            line = f"{result.cli or 'install-prompts'}: {result.status} {result.path}".rstrip()
            if result.backup_path:
                line += f" (backup: {result.backup_path})"
            if result.message:
                line += f" - {result.message}"
            print(line)
    return 0 if all(result.status not in {"failed"} for result in results) else 1
