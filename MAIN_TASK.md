# Envctl Plan-Agent Starter Surface Verification And Observability Closure

## Context and objective
- The previous iteration implemented the core launcher change for newly created cmux workspaces:
  - `python/envctl_engine/planning/plan_agent_launch_support.py` now carries workspace-creation metadata, probes `cmux list-pane-surfaces`, reuses an unambiguous starter surface, and falls back to `cmux new-surface` when probing is empty, ambiguous, or fails.
  - `tests/python/planning/test_plan_agent_launch_support.py` now covers reuse, fallback, parser behavior, and the existing-workspace path.
  - `docs/reference/configuration.md`, `docs/reference/commands.md`, and `docs/user/planning-and-worktrees.md` describe the corrected user-facing behavior.
- The remaining work is to close the evidence gaps that still prevent the original task from being fully proven complete:
  - there is no focused automated coverage for the new observability payloads emitted by the launcher
  - there is no repo-recorded live cmux verification that the real workspace no longer ends up with a redundant starter tab on first-run workspace creation
- Fully implement the remaining scope end to end. Do not stop at analysis. Add tests, run the required real-cmux verification, fix anything uncovered, and update the changelog with exact evidence.

## Remaining requirements (complete and exhaustive)
1. Add focused regression coverage for the new launcher observability behavior.
   - Extend `tests/python/planning/test_plan_agent_launch_support.py` so the tests assert the emitted runtime events for:
     - starter surface reuse on a newly created workspace
     - fallback to `new-surface` when the starter-surface probe is ambiguous
     - normal `new-surface` creation for an already existing workspace
   - Lock the payload contract for:
     - `planning.agent_launch.workspace_surface_probe`
     - `planning.agent_launch.surface_fallback`
     - `planning.agent_launch.surface_created`
   - Assert the relevant bounded payload fields:
     - `workspace_id`
     - `result`
     - `surface_count` when available
     - `surface_id` when available
     - `source` on `planning.agent_launch.surface_created` with `starter_reused` vs `new_surface`
   - Keep the tests narrow and deterministic. Reuse the existing `_RuntimeHarness` event capture.
2. Perform live cmux verification against the actual local binary and current launcher flow.
   - Validate the default first-run workspace creation path:
     - ensure the default implementation workspace does not already exist
     - run `CMUX=true ./bin/envctl --plan` in a real cmux session
     - verify the created implementation workspace contains only the real launched plan-agent surface and no redundant extra starter tab remains
   - Validate the explicit missing named-workspace path:
     - use `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=<new-title> ./bin/envctl --plan`
     - verify the newly created named workspace also ends with only the intended launched surface
   - Validate the existing-workspace rerun path:
     - rerun `--plan` against the now-existing workspace
     - verify envctl opens exactly one new real launch surface there and does not regress existing behavior
   - If live verification exposes any mismatch between the code/tests/docs and real cmux behavior, fix the code, tests, docs, and changelog in the same iteration before declaring completion.
3. Record the verification evidence in the worktree changelog.
   - Append a new dated entry to `docs/changelog/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create-1_changelog.md`.
   - Include the exact verification commands used, what each scenario produced, whether starter reuse or fallback occurred, and any follow-up code/doc changes made as a result.
   - If a scenario can only be validated via fallback on the current machine, state that explicitly and document why.

## Gaps from prior iteration (mapped to evidence)
- Core reuse/fallback implementation is present:
  - `python/envctl_engine/planning/plan_agent_launch_support.py` contains `_WorkspaceLaunchTarget`, `_list_workspace_surfaces(...)`, `_starter_surface_for_new_workspace(...)`, starter-surface reuse in `_launch_single_worktree(...)`, and emitted probe/fallback events.
- Core launcher path coverage is present:
  - `tests/python/planning/test_plan_agent_launch_support.py` covers:
    - created default workspace reuse
    - created named workspace reuse
    - ambiguous starter probe fallback
    - existing workspace explicit `new-surface`
    - parser coverage for `list-pane-surfaces`
- Docs are updated:
  - `docs/reference/configuration.md`
  - `docs/reference/commands.md`
  - `docs/user/planning-and-worktrees.md`
- Remaining evidence gaps:
  - no focused test currently asserts the payload contract for `planning.agent_launch.workspace_surface_probe`, `planning.agent_launch.surface_fallback`, or `planning.agent_launch.surface_created.source`
  - no live cmux verification output is recorded in the repo/changelog showing the real first-run workspace ends with only one launch surface
- Git/code evidence used to derive this gap assessment:
  - `git status --short`
  - `git diff --name-status`
  - `git diff --cached --name-status`
  - `git log --oneline --decorate -n 30`
  - `git log --oneline --decorate -- python/envctl_engine/planning/plan_agent_launch_support.py tests/python/planning/test_plan_agent_launch_support.py docs/reference/configuration.md docs/reference/commands.md docs/user/planning-and-worktrees.md`
  - direct inspection of the changed launcher, tests, docs, and worktree changelog

## Acceptance criteria (requirement-by-requirement)
1. Observability coverage is complete when:
   - reuse-path tests assert `planning.agent_launch.workspace_surface_probe` with `result="single"` and the reused `surface_id`
   - reuse-path tests assert `planning.agent_launch.surface_created` includes `source="starter_reused"`
   - fallback-path tests assert `planning.agent_launch.workspace_surface_probe` with the correct fallback reason and `surface_count` when applicable
   - fallback-path tests assert `planning.agent_launch.surface_fallback` is emitted with the same bounded reason
   - existing-workspace tests assert `planning.agent_launch.surface_created` includes `source="new_surface"` and that no workspace probe/fallback event is emitted for a workspace that already existed
2. Live cmux verification is complete when:
   - the default missing-workspace scenario is run against real cmux and verified to leave only the intended launched surface
   - the explicit missing named-workspace scenario is run against real cmux and verified to leave only the intended launched surface
   - the existing-workspace rerun scenario is run against real cmux and verified to keep the one-new-surface behavior
3. Changelog evidence is complete when:
   - the worktree changelog entry includes exact commands, scenario-by-scenario outcomes, tests run, and any fixes or notes discovered during live verification

## Required implementation scope (frontend/backend/data/integration)
- Frontend:
  - none
- Backend:
  - `python/envctl_engine/planning/plan_agent_launch_support.py` only if live verification or new observability assertions expose a defect or missing event payload
- Data/config:
  - no new config keys or data-model changes are expected
- Integration:
  - `tests/python/planning/test_plan_agent_launch_support.py` observability assertions
  - live cmux verification in the real local environment
  - changelog update with verification evidence

## Required tests and quality gates
- Required automated tests:
  - `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity`
- Required live verification:
  - real cmux run for default missing-workspace creation
  - real cmux run for explicit missing named-workspace creation
  - real cmux rerun for existing workspace behavior
- Quality gate:
  - do not mark this task complete without both the automated tests and the live cmux verification evidence recorded in the changelog

## Edge cases and failure handling
- If `cmux list-pane-surfaces` behaves differently in live verification than the unit tests assumed, update the parser/tests/code together so the behavior is both correct and documented.
- If live verification shows the fallback path still leaves a duplicate starter surface on this cmux build, document the exact trigger and either:
  - implement a safe non-destructive fix in the same iteration, or
  - update the docs/changelog to reflect the proven limitation only if repo evidence shows the limitation cannot be corrected safely in-scope.
- If the local machine cannot run the real cmux verification because cmux or the required AI CLI is unavailable, resolve that prerequisite first; do not close the task with simulated evidence only.

## Definition of done
- Automated tests cover both behavior and observability for starter reuse, fallback, and existing-workspace launches.
- Real cmux verification is executed and recorded for the default created-workspace path, explicit missing named-workspace path, and existing-workspace rerun path.
- Any defects uncovered by live verification are fixed end to end in code, tests, docs, and changelog before completion.
- `docs/changelog/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create-1_changelog.md` contains the final scenario-by-scenario verification evidence.
