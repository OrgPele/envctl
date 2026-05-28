# Envctl Import Startup Failure Handoff Output

## Goal

When `envctl import <remote-branch>` successfully creates or updates the local imported worktree but the follow-on app startup cannot start services, envctl should make the import success clear and then show the startup error at the end of the command output.

The worktree import is durable and should not look rolled back or failed because the subsequent local runtime startup failed. The startup failure should still be visible and actionable.

## Problem

Observed behavior after the remote-branch import work:

- `envctl import <branch>` without `--no-infra` creates the imported worktree, then attempts to start the imported project.
- In a temp repo with no backend/frontend start command, startup fails with `missing_service_start_command`.
- The command exits non-zero, but the output does not clearly frame this as "import succeeded, startup failed afterward."
- `envctl import <branch> --no-infra` skips actual service startup and exits 0, but still prints `Starting 1 project(s)...`, which is misleading because no project services are being started.

Desired behavior:

```text
Imported remote branch origin/feature/foo into trees/imported/feature-foo
...
Startup failed

Imported worktree is ready, but local app startup failed.
project: feature-foo
error: missing_service_start_command: ...
next: configure ENVCTL_BACKEND_START_CMD / ENVCTL_FRONTEND_START_CMD, or rerun import with --no-infra when you only want the worktree.
```

For `--no-infra`, envctl should keep the successful import behavior and avoid printing a misleading `Starting 1 project(s)...` service-start banner.

## Non-Goals

- Do not change the core import semantics for branch normalization, ff-only updates, dirty-worktree protection, or imported worktree paths.
- Do not make real startup failures disappear. Without `--no-infra`, a failed requested startup should continue to fail the command unless an existing plan-agent degraded-handoff path intentionally allows the AI session to continue.
- Do not classify every missing command as "no system configured"; preserve the existing actionable `missing_service_start_command` behavior for import startup failures.
- Do not add a new service autodetection system.
- Do not change unrelated `start`, `restart`, `resume`, `dashboard`, or `--plan` startup output except where shared helpers need to avoid a false "Starting project(s)" line.

## Current Code Map

- `python/envctl_engine/startup/context_selection.py`
  - `_select_imported_worktree()` invokes the import flow and assigns the resulting project context to `session.contexts_to_start`.
  - This is the place to preserve/import metadata needed by finalization, such as imported branch name, worktree name, and path.
- `python/envctl_engine/planning/worktree_import_commands.py`
  - Contains the user-facing import command helpers and remote-branch normalization.
- `python/envctl_engine/planning/worktree_import_orchestration.py`
  - Owns the actual worktree creation/update orchestration and should remain the source of truth for whether import succeeded.
- `python/envctl_engine/startup/selected_context_startup.py`
  - Emits `Starting {len(session.contexts_to_start)} project(s)...` before service startup work.
  - Converts startup exceptions into fatal startup failures or degraded plan-agent local startup failures.
- `python/envctl_engine/startup/finalization.py`
  - Renders final startup failure summaries and plan-agent degraded handoff text.
  - Already has local startup failure rendering for plan-agent paths.
- `python/envctl_engine/startup/plan_agent_handoff.py`
  - Classifies local startup failures such as `missing_service_start_command` for degraded handoff output.
- Tests near:
  - `tests/python/startup/test_startup_context_selection.py`
  - `tests/python/startup/test_selected_context_startup.py`
  - `tests/python/startup/test_startup_finalization.py`
  - `tests/python/startup/test_startup_orchestrator_flow_failure.py`
  - `tests/python/startup/test_startup_orchestrator_flow_handoff.py`

## Implementation Plan

1. Track successful import metadata through startup.
   - Add a small structured field to `StartupSession` or an existing selection result model for the latest import operation.
   - Capture at least:
     - remote branch input / normalized remote branch
     - imported project/worktree name
     - imported worktree path
     - whether the import created, reused, or fast-forwarded the worktree if that status already exists
   - Populate it in `_select_imported_worktree()` only after the import operation succeeds.

2. Render import success before startup attempts.
   - Ensure explicit import success output is emitted before service startup begins.
   - If current import orchestration already prints this, do not duplicate it; instead make the final failure summary reference that successful import.
   - Keep dirty-worktree and ff-only import failures as import failures, not startup failures.

3. Add import-aware startup failure finalization.
   - When a startup failure occurs after a successful import, finalization should append an end-of-output block that says the imported worktree is ready but local app startup failed.
   - Include:
     - imported project/worktree name
     - worktree path
     - startup error and reason
     - next action: configure backend/frontend start commands or use `--no-infra` when only importing the worktree
   - Preserve non-zero exit semantics for plain `envctl import <branch>` when requested startup fails.
   - For import plus plan-agent launch, keep the existing degraded-handoff semantics if the AI session is running, but include the import-ready context before or inside the local startup failure block.

4. Stop printing misleading service-start banners for `--no-infra`.
   - In `selected_context_startup.py`, avoid `Starting N project(s)...` when the selected runtime scope means no service startup will occur.
   - Prefer a precise skip message or no message at all for import-only `--no-infra`.
   - Keep dependency or requirements messages only when that work actually runs.

5. Keep shared startup behavior stable.
   - Existing non-import startup failures should render the same user-facing failure summaries as before.
   - Existing plan-agent local startup failures should keep their AI-session-running handoff text.
   - The import-aware wording should be gated by the import success metadata, not by generic project names.

6. Update documentation.
   - In `docs/reference/commands.md`, document that `envctl import <branch>` creates/updates the imported worktree first, then attempts local startup unless `--no-infra` is supplied.
   - Document that startup failure after import leaves the imported worktree in place and reports startup diagnostics at the end.

## Test Plan

- Add or update import/startup flow tests:
  - successful import followed by `missing_service_start_command` renders import success, then an end-of-output local startup failure block; command remains failed for plain import.
  - failure text includes the imported worktree path and does not imply the import was rolled back.
  - import orchestration failures still render as import failures and do not show the import-ready startup failure block.
- Add `--no-infra` coverage:
  - `envctl import <branch> --no-infra` exits 0 after a successful import.
  - output does not include `Starting 1 project(s)...`.
  - no service start command resolution is attempted.
- Add plan-agent/handoff coverage if import can be combined with plan-agent launch flags:
  - successful import plus running AI session plus local startup failure says the implementation session is running and also says the imported worktree is ready but local app startup failed.
- Regression coverage:
  - non-import startup failure output remains unchanged.
  - explicit backend/frontend command misconfiguration still reports `missing_service_start_command`.

## Verification

Focused tests:

```bash
uv run --extra dev python -m pytest tests/python/startup/test_startup_context_selection.py tests/python/startup/test_selected_context_startup.py
uv run --extra dev python -m pytest tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow_failure.py
```

Broader slice:

```bash
uv run --extra dev python -m pytest tests/python/startup tests/python/planning
```

Manual smoke:

```bash
envctl import origin/<branch-with-no-worktree>
envctl import origin/<branch-with-no-worktree> --no-infra
```

Expected manual result:

- Without `--no-infra`, import succeeds first; if local startup cannot resolve service commands, the final output says the imported worktree is ready but startup failed and shows `missing_service_start_command`.
- With `--no-infra`, import succeeds, exits 0, and does not print `Starting 1 project(s)...`.

## Risks

- The import path may already print partial success messages from lower-level helpers. Avoid duplicate success lines by centralizing final wording or making the final failure block reference the already-imported worktree.
- Startup session state is shared by many command modes. Gate import-specific output on explicit import metadata to avoid changing normal startup flows.
- Some plan-agent paths intentionally degrade local startup failures instead of failing the whole command. Preserve those semantics while improving the local startup failure explanation.

## Implementation Launch

Recommended Codex cycles: 1.

Implementation surface: `--entire-system`, because the bug happens at the boundary between worktree import, startup selection, service startup, and final handoff output.
