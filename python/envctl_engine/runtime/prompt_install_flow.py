from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from envctl_engine.runtime.prompt_install_codex_skills import (
    _build_codex_skill_install_plans,
    _install_codex_skill,
)
from envctl_engine.runtime.prompt_install_models import (
    CodexSkillInstallPlan,
    PromptInstallPlan,
    PromptInstallResult,
    PromptTemplate,
)
from envctl_engine.runtime.prompt_install_paths import (
    _legacy_codex_prompt_path,
    _target_path,
    _user_home,
)
from envctl_engine.runtime.prompt_install_templates import (
    _available_presets,
    _load_template,
    _parse_template,
    _render_preset,
    _unsupported_preset_message,
)
from envctl_engine.ui.path_links import render_path_for_terminal

_SUPPORTED_CLIS: Final[tuple[str, ...]] = ("codex", "claude", "opencode")
_DEFAULT_PRESET: Final = "all"


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
    env = getattr(runtime, "env", {})

    if preset_error is not None:
        return _print_install_results(
            preset=preset_label,
            dry_run=dry_run,
            json_output=json_output,
            env=env,
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
            env=env,
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
    skill_results: list[PromptInstallResult] = []
    prompt_target_clis = [cli_name for cli_name in selected_clis if cli_name != "codex"]
    plans, planning_failures = _build_install_plans(
        selected_clis=prompt_target_clis,
        presets=presets,
        home=home,
        env=env,
    )
    if planning_failures:
        results.extend(planning_failures)
        return _print_install_results(
            preset=preset_label,
            dry_run=dry_run,
            json_output=json_output,
            env=env,
            results=results,
        )
    skill_plans: list[CodexSkillInstallPlan] = []
    if "codex" in selected_clis:
        skill_plans, skill_failures = _build_codex_skill_install_plans(presets=presets, home=home, env=env)
        if skill_failures:
            skill_results.extend(skill_failures)
            return _print_install_results(
                preset=preset_label,
                dry_run=dry_run,
                json_output=json_output,
                env=env,
                results=results,
                skill_results=skill_results,
            )
    overwrite_candidates = [plan for plan in plans if plan.existed] + [plan for plan in skill_plans if plan.existed]
    if overwrite_candidates and not dry_run and not overwrite_approved:
        overwrite_error = _require_overwrite_approval(
            overwrite_candidates=overwrite_candidates,
            json_output=json_output,
            env=env,
        )
        if overwrite_error is not None:
            results.append(overwrite_error)
            return _print_install_results(
                preset=preset_label,
                dry_run=dry_run,
                json_output=json_output,
                env=env,
                results=results,
                skill_results=skill_results,
            )
    for plan in plans:
        results.append(_install_prompt(plan=plan, dry_run=dry_run))
    for plan in skill_plans:
        skill_results.append(_install_codex_skill(plan=plan, dry_run=dry_run))
    return _print_install_results(
        preset=preset_label,
        dry_run=dry_run,
        json_output=json_output,
        env=env,
        results=results,
        skill_results=skill_results,
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
    env: Mapping[str, str] | None = None,
) -> tuple[list[PromptInstallPlan], list[PromptInstallResult]]:
    plans: list[PromptInstallPlan] = []
    failures: list[PromptInstallResult] = []
    for cli_name in selected_clis:
        for preset in presets:
            target_path = _target_path(cli_name=cli_name, preset=preset, home=home, env=env)
            try:
                template = _install_template(cli_name=cli_name, preset=preset, home=home, env=env)
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


def _install_template(
    *,
    cli_name: str,
    preset: str,
    home: Path,
    env: Mapping[str, str] | None = None,
) -> PromptTemplate:
    if cli_name != "codex":
        return _load_template(preset)
    target_path = _target_path(cli_name=cli_name, preset=preset, home=home, env=env)
    legacy_path = _legacy_codex_prompt_path(preset=preset, home=home)
    if not target_path.exists() and legacy_path.is_file():
        return _parse_template(name=preset, raw=legacy_path.read_text(encoding="utf-8"))
    return _load_template(preset)


def _require_overwrite_approval(
    *,
    overwrite_candidates: Sequence[PromptInstallPlan | CodexSkillInstallPlan],
    json_output: bool,
    env: Mapping[str, str] | None = None,
) -> PromptInstallResult | None:
    if json_output:
        return _overwrite_failure(
            "Overwrite approval required for existing prompt files; rerun with --yes or --force "
            "because --json mode cannot prompt.",
        )
    if not _interactive_stdio():
        return _overwrite_failure(
            "Overwrite approval required for existing prompt files; rerun with --yes or --force "
            "because no interactive TTY is available.",
        )
    response = input(_overwrite_prompt(overwrite_candidates, env=env)).strip().lower()
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


def _overwrite_prompt(
    overwrite_candidates: Sequence[PromptInstallPlan | CodexSkillInstallPlan],
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    lines = [f"Overwrite {len(overwrite_candidates)} existing prompt file(s)?"]
    for plan in overwrite_candidates:
        lines.append(f"- {plan.cli}: {render_path_for_terminal(plan.target_path, env=env, stream=sys.stdout)}")
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


def _install_guidance(
    *,
    results: list[PromptInstallResult],
    skill_results: list[PromptInstallResult] | None,
) -> list[dict[str, object]]:
    guidance: list[dict[str, object]] = []
    for result in skill_results or []:
        if result.cli != "codex" or result.kind != "skill" or not result.path:
            continue
        skill_name = Path(result.path).parent.name
        guidance.append(
            {
                "cli": "codex",
                "installed_as": "skill",
                "path": result.path,
                "recommended_invocation": f"${skill_name}",
                "applies_to": ["codex", "omx"],
                "managed_launch_behavior": (
                    "envctl-managed plan launches submit the rendered workflow automatically; "
                    "no manual in-session command is required after launch"
                ),
            }
        )
    for result in results:
        if result.cli != "codex" or result.kind != "prompt" or not result.path:
            continue
        preset = Path(result.path).stem
        guidance.append(
            {
                "cli": "codex",
                "installed_as": "prompt",
                "path": result.path,
                "recommended_invocation": f"/prompts:{preset}",
                "applies_to": ["codex"],
            }
        )
    return guidance


def _print_install_results(
    *,
    preset: str,
    dry_run: bool,
    json_output: bool,
    env: dict[str, str] | Mapping[str, str] | None = None,
    results: list[PromptInstallResult],
    skill_results: list[PromptInstallResult] | None = None,
) -> int:
    combined_results = [*results, *(skill_results or [])]
    guidance = _install_guidance(results=results, skill_results=skill_results)
    payload = {
        "command": "install-prompts",
        "preset": preset,
        "dry_run": dry_run,
        "results": [asdict(result) for result in results],
    }
    if skill_results is not None:
        payload["skill_results"] = [asdict(result) for result in skill_results]
    if guidance:
        payload["guidance"] = guidance
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for result in combined_results:
            rendered_path = render_path_for_terminal(result.path, env=env, stream=sys.stdout) if result.path else ""
            line = f"{result.cli or 'install-prompts'}: {result.status} {rendered_path}".rstrip()
            if result.backup_path:
                line += f" (backup: {render_path_for_terminal(result.backup_path, env=env, stream=sys.stdout)})"
            if result.link_path:
                line += f" (link: {render_path_for_terminal(result.link_path, env=env, stream=sys.stdout)})"
            if result.message:
                line += f" - {result.message}"
            print(line)
        for entry in guidance:
            print(
                "guidance: "
                f"{entry['cli']} installed as {entry['installed_as']} at "
                f"{render_path_for_terminal(str(entry['path']), env=env, stream=sys.stdout)}; "
                f"manual invocation {entry['recommended_invocation']}"
            )
            managed = entry.get("managed_launch_behavior")
            if managed:
                print(f"guidance: {managed}")
    return 0 if all(result.status not in {"failed"} for result in combined_results) else 1
