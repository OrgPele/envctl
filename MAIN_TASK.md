# Complete Import Startup Failure Handoff Rollover

## Context and objective

The previous task, now archived as `OLD_TASK_1.md`, required `envctl import <remote-branch>` to make durable import success clear when follow-on local app startup fails, and to avoid misleading service-start output for `--no-infra`.

Code and test evidence in this worktree shows that the previous implementation scope is complete. There is no remaining product implementation required for the import startup failure handoff behavior.

The objective for this iteration is to preserve the completed task history and treat the branch as ready for review/merge once the stacked prerequisite branch is available. Do not invent additional feature work beyond maintaining the completed state and resolving review or merge issues if they appear.

## Remaining requirements (complete and exhaustive)

There are no remaining implementation requirements from the archived task.

Maintain the completed behavior:

- Successful import metadata is recorded after import orchestration succeeds and before local startup finalization.
- Plain `envctl import <branch>` still exits non-zero when requested local startup fails, while the output says the imported worktree is ready and includes actionable startup diagnostics.
- `envctl import <branch> --no-infra` exits successfully after import and does not print a misleading `Starting 1 project(s)...` service-start banner.
- Import plus explicit plan-agent launch keeps degraded-handoff semantics and includes import-ready context when local startup fails.
- Non-import startup failure output remains gated away from import-specific messaging.
- Documentation reflects import-first, startup-second behavior.
- The OMX attach polling fix remains in place so focused validation does not fail when session state is written during the final sleep interval.

## Gaps from prior iteration (mapped to evidence)

No product gaps remain from `OLD_TASK_1.md`.

Evidence:

- `git diff origin/features_envctl_import_remote_branch_worktrees-2..HEAD --name-status` shows the completed import handoff delta plus the focused OMX polling validation fix.
- Commit `000c0d17` implements import startup failure handoff behavior across startup session state, context selection, selected-context startup, finalization, run-state metadata, docs, and tests.
- Commit `9d497de4` stabilizes OMX attach polling after `envctl test-focused` exposed a deterministic validation failure.
- Focused import/startup tests pass: `47 passed`.
- Focused validation passes after the OMX fix: `516 passed, 82 subtests passed`; ruff passed for the touched OMX helper.
- PR `https://github.com/OrgPele/envctl/pull/281` is open and mergeable when based on `features_envctl_import_remote_branch_worktrees-2`.

Operational note:

- `envctl ship` predicts conflicts against `origin/main` because this branch is stacked on `features_envctl_import_remote_branch_worktrees-2`. GitHub reports PR #281 as mergeable against that stacked base. Do not merge `origin/main` into this worktree solely to satisfy that predictor unless the intended PR base changes.

## Acceptance criteria (requirement-by-requirement)

Because no implementation work remains, acceptance is evidence-based:

- `MAIN_TASK.md` clearly states that the archived import startup handoff task is complete and that no remaining product implementation is required.
- `OLD_TASK_1.md` contains the full previous task text.
- The worktree remains clean apart from this rollover until the rollover files are committed.
- If validation is rerun, the following commands continue to pass:
  - `envctl test-focused`
  - `uv run --extra dev python -m pytest tests/python/startup/test_startup_context_selection.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_finalization.py tests/python/runtime/test_engine_runtime_import_startup.py`

## Required implementation scope (frontend/backend/data/integration)

No frontend, backend, data, runtime, or integration implementation remains.

Only task-management files are in scope for this rollover:

- `OLD_TASK_1.md`
- `MAIN_TASK.md`

If future review comments or merge conflicts identify a real code issue, handle that issue in a new implementation pass using the current PR/review evidence as source of truth.

## Required tests and quality gates

No new tests are required for this rollover because it does not change product code.

Previously completed validation evidence:

- `envctl test-focused` passed with `516 passed, 82 subtests passed`; ruff passed for `python/envctl_engine/planning/plan_agent/omx_attach_support.py`.
- `uv run --extra dev python -m pytest tests/python/planning/test_plan_agent_omx_attach_discovery.py::PlanAgentOmxAttachDiscoveryTests::test_omx_new_session_wait_checks_state_written_by_final_sleep` passed.
- `uv run --extra dev python -m pytest tests/python/startup/test_startup_context_selection.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_finalization.py tests/python/runtime/test_engine_runtime_import_startup.py` passed with `47 passed`.

Before merging or responding to a new code-review request, rerun the relevant focused command if the code or PR base changes.

## Edge cases and failure handling

No unimplemented edge cases remain from the archived task.

Preserve the existing covered edge cases:

- Import orchestration failures remain import failures and do not show the import-ready startup failure block.
- Local startup failures after successful import preserve `missing_service_start_command` diagnostics.
- `--no-infra` import does not attempt service start command resolution.
- Plan-agent local startup degradation includes import-ready context without changing whether the AI session continues.
- Normal non-import startup failures do not receive import-specific output.

## Definition of done

This rollover iteration is done when:

- `MAIN_TASK.md` has been archived to `OLD_TASK_1.md`.
- This new `MAIN_TASK.md` states that there is no remaining implementation scope.
- Git evidence has been recorded in the handoff summary.
- The rollover files are committed and pushed through the repo's normal shipping flow, or any shipping blocker is documented with the exact status.
