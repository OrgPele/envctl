from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
import sys
from typing import Any, Final, Mapping, Sequence

from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.path_links import render_path_for_terminal

_SUPPORTED_CLIS: Final[tuple[str, ...]] = ("codex", "claude", "opencode")
_DEFAULT_PRESET = "all"
_PROMPT_TEMPLATE_PACKAGE = "envctl_engine.runtime.prompt_templates"
_PROMPT_TEMPLATE_SUFFIX = ".md"
_CODEX_SKILL_FEATURE_FLAG = "ENVCTL_EXPERIMENTAL_CODEX_SKILLS"
_PROMPT_ARGUMENT_PLACEHOLDER = "$ARGUMENTS"


@dataclass(slots=True)
class PromptInstallResult:
    cli: str
    path: str
    status: str
    backup_path: str | None
    message: str
    kind: str = "prompt"
    link_path: str | None = None


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


@dataclass(slots=True)
class CodexSkillInstallPlan:
    cli: str
    preset: str
    skill_name: str
    skill_dir: Path
    target_path: Path
    agents_path: Path
    rendered: str
    rendered_openai_yaml: str
    existed: bool


@dataclass(slots=True, frozen=True)
class CodexSkillMetadata:
    skill_name: str
    display_name: str
    short_description: str
    description: str


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
    with_codex_skills = bool(flags.get("with_codex_skills"))
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

    if with_codex_skills and not _codex_skill_feature_enabled(env):
        return _print_install_results(
            preset=preset_label,
            dry_run=dry_run,
            json_output=json_output,
            env=env,
            results=[
                PromptInstallResult(
                    cli="codex",
                    path="",
                    status="failed",
                    backup_path=None,
                    message=(
                        f"Codex skill installation is experimental; set {_CODEX_SKILL_FEATURE_FLAG}=true to use "
                        "--with-codex-skills."
                    ),
                    kind="skill",
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
    if with_codex_skills and "codex" not in selected_clis:
        invalid_results.append(
            PromptInstallResult(
                cli="codex",
                path="",
                status="failed",
                backup_path=None,
                message="Codex skill installation requires --cli codex or --cli all.",
                kind="skill",
            )
        )
    results: list[PromptInstallResult] = list(invalid_results)
    skill_results: list[PromptInstallResult] = []
    plans, planning_failures = _build_install_plans(
        selected_clis=selected_clis,
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
    if with_codex_skills and "codex" in selected_clis:
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
            "Overwrite approval required for existing prompt files; rerun with --yes or --force because --json mode cannot prompt.",
        )
    if not _interactive_stdio():
        return _overwrite_failure(
            "Overwrite approval required for existing prompt files; rerun with --yes or --force because no interactive TTY is available.",
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


def codex_preset_uses_direct_submission(preset: str) -> bool:
    return bool(str(preset).strip())


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
    target_path = _target_path(cli_name="codex", preset=normalized_preset, home=home, env=env)
    legacy_path = _legacy_codex_prompt_path(preset=normalized_preset, home=home)
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
    return _render_direct_prompt_arguments(template.body, arguments=arguments)


def _codex_envctl_prompt_root(*, home: Path, env: Mapping[str, str] | None = None) -> Path:
    raw_xdg = str((env or {}).get("XDG_CONFIG_HOME", "")).strip()
    config_home = Path(raw_xdg).expanduser() if raw_xdg else home / ".config"
    return config_home / "envctl" / "codex" / "prompts"


def _legacy_codex_prompt_path(*, preset: str, home: Path) -> Path:
    return home / ".codex" / "prompts" / f"{preset}.md"


def _user_home(runtime: Any) -> Path:
    env = getattr(runtime, "env", {})
    return _user_home_from_env(env if isinstance(env, dict) else {})


def _user_home_from_env(env: Mapping[str, str] | None) -> Path:
    raw_home = str((env or {}).get("HOME", "")).strip()
    if raw_home:
        return Path(raw_home).expanduser()
    return Path.home()


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


def _render_direct_prompt_arguments(body: str, *, arguments: str) -> str:
    replacement = str(arguments or "")
    return str(body).replace(_PROMPT_ARGUMENT_PLACEHOLDER, replacement, 1)


def _codex_skill_feature_enabled(env: Mapping[str, str] | None) -> bool:
    return parse_bool((env or {}).get(_CODEX_SKILL_FEATURE_FLAG), False)


def _build_codex_skill_install_plans(
    *,
    presets: list[str],
    home: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[list[CodexSkillInstallPlan], list[PromptInstallResult]]:
    plans: list[CodexSkillInstallPlan] = []
    failures: list[PromptInstallResult] = []
    skill_root = _codex_skill_root(home=home)
    for preset in presets:
        try:
            template = _load_template(preset)
            metadata = _codex_skill_metadata(preset)
            skill_dir = skill_root / metadata.skill_name
            target_path = skill_dir / "SKILL.md"
            agents_path = skill_dir / "agents" / "openai.yaml"
            plans.append(
                CodexSkillInstallPlan(
                    cli="codex",
                    preset=preset,
                    skill_name=metadata.skill_name,
                    skill_dir=skill_dir,
                    target_path=target_path,
                    agents_path=agents_path,
                    rendered=_render_codex_skill_markdown(template=template, metadata=metadata),
                    rendered_openai_yaml=_render_codex_skill_openai_yaml(metadata=metadata),
                    existed=skill_dir.exists(),
                )
            )
        except (LookupError, OSError, ValueError) as exc:
            failures.append(
                PromptInstallResult(
                    cli="codex",
                    path=str(skill_root / preset),
                    status="failed",
                    backup_path=None,
                    message=str(exc),
                    kind="skill",
                )
            )
    return plans, failures


def _install_codex_skill(*, plan: CodexSkillInstallPlan, dry_run: bool) -> PromptInstallResult:
    if dry_run:
        return PromptInstallResult(
            cli=plan.cli,
            path=str(plan.target_path),
            status="planned",
            backup_path=None,
            message=f"Would install {plan.skill_name} for codex from preset {plan.preset}",
            kind="skill",
        )
    try:
        if plan.skill_dir.exists() and not plan.skill_dir.is_dir():
            if plan.skill_dir.is_symlink() or plan.skill_dir.is_file():
                plan.skill_dir.unlink()
            else:
                raise OSError(f"Unsupported existing skill path: {plan.skill_dir}")
        plan.agents_path.parent.mkdir(parents=True, exist_ok=True)
        plan.target_path.write_text(plan.rendered, encoding="utf-8")
        plan.agents_path.write_text(plan.rendered_openai_yaml, encoding="utf-8")
    except OSError as exc:
        return PromptInstallResult(
            cli=plan.cli,
            path=str(plan.target_path),
            status="failed",
            backup_path=None,
            message=str(exc),
            kind="skill",
        )
    status = "overwritten" if plan.existed else "written"
    return PromptInstallResult(
        cli=plan.cli,
        path=str(plan.target_path),
        status=status,
        backup_path=None,
        message=f"Installed {plan.skill_name} for codex from preset {plan.preset}",
        kind="skill",
    )


def _codex_skill_root(*, home: Path) -> Path:
    return home / ".agents" / "skills"


def _codex_skill_metadata(preset: str) -> CodexSkillMetadata:
    mapping = {
        "implement_plan": CodexSkillMetadata(
            skill_name="envctl-implement-plan",
            display_name="Envctl Implement Plan",
            short_description="MAIN_TASK-driven implementation workflow",
            description=(
                "Use when you explicitly want the envctl implement_plan workflow for a MAIN_TASK-driven "
                "implementation pass. Invoke it explicitly as $envctl-implement-plan."
            ),
        ),
        "implement_task": CodexSkillMetadata(
            skill_name="envctl-implement-task",
            display_name="Envctl Implement Task",
            short_description="MAIN_TASK-driven implementation workflow",
            description=(
                "Use when you explicitly want the envctl implement_task workflow for a MAIN_TASK-driven "
                "implementation pass. Invoke it explicitly as $envctl-implement-task."
            ),
        ),
        "continue_task": CodexSkillMetadata(
            skill_name="envctl-continue-task",
            display_name="Envctl Continue Task",
            short_description="Resume an incomplete envctl implementation pass",
            description=(
                "Use when you explicitly want the envctl continue_task workflow to audit the current implementation "
                "state and continue work. Invoke it explicitly as $envctl-continue-task."
            ),
        ),
        "finalize_task": CodexSkillMetadata(
            skill_name="envctl-finalize-task",
            display_name="Envctl Finalize Task",
            short_description="Finalize an envctl implementation branch for handoff",
            description=(
                "Use when you explicitly want the envctl finalize_task workflow to validate, commit, push, and "
                "prepare the branch for PR handoff. Invoke it explicitly as $envctl-finalize-task."
            ),
        ),
        "review_task_imp": CodexSkillMetadata(
            skill_name="envctl-review-task",
            display_name="Envctl Review Task",
            short_description="Review an implementation against its original plan",
            description=(
                "Use when you explicitly want the envctl review_task_imp workflow to review a worktree "
                "implementation against its originating plan. Invoke it explicitly as $envctl-review-task."
            ),
        ),
        "review_worktree_imp": CodexSkillMetadata(
            skill_name="envctl-review-worktree",
            display_name="Envctl Review Worktree",
            short_description="Read-only origin-side review of an envctl worktree",
            description=(
                "Use when you explicitly want the envctl review_worktree_imp workflow for read-only origin-side "
                "review of a generated implementation worktree. Invoke it explicitly as $envctl-review-worktree."
            ),
        ),
        "merge_trees_into_dev": CodexSkillMetadata(
            skill_name="envctl-merge-trees-into-dev",
            display_name="Envctl Merge Trees Into Dev",
            short_description="Merge two implementation branches into dev",
            description=(
                "Use when you explicitly want the envctl merge_trees_into_dev workflow to reconcile two "
                "implementation branches into dev. Invoke it explicitly as $envctl-merge-trees-into-dev."
            ),
        ),
        "create_plan": CodexSkillMetadata(
            skill_name="envctl-create-plan",
            display_name="Envctl Create Plan",
            short_description="Create an envctl implementation plan",
            description=(
                "Use when you explicitly want the envctl create_plan workflow to produce a plan artifact for "
                "implementation work. Invoke it explicitly as $envctl-create-plan."
            ),
        ),
        "ship_release": CodexSkillMetadata(
            skill_name="envctl-ship-release",
            display_name="Envctl Ship Release",
            short_description="Prepare and ship a production release",
            description=(
                "Use when you explicitly want the envctl ship_release workflow to prepare and ship a production "
                "release end-to-end. Invoke it explicitly as $envctl-ship-release."
            ),
        ),
    }
    try:
        return mapping[str(preset).strip()]
    except KeyError as exc:
        raise LookupError(f"No Codex skill metadata is defined for preset: {preset}") from exc


def _render_codex_skill_markdown(*, template: PromptTemplate, metadata: CodexSkillMetadata) -> str:
    invocation = f"${metadata.skill_name}"
    invocation_note = (
        "Treat any extra text in the invoking user message as the optional additional instructions "
        "that the prompt version would have received through `$ARGUMENTS`."
    )
    body = _render_direct_prompt_arguments(
        template.body,
        arguments="additional user instructions supplied with the invoking prompt",
    )
    return (
        f"---\n"
        f"name: {json.dumps(metadata.skill_name)}\n"
        f"description: {json.dumps(metadata.description)}\n"
        f"---\n\n"
        f"# {metadata.display_name}\n\n"
        f"Use this skill explicitly with `{invocation}`.\n\n"
        f"{invocation_note}\n\n"
        f"{body}"
    )


def _render_codex_skill_openai_yaml(*, metadata: CodexSkillMetadata) -> str:
    return (
        "interface:\n"
        f"  display_name: {json.dumps(metadata.display_name)}\n"
        f"  short_description: {json.dumps(metadata.short_description)}\n"
        f"  default_prompt: {json.dumps(f'Use {metadata.skill_name} explicitly for this envctl workflow.')}\n"
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )


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
    payload = {
        "command": "install-prompts",
        "preset": preset,
        "dry_run": dry_run,
        "results": [asdict(result) for result in results],
    }
    if skill_results is not None:
        payload["skill_results"] = [asdict(result) for result in skill_results]
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
    return 0 if all(result.status not in {"failed"} for result in combined_results) else 1
