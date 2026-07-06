from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from envctl_engine.planning.plan_agent.constants import (
    _BROWSER_E2E_FOLLOWUP_TEMPLATE,
    _DEFAULT_PRESET,
    _FINALIZATION_INSTRUCTION_TEMPLATE,
    _FIRST_CYCLE_COMPLETION_TEMPLATE,
    _INTERMEDIATE_CYCLE_COMPLETION_TEMPLATE,
    _LOW_SIGNAL_TAB_TITLE_WORDS,
    _PLAN_AGENT_CODEX_CYCLE_CAP,
    _PLAN_AGENT_TAB_TITLE_MAX_LEN,
    _PLAN_AGENT_WORKFLOW_CODEX_CYCLES,
    _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT,
    _PR_REVIEW_COMMENTS_FOLLOWUP_TEMPLATE,
    _PROMPT_TEMPLATE_PACKAGE,
)
from envctl_engine.planning.plan_agent.launch_policy import uses_direct_submission
from envctl_engine.planning.plan_agent.models import _PlanAgentWorkflow, _PlanAgentWorkflowStep
from envctl_engine.runtime.prompt_install_support import codex_skill_invocation_for_preset


@dataclass(frozen=True, slots=True)
class PlanAgentWorkflowBuilder:
    cli: str
    preset: str
    codex_cycles: int
    direct_prompt_enabled: bool = False
    browser_e2e_followup_enable: bool = False
    pr_review_comments_followup_enable: bool = False

    def build(self) -> _PlanAgentWorkflow:
        normalized_cli = str(self.cli).strip().lower()
        bounded_cycles = max(0, min(int(self.codex_cycles), _PLAN_AGENT_CODEX_CYCLE_CAP))
        requires_goal = normalized_cli == "codex"
        initial_step = self._initial_step(normalized_cli=normalized_cli, requires_goal=requires_goal)
        if normalized_cli != "codex" or bounded_cycles <= 0:
            return _PlanAgentWorkflow(
                mode=_PLAN_AGENT_WORKFLOW_SINGLE_PROMPT,
                codex_cycles=bounded_cycles,
                steps=tuple(self._single_prompt_steps(initial_step, normalized_cli=normalized_cli)),
            )
        return _PlanAgentWorkflow(
            mode=_PLAN_AGENT_WORKFLOW_CODEX_CYCLES,
            codex_cycles=bounded_cycles,
            steps=tuple(self._codex_cycle_steps(bounded_cycles, requires_goal=False)),
        )

    def _initial_step(self, *, normalized_cli: str, requires_goal: bool) -> _PlanAgentWorkflowStep:
        if uses_direct_submission(cli=normalized_cli, direct_prompt_enabled=self.direct_prompt_enabled):
            return _PlanAgentWorkflowStep(
                kind="submit_direct_prompt",
                text=str(self.preset).strip(),
                requires_goal=requires_goal,
            )
        return _PlanAgentWorkflowStep(kind="submit_prompt", text=_slash_command(normalized_cli, self.preset))

    def _single_prompt_steps(
        self,
        initial_step: _PlanAgentWorkflowStep,
        *,
        normalized_cli: str,
    ) -> list[_PlanAgentWorkflowStep]:
        steps = [initial_step]
        if normalized_cli == "codex":
            steps.extend(self._terminal_followup_steps(requires_goal=False))
        return steps

    def _codex_cycle_steps(self, bounded_cycles: int, *, requires_goal: bool) -> list[_PlanAgentWorkflowStep]:
        steps = [
            _PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task", requires_goal=requires_goal)
        ]
        for _cycle in range(bounded_cycles):
            steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="continue_task", requires_goal=False))
            steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="implement_task", requires_goal=False))
        steps.extend(self._terminal_followup_steps(requires_goal=False))
        return steps

    def _terminal_followup_steps(self, *, requires_goal: bool) -> list[_PlanAgentWorkflowStep]:
        steps: list[_PlanAgentWorkflowStep] = []
        if self.browser_e2e_followup_enable:
            steps.append(
                _PlanAgentWorkflowStep(
                    kind="queue_message",
                    text=_browser_e2e_instruction_text(),
                    requires_goal=requires_goal,
                )
            )
        if self.pr_review_comments_followup_enable:
            steps.append(
                _PlanAgentWorkflowStep(
                    kind="queue_message",
                    text=_pr_review_comments_instruction_text(),
                    requires_goal=requires_goal,
                )
            )
        return steps


def _build_plan_agent_workflow(
    *,
    cli: str,
    preset: str,
    codex_cycles: int,
    direct_prompt_enabled: bool = False,
    browser_e2e_followup_enable: bool = False,
    pr_review_comments_followup_enable: bool = False,
) -> _PlanAgentWorkflow:
    return PlanAgentWorkflowBuilder(
        cli=cli,
        preset=preset,
        codex_cycles=codex_cycles,
        direct_prompt_enabled=direct_prompt_enabled,
        browser_e2e_followup_enable=browser_e2e_followup_enable,
        pr_review_comments_followup_enable=pr_review_comments_followup_enable,
    ).build()


def _finalization_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_FINALIZATION_INSTRUCTION_TEMPLATE)


def _first_cycle_completion_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_FIRST_CYCLE_COMPLETION_TEMPLATE)


def _intermediate_cycle_completion_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_INTERMEDIATE_CYCLE_COMPLETION_TEMPLATE)


def _browser_e2e_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_BROWSER_E2E_FOLLOWUP_TEMPLATE)


def _pr_review_comments_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_PR_REVIEW_COMMENTS_FOLLOWUP_TEMPLATE)


def _load_plan_agent_followup_prompt(name: str) -> str:
    template_name = f"{str(name).strip()}.md"
    template_file = resources.files(_PROMPT_TEMPLATE_PACKAGE).joinpath(template_name)
    if not template_file.is_file():
        raise LookupError(f"Missing plan-agent follow-up prompt template: {template_name}")
    body = template_file.read_text(encoding="utf-8").strip()
    if not body:
        raise ValueError(f"Plan-agent follow-up prompt template is empty: {template_name}")
    return body


def _tab_title_for_worktree(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        return "implementation"
    parts = [part.strip() for part in normalized.split("_") if str(part).strip()]
    if len(parts) < 4:
        return normalized
    tail_parts: list[str] = []
    for part in reversed(parts[1:]):
        if len(tail_parts) >= 3:
            break
        if part in _LOW_SIGNAL_TAB_TITLE_WORDS:
            continue
        tail_parts.append(part)
    tail_parts.reverse()
    candidate = "_".join([parts[0], *tail_parts]) if tail_parts else normalized
    if len(candidate) <= _PLAN_AGENT_TAB_TITLE_MAX_LEN:
        return candidate
    fallback_tail = tail_parts[-2:] if tail_parts else parts[-2:]
    fallback = "_".join([parts[0], *fallback_tail])
    return fallback or candidate or normalized


def _slash_command(cli: str, preset: str, *, arguments: str = "") -> str:
    normalized = str(preset).strip()
    if not normalized:
        normalized = _DEFAULT_PRESET
    trimmed = normalized[1:] if normalized.startswith("/") else normalized
    if str(cli).strip().lower() == "codex":
        return codex_skill_invocation_for_preset(preset=trimmed, arguments=arguments)
    else:
        command = normalized if normalized.startswith("/") else f"/{normalized}"
    extra = " ".join(str(arguments).split())
    if not extra:
        return command
    return f"{command} {extra}"


__all__ = tuple(name for name in globals() if not name.startswith("__"))
