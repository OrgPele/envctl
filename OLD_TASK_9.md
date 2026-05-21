# Prompt Workflow Modernization Remains Complete

## Context and objective

The previous `MAIN_TASK.md` is archived as `OLD_TASK_8.md`. It recorded that
the prompt workflow modernization sequence had no remaining implementation scope
after these commits:

- `644cc2c Modernize plan-agent prompt workflow`
- `3b0885c Complete residual prompt workflow contract cleanup`
- `aa99171 Archive completed residual prompt workflow task`
- `5bf5b6b Archive completed prompt workflow iteration audit`
- `bcd14fb Archive completed prompt workflow modernization task`

This rollover is audit-only. Current task, code, test, and git evidence show no
remaining prompt workflow implementation work.

## Remaining requirements (complete and exhaustive)

There are no remaining implementation requirements from the prompt workflow
modernization sequence.

Do not infer new work from this completed task history. Any future prompt,
launcher, documentation, validation, `envctl ship`, or `envctl test-plan`
implementation must be driven by a new explicit requirement, bug report,
reviewer finding, or plan.

## Gaps from prior iteration (mapped to evidence)

Fully implemented:

- Plan-agent launch code contains the goal-required queued Codex workflow
  changes:
  - `python/envctl_engine/planning/plan_agent/models.py`
  - `python/envctl_engine/planning/plan_agent/workflow.py`
  - `python/envctl_engine/planning/plan_agent/cmux_transport.py`
  - `python/envctl_engine/planning/plan_agent/tmux_transport.py`
- Runtime prompt templates contain the modern focused-validation,
  protected-artifact, planned `envctl test-plan`, planned `envctl ship`, and
  compact fallback guidance:
  - `python/envctl_engine/runtime/prompt_templates/implement_task.md`
  - `python/envctl_engine/runtime/prompt_templates/finalize_task.md`
  - `python/envctl_engine/runtime/prompt_templates/implement_plan.md`
  - `python/envctl_engine/runtime/prompt_templates/continue_task.md`
  - private plan-agent follow-up templates.
- Auto-Codex and auto-OpenCode create-plan templates select and record
  `selected_launch_scope_flags` and use `<launch_scope_flags>` in launch command
  shapes:
  - `python/envctl_engine/runtime/prompt_templates/create_plan_auto_codex.md`
  - `python/envctl_engine/runtime/prompt_templates/create_plan_auto_opencode.md`
- User docs describe plan-selected launch scope and surface differences:
  - `docs/user/planning-and-worktrees.md`
  - `docs/user/ai-playbooks.md`
- Regression tests cover the prompt contracts, stale broad-scope wording
  removal, continuation contract, and queued goal-frame behavior:
  - `tests/python/runtime/test_prompt_install_support.py`
  - `tests/python/planning/test_plan_agent_launch_support.py`
- Task history is preserved in `OLD_TASK_2.md`, `OLD_TASK_5.md`,
  `OLD_TASK_6.md`, and `OLD_TASK_7.md`.

Partially implemented:

- None.

Not implemented:

- None.

Working-tree evidence:

- `.envctl-state/worktree-provenance.json` has a generated local provenance
  difference. It is not implementation scope and should remain local unless a
  future task explicitly targets provenance metadata behavior.

Validation evidence from the completed implementation:

- `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py`
  passed with `43 passed, 28 subtests passed`.
- `uv run --extra dev pytest -q tests/python/runtime/test_runtime_feature_inventory.py`
  passed with `9 passed`.
- `uv tool run ruff check python tests scripts` passed.

## Acceptance criteria (requirement-by-requirement)

- No implementation changes are required for the prompt workflow modernization
  sequence.
- The next implementation agent must not create new work from this completed
  task history.
- If completion needs reconfirmation, run the focused validation commands listed
  below and inspect current PR state.

## Required implementation scope (frontend/backend/data/integration)

- Frontend: none.
- Backend/runtime services: none.
- Data/migrations/config: none.
- Prompt templates/docs/tests: none remaining from the prior task sequence.

## Required tests and quality gates

No tests are required for new implementation work because no implementation work
remains.

If completion needs to be reconfirmed, run:

- `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py`
- `uv run --extra dev pytest -q tests/python/runtime/test_runtime_feature_inventory.py`
- `uv tool run ruff check python tests scripts`

## Edge cases and failure handling

- Do not treat `.envctl-state/worktree-provenance.json` as a prompt workflow
  implementation gap.
- Do not implement real `envctl ship` or `envctl test-plan` commands from this
  task record; prior tasks intentionally referenced those as planned contracts
  with fallback behavior.
- Do not alter OMX behavior unless a future task explicitly targets OMX.

## Definition of done

- `OLD_TASK_8.md` archives the previous no-remaining-work task record.
- This `MAIN_TASK.md` states that no implementation work remains from the prompt
  workflow modernization sequence.
- Future work starts from a new explicit requirement rather than inferred
  carry-forward scope.
