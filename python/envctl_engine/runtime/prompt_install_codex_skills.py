from __future__ import annotations

import json
from pathlib import Path
from typing import Final, Mapping

from envctl_engine.runtime.prompt_install_models import (
    CodexSkillInstallPlan,
    CodexSkillMetadata,
    PromptInstallResult,
    PromptTemplate,
)
from envctl_engine.runtime.prompt_install_paths import _codex_skill_root
from envctl_engine.runtime.prompt_install_templates import _PROMPT_ARGUMENT_PLACEHOLDER, _load_template
from envctl_engine.shared.parsing import parse_bool

_CODEX_SKILL_FEATURE_FLAG: Final = "ENVCTL_EXPERIMENTAL_CODEX_SKILLS"
_CODEX_SKILL_BODY_START: Final = "<!-- ENVCTL_DIRECT_PROMPT_BODY_START -->"
_CODEX_SKILL_BODY_END: Final = "<!-- ENVCTL_DIRECT_PROMPT_BODY_END -->"
_CODEX_SKILL_ARGUMENT_SENTINEL: Final = "additional user instructions supplied with the invoking prompt"


def _codex_skill_feature_enabled(env: Mapping[str, str] | None) -> bool:
    return parse_bool((env or {}).get(_CODEX_SKILL_FEATURE_FLAG), False)


def _codex_skill_markdown_path(*, preset: str, home: Path) -> Path:
    metadata = _codex_skill_metadata(preset)
    return _codex_skill_root(home=home) / metadata.skill_name / "SKILL.md"


def _extract_codex_skill_prompt_body(raw: str, *, preset: str) -> str:
    start = raw.find(_CODEX_SKILL_BODY_START)
    end = raw.find(_CODEX_SKILL_BODY_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Installed Codex skill for {preset} is missing prompt body markers")
    body = raw[start + len(_CODEX_SKILL_BODY_START):end].strip("\n")
    if not body.strip():
        raise ValueError(f"Installed Codex skill for {preset} is missing prompt body")
    return body + "\n"


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


def _codex_skill_metadata(preset: str) -> CodexSkillMetadata:
    mapping = {
        "implement_task": CodexSkillMetadata(
            skill_name="envctl-implement-task",
            display_name="Envctl Implement Task",
            short_description="MAIN_TASK implementation workflow with scoped runtime validation",
            description=(
                "Use when you explicitly want the envctl implement_task workflow for a MAIN_TASK-driven "
                "implementation pass. The skill knows envctl service-scope flags such as --backend, --frontend, "
                "--fullstack/--both, --dependencies/--deps, and --entire-system, plus stop/kill aliases, "
                "when to choose each scope, and expects Playwright E2E validation against a running service "
                "when UI behavior is involved. It also requires final validation and reports runtime addresses "
                "for dependencies, backend, and frontend when a runtime is involved. "
                "Invoke it explicitly as $envctl-implement-task."
            ),
            default_prompt=(
                "Use envctl-implement-task explicitly for this envctl workflow. For runtime validation, "
                "default to `envctl --entire-system --headless` when a change crosses backend/frontend boundaries, "
                "affects API/UI integration, changes browser-visible behavior, needs DB/Redis/queue or other "
                "managed dependencies, or when a narrower scope is not obviously sufficient. Use backend only "
                "for backend-confined changes with "
                "`envctl --backend --headless`. Use frontend only for frontend-confined changes with "
                "`envctl --frontend --headless`. Use `envctl --fullstack --headless` only when backend and "
                "frontend are both needed but managed dependencies are explicitly disabled, mocked, externalized, "
                "or proven unnecessary. Use `envctl --dependencies --headless` for DB/Redis or infrastructure-only "
                "validation. For UI/product work, run Playwright E2E validation against the running service before "
                "claiming completion. Before final handoff, run the final relevant validation after the code "
                "is complete "
                "and report the result. When a runtime was needed or started, report the actual addresses/URLs for "
                "started dependencies, backend, and frontend, or say explicitly which components were not started. "
                "At the end, kill the scope you started with "
                "`envctl stop --backend --headless`, `envctl stop --frontend --headless`, "
                "`envctl stop --fullstack --headless`, `envctl stop --dependencies --headless`, "
                "`envctl stop --entire-system --headless`, or `envctl kill-all --headless`, then offer to "
                "start it again for human verification."
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
        "review_worktree_imp": CodexSkillMetadata(
            skill_name="envctl-review-worktree",
            display_name="Envctl Review Worktree",
            short_description="Read-only origin-side review of an envctl worktree",
            description=(
                "Use when you explicitly want the envctl review_worktree_imp workflow for read-only origin-side "
                "review of a generated implementation worktree. Invoke it explicitly as $envctl-review-worktree."
            ),
        ),
        "merge_implementation_branches": CodexSkillMetadata(
            skill_name="envctl-merge-implementation-branches",
            display_name="Envctl Merge Implementation Branches",
            short_description="Reconcile implementation branches into an integration branch",
            description=(
                "Use when you explicitly want the envctl merge_implementation_branches workflow to reconcile "
                "two implementation branches into a target-neutral integration branch. Invoke it explicitly as "
                "$envctl-merge-implementation-branches."
            ),
        ),
        "create_plan": CodexSkillMetadata(
            skill_name="envctl-create-plan",
            display_name="Envctl Create Plan",
            short_description="Create an envctl implementation plan",
            description=(
                "Use when you explicitly want the envctl create_plan workflow to produce a plan artifact for "
                "implementation work and default envctl follow-up launches to full-stack E2E scope. Invoke it "
                "explicitly as $envctl-create-plan."
            ),
        ),
        "create_plan_auto_codex": CodexSkillMetadata(
            skill_name="envctl-create-plan-auto-codex",
            display_name="Envctl Create Plan Auto Codex",
            short_description="Create a plan and auto-launch Codex implementation",
            description=(
                "Use only when you explicitly invoke $envctl-create-plan-auto-codex to create an envctl "
                "implementation plan and automatically launch the Codex implementation workflow with full-stack "
                "E2E scope by default."
            ),
        ),
        "create_plan_auto_opencode": CodexSkillMetadata(
            skill_name="envctl-create-plan-auto-opencode",
            display_name="Envctl Create Plan Auto OpenCode",
            short_description="Create a plan and auto-launch OpenCode ULW implementation",
            description=(
                "Use only when you explicitly invoke $envctl-create-plan-auto-opencode to create an envctl "
                "implementation plan and automatically launch the OpenCode ULW implementation workflow with "
                "full-stack E2E scope by default."
            ),
        ),
        "create_plan_auto_omx": CodexSkillMetadata(
            skill_name="envctl-create-plan-auto-omx",
            display_name="Envctl Create Plan Auto OMX",
            short_description="Create a plan and auto-launch OMX Ultragoal implementation",
            description=(
                "Use only when you explicitly invoke $envctl-create-plan-auto-omx to create an envctl "
                "implementation plan and automatically launch the OMX Ultragoal implementation workflow with "
                "full-stack E2E scope by default."
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
    body = template.body.replace(_PROMPT_ARGUMENT_PLACEHOLDER, _CODEX_SKILL_ARGUMENT_SENTINEL, 1)
    return (
        f"---\n"
        f"name: {json.dumps(metadata.skill_name)}\n"
        f"description: {json.dumps(metadata.description)}\n"
        f"---\n\n"
        f"# {metadata.display_name}\n\n"
        f"Use this skill explicitly with `{invocation}`.\n\n"
        f"{invocation_note}\n\n"
        f"{_CODEX_SKILL_BODY_START}\n"
        f"{body}"
        f"{_CODEX_SKILL_BODY_END}\n"
    )


def _render_codex_skill_openai_yaml(*, metadata: CodexSkillMetadata) -> str:
    default_prompt = metadata.default_prompt or f"Use {metadata.skill_name} explicitly for this envctl workflow."
    return (
        "interface:\n"
        f"  display_name: {json.dumps(metadata.display_name)}\n"
        f"  short_description: {json.dumps(metadata.short_description)}\n"
        f"  default_prompt: {json.dumps(default_prompt)}\n"
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )
