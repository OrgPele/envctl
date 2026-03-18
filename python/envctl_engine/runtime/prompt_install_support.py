from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
import sys
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


@dataclass(slots=True)
class PromptInstallPlan:
    cli: str
    preset: str
    target_path: Path
    rendered: str
    existed: bool


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
    overwrite_approved = bool(flags.get("yes")) or bool(flags.get("force"))
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
    plans, planning_failures = _build_install_plans(selected_clis=selected_clis, presets=presets, home=home)
    if planning_failures:
        results.extend(planning_failures)
        return _print_install_results(
            preset=preset_label,
            dry_run=dry_run,
            json_output=json_output,
            results=results,
        )
    overwrite_candidates = [plan for plan in plans if plan.existed]
    if overwrite_candidates and not dry_run and not overwrite_approved:
        overwrite_error = _require_overwrite_approval(
            overwrite_candidates=overwrite_candidates,
            json_output=json_output,
        )
        if overwrite_error is not None:
            results.append(overwrite_error)
            return _print_install_results(
                preset=preset_label,
                dry_run=dry_run,
                json_output=json_output,
                results=results,
            )
    for plan in plans:
        results.append(_install_prompt(plan=plan, dry_run=dry_run))
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


def _build_install_plans(
    *,
    selected_clis: list[str],
    presets: list[str],
    home: Path,
) -> tuple[list[PromptInstallPlan], list[PromptInstallResult]]:
    plans: list[PromptInstallPlan] = []
    failures: list[PromptInstallResult] = []
    for cli_name in selected_clis:
        for preset in presets:
            target_path = _target_path(cli_name=cli_name, preset=preset, home=home)
            try:
                template = _load_template(preset)
                rendered = _render_preset(cli_name=cli_name, template=template)
            except (LookupError, OSError, ValueError) as exc:
                failures.append(
                    PromptInstallResult(
                        cli=cli_name,
                        path=str(target_path),
                        status="failed",
                        backup_path=None,
                        message=str(exc),
                    )
                )
                continue
            plans.append(
                PromptInstallPlan(
                    cli=cli_name,
                    preset=preset,
                    target_path=target_path,
                    rendered=rendered,
                    existed=target_path.exists(),
                )
            )
    return plans, failures


def _require_overwrite_approval(
    *,
    overwrite_candidates: list[PromptInstallPlan],
    json_output: bool,
) -> PromptInstallResult | None:
    if json_output:
        return _overwrite_failure(
            "Overwrite approval required for existing prompt files; rerun with --yes or --force because --json mode cannot prompt.",
        )
    if not _interactive_stdio():
        return _overwrite_failure(
            "Overwrite approval required for existing prompt files; rerun with --yes or --force because no interactive TTY is available.",
        )
    response = input(_overwrite_prompt(overwrite_candidates)).strip().lower()
    if response in {"y", "yes"}:
        return None
    return _overwrite_failure("Overwrite declined; no prompt files were changed.")


def _overwrite_failure(message: str) -> PromptInstallResult:
    return PromptInstallResult(
        cli="install-prompts",
        path="",
        status="failed",
        backup_path=None,
        message=message,
    )


def _interactive_stdio() -> bool:
    stdin_isatty = getattr(sys.stdin, "isatty", None)
    stdout_isatty = getattr(sys.stdout, "isatty", None)
    return bool(callable(stdin_isatty) and stdin_isatty() and callable(stdout_isatty) and stdout_isatty())


def _overwrite_prompt(overwrite_candidates: list[PromptInstallPlan]) -> str:
    lines = [f"Overwrite {len(overwrite_candidates)} existing prompt file(s)?"]
    for plan in overwrite_candidates:
        lines.append(f"- {plan.cli}: {plan.target_path}")
    lines.append("Type 'y' to continue [y/N]: ")
    return "\n".join(lines)


def _install_prompt(*, plan: PromptInstallPlan, dry_run: bool) -> PromptInstallResult:
    if dry_run:
        return PromptInstallResult(
            cli=plan.cli,
            path=str(plan.target_path),
            status="planned",
            backup_path=None,
            message=f"Would install {plan.preset} for {plan.cli}",
        )
    try:
        plan.target_path.parent.mkdir(parents=True, exist_ok=True)
        plan.target_path.write_text(plan.rendered, encoding="utf-8")
    except OSError as exc:
        return PromptInstallResult(
            cli=plan.cli,
            path=str(plan.target_path),
            status="failed",
            backup_path=None,
            message=str(exc),
        )
    status = "overwritten" if plan.existed else "written"
    return PromptInstallResult(
        cli=plan.cli,
        path=str(plan.target_path),
        status=status,
        backup_path=None,
        message=f"Installed {plan.preset} for {plan.cli}",
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
