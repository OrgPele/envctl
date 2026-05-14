from __future__ import annotations

from envctl_engine.planning.plan_agent.models import _PlanAgentWorkflow, _PlanAgentWorkflowStep


def _build_plan_agent_workflow(
    *,
    cli: str,
    preset: str,
    codex_cycles: int,
    direct_prompt_enabled: bool = False,
    browser_e2e_followup_enable: bool = True,
    pr_review_comments_followup_enable: bool = True,
) -> _PlanAgentWorkflow:
    from envctl_engine.planning.plan_agent import launch as _launch

    normalized_cli = str(cli).strip().lower()
    bounded_cycles = max(0, min(int(codex_cycles), _launch._PLAN_AGENT_CODEX_CYCLE_CAP))
    if _launch._uses_direct_submission(cli=normalized_cli, direct_prompt_enabled=direct_prompt_enabled):
        initial_step = _PlanAgentWorkflowStep(kind="submit_direct_prompt", text=str(preset).strip())
    else:
        initial_step = _PlanAgentWorkflowStep(kind="submit_prompt", text=_launch._slash_command(cli, preset))
    if normalized_cli != "codex" or bounded_cycles <= 0:
        steps = [initial_step]
        if normalized_cli == "codex":
            if browser_e2e_followup_enable:
                steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=_launch._browser_e2e_instruction_text()))
            if pr_review_comments_followup_enable:
                steps.append(
                    _PlanAgentWorkflowStep(kind="queue_message", text=_launch._pr_review_comments_instruction_text())
                )
        return _PlanAgentWorkflow(
            mode=_launch._PLAN_AGENT_WORKFLOW_SINGLE_PROMPT,
            codex_cycles=bounded_cycles,
            steps=tuple(steps),
        )
    steps = [_PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task")]
    for cycle in range(1, bounded_cycles + 1):
        if cycle == bounded_cycles:
            steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="finalize_task"))
            if browser_e2e_followup_enable:
                steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=_launch._browser_e2e_instruction_text()))
            if pr_review_comments_followup_enable:
                steps.append(
                    _PlanAgentWorkflowStep(kind="queue_message", text=_launch._pr_review_comments_instruction_text())
                )
            continue
        if cycle == 1:
            completion_text = _launch._first_cycle_completion_instruction_text()
        else:
            completion_text = _launch._intermediate_cycle_completion_instruction_text()
        steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=completion_text))
        steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="continue_task"))
        steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="implement_task"))
    return _PlanAgentWorkflow(
        mode=_launch._PLAN_AGENT_WORKFLOW_CODEX_CYCLES,
        codex_cycles=bounded_cycles,
        steps=tuple(steps),
    )
