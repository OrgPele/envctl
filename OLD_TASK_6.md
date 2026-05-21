# Prompt Workflow Residual Contract Cleanup Complete

## Context and objective

The prior `MAIN_TASK.md` is archived as `OLD_TASK_5.md`. It required a focused
residual cleanup after the broader prompt workflow modernization:

- modernize `continue_task.md` with focused validation, planned `envctl
  test-plan`, planned `envctl ship`, protected-artifact handling, and
  goal-scoped continuation wording;
- update auto-Codex and auto-OpenCode create-plan prompts so launch scope is
  selected from plan evidence rather than defaulting every plan to
  `--entire-system`;
- update user docs to describe plan-selected launch scope;
- strengthen prompt-install regression coverage for the updated contract.

Audit evidence shows this scope is fully implemented in commit `3b0885c
Complete residual prompt workflow contract cleanup`, pushed to the active PR
branch. There is no remaining implementation work for the prior task.

## Remaining requirements (complete and exhaustive)

There are no remaining requirements to implement for the prior prompt workflow
residual contract cleanup task.

If a future reviewer or user identifies new prompt workflow behavior, treat it
as a new task with its own explicit requirements rather than carrying it forward
from `OLD_TASK_5.md`.

## Gaps from prior iteration (mapped to evidence)

Fully implemented:

- `python/envctl_engine/runtime/prompt_templates/continue_task.md` now includes
  protected-artifact guidance, focused validation evidence, planned
  `envctl test-plan --project <current-worktree-name> --json`, planned
  `envctl ship --project <current-worktree-name> --json`, compact fallback
  handoff wording, and goal-scoped continuation guidance.
- `python/envctl_engine/runtime/prompt_templates/create_plan_auto_codex.md`
  selects and records `selected_launch_scope_flags`, uses
  `<launch_scope_flags>` in the launch command, and keeps Codex cycle and goal
  behavior intact.
- `python/envctl_engine/runtime/prompt_templates/create_plan_auto_opencode.md`
  selects and records `selected_launch_scope_flags`, uses
  `<launch_scope_flags>` in the OpenCode launch command, and keeps `/ulw-loop`
  behavior intact.
- `docs/user/planning-and-worktrees.md` and `docs/user/ai-playbooks.md`
  describe plan-selected launch scope, including `--no-infra` for prompt/static
  work and `--entire-system` only for runtime, browser, or integration-sensitive
  work.
- `tests/python/runtime/test_prompt_install_support.py` covers the continuation
  contract terms, auto-Codex/OpenCode launch command shapes, and stale
  broad-scope wording removal.
- `OLD_TASK_2.md` remains the archived copy of the previous full prompt
  workflow modernization task, as required by the completed residual task.

Not implemented:

- None.

Partially implemented:

- None.

Validation evidence:

- `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py`
  passed with `43 passed, 28 subtests passed`.
- `uv run --extra dev pytest -q tests/python/runtime/test_runtime_feature_inventory.py`
  passed with `9 passed`.
- `uv tool run ruff check python tests scripts` passed.

Git and PR evidence:

- Commit `3b0885c Complete residual prompt workflow contract cleanup` contains
  the prompt, docs, tests, `MAIN_TASK.md`, `OLD_TASK_2.md`, and commit-message
  updates for the residual cleanup.
- PR `https://github.com/OrgPele/envctl/pull/249` is open with clean merge
  state and no reported required checks for the branch at the time of audit.

## Acceptance criteria (requirement-by-requirement)

- No additional implementation changes are required.
- The next implementation agent should not invent new prompt workflow work from
  the completed prior task.
- If asked to validate the completed task again, rerun the focused validation
  commands listed above and inspect PR state before reporting status.

## Required implementation scope (frontend/backend/data/integration)

- Frontend: none.
- Backend/runtime services: none.
- Data/migrations/config: none.
- Prompt templates/docs/tests: none remaining from the prior task.

## Required tests and quality gates

No tests are required for new implementation work because no implementation work
remains.

If confirmation is requested, rerun:

- `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py`
- `uv run --extra dev pytest -q tests/python/runtime/test_runtime_feature_inventory.py`
- `uv tool run ruff check python tests scripts`

## Edge cases and failure handling

- Do not treat the local `.envctl-state/worktree-provenance.json` metadata
  difference as remaining implementation scope. It is envctl-generated
  provenance and is intentionally local unless an active task explicitly asks to
  modify provenance behavior.
- Do not carry forward implementation of real `envctl ship` or
  `envctl test-plan` commands from the completed prompt-contract task; the prior
  task explicitly scoped those as planned prompt-contract references only.
- Keep OMX launch-scope wording separate unless a new task explicitly targets
  OMX; the completed residual task targeted auto-Codex and auto-OpenCode.

## Definition of done

- `OLD_TASK_5.md` archives the completed residual prompt workflow cleanup task.
- This `MAIN_TASK.md` states that there is no remaining implementation work from
  the prior task.
- The completed implementation remains committed and pushed in `3b0885c`.
