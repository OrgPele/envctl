# Prompt Workflow Iteration Complete

## Context and objective

The previous `MAIN_TASK.md` is archived as `OLD_TASK_6.md`. That task already
recorded that the residual prompt workflow cleanup had no remaining
implementation work after commit `3b0885c Complete residual prompt workflow
contract cleanup` and the follow-up archive commit `aa99171 Archive completed
residual prompt workflow task`.

This iteration is an audit-only rollover. The objective is to preserve task
history and keep the next implementation task accurate: there is still no
remaining implementation scope to carry forward from the prompt workflow
modernization work.

## Remaining requirements (complete and exhaustive)

There are no remaining requirements to implement from the prompt workflow
modernization or residual cleanup tasks.

Do not invent additional prompt workflow work from this completed task history.
Any future prompt, launcher, documentation, or validation behavior change must
come from a new explicit requirement, reviewer finding, bug report, or plan.

## Gaps from prior iteration (mapped to evidence)

Fully implemented:

- Commit `644cc2c Modernize plan-agent prompt workflow` implemented the broader
  prompt workflow modernization, including goal-required queued Codex steps,
  modern implementation/finalization prompt wording, plan-agent follow-up
  cleanup, OMX initial-goal wording, docs, and regression coverage.
- Commit `3b0885c Complete residual prompt workflow contract cleanup`
  completed the remaining residual scope by modernizing `continue_task.md`,
  updating auto-Codex and auto-OpenCode create-plan launch-scope wording,
  updating user docs, and strengthening prompt-install tests.
- Commit `aa99171 Archive completed residual prompt workflow task` archived the
  completed residual task as `OLD_TASK_5.md` and replaced `MAIN_TASK.md` with a
  no-remaining-work record.
- Current code evidence shows:
  - `python/envctl_engine/runtime/prompt_templates/continue_task.md` includes
    protected artifacts, focused validation, planned `envctl test-plan`,
    planned `envctl ship`, and goal-scoped continuation wording.
  - `python/envctl_engine/runtime/prompt_templates/create_plan_auto_codex.md`
    and `python/envctl_engine/runtime/prompt_templates/create_plan_auto_opencode.md`
    record `selected_launch_scope_flags` and use `<launch_scope_flags>` in
    launch command shapes.
  - `tests/python/runtime/test_prompt_install_support.py` asserts the modern
    continuation and auto-launch contracts and rejects stale broad-scope wording
    for auto-Codex and auto-OpenCode.

Partially implemented:

- None.

Not implemented:

- None.

Working-tree evidence:

- `.envctl-state/worktree-provenance.json` has a local generated provenance
  difference. It is not remaining implementation scope and should remain local
  unless a future task explicitly targets provenance behavior or metadata.

Validation evidence from the completed implementation:

- `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py`
  passed with `43 passed, 28 subtests passed`.
- `uv run --extra dev pytest -q tests/python/runtime/test_runtime_feature_inventory.py`
  passed with `9 passed`.
- `uv tool run ruff check python tests scripts` passed.

## Acceptance criteria (requirement-by-requirement)

- No implementation changes are required for the prior prompt workflow scope.
- The next implementation agent must treat this task as complete unless new
  external evidence supplies a fresh requirement.
- If asked to reconfirm completion, rerun the focused validation commands listed
  in this file and inspect current PR state before reporting.

## Required implementation scope (frontend/backend/data/integration)

- Frontend: none.
- Backend/runtime services: none.
- Data/migrations/config: none.
- Prompt templates/docs/tests: none remaining from the prior task.

## Required tests and quality gates

No tests are required for new implementation work because no implementation work
remains.

If completion needs to be reconfirmed, run:

- `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py`
- `uv run --extra dev pytest -q tests/python/runtime/test_runtime_feature_inventory.py`
- `uv tool run ruff check python tests scripts`

## Edge cases and failure handling

- Do not treat generated `.envctl-state/worktree-provenance.json` metadata as a
  product or prompt-workflow gap.
- Do not carry forward real implementation of `envctl ship` or `envctl
  test-plan`; those were explicitly prompt-contract references with fallback
  behavior in the completed task.
- Do not alter OMX behavior from this task record. The completed residual scope
  targeted auto-Codex and auto-OpenCode launch-scope wording.

## Definition of done

- `OLD_TASK_6.md` archives the previous no-remaining-work task record.
- This `MAIN_TASK.md` states that no implementation work remains from the prompt
  workflow modernization sequence.
- Future work starts from a new explicit requirement rather than inferred
  carry-forward scope.
