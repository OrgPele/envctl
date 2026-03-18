## 2026-03-18 - Reuse starter surface for newly created plan-agent workspaces

Scope:
- Fixed the `--plan` cmux launch flow so envctl no longer leaves behind a redundant starter tab when it has to create the target workspace first.
- Kept the existing behavior unchanged for launches into already existing workspaces and for explicit workspace handles that do not require workspace creation.

Key behavior changes:
- Workspace resolution now carries creation metadata and an optional starter surface id instead of handing the launch path only a bare workspace ref.
- After `cmux new-workspace`, envctl now probes `cmux list-pane-surfaces --workspace <workspace>` and reuses the starter surface only when the probe returns exactly one surface.
- When the probe returns zero surfaces, multiple surfaces, or the command fails, envctl emits bounded fallback diagnostics and safely falls back to `cmux new-surface`.
- Reused starter surfaces still follow the same bootstrap path as explicit surfaces: rename tab, respawn shell, `cd` into the worktree, launch the configured AI CLI, and send the configured preset.
- Launch diagnostics now distinguish `planning.agent_launch.surface_created` sources (`starter_reused` vs `new_surface`) and emit workspace probe/fallback events.
- Planning docs now describe the corrected behavior for newly created target workspaces, and `docs/reference/commands.md` no longer contains the stale merge-marker block in that section.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/changelog/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed (`Ran 27 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed (`Ran 55 tests`, `OK`)

Config / env / migrations:
- No new config keys or migrations.
- Existing `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`, `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE`, and `CMUX` workflows keep the same external config contract.

Risks / notes:
- Starter-surface reuse still depends on the local `cmux list-pane-surfaces` CLI shape; envctl intentionally reuses only an unambiguous single-surface result and falls back otherwise.
- The launcher now emits additional bounded diagnostics for workspace probing/fallback, but the high-level launch summary remains unchanged.

## 2026-03-18 - Archive previous task and narrow follow-up scope to remaining evidence gaps

Scope:
- Audited the current `MAIN_TASK.md` against the implemented launcher code, tests, docs, staged git changes, and recent git history.
- Archived the original task into `OLD_TASK_1.md` and replaced `MAIN_TASK.md` with a follow-up task that contains only the remaining actionable scope.

Key behavior changes:
- No runtime behavior changed in this audit/rewrite step.
- The new `MAIN_TASK.md` is now focused only on:
  - adding focused observability assertions for the new launcher events and payloads
  - performing and recording live cmux verification for the default created-workspace path, explicit named-workspace creation path, and existing-workspace rerun path
- The archived task remains preserved verbatim in `OLD_TASK_1.md`.

Files / modules touched:
- `OLD_TASK_1.md`
- `MAIN_TASK.md`
- `docs/changelog/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create-1_changelog.md`

Tests run + results:
- No automated tests were run in this audit-only task archival/rewrite step.

Config / env / migrations:
- No config changes.
- No migrations.

Risks / notes:
- The narrowed follow-up task assumes the code-level starter-surface reuse implementation is already present and that the remaining closure work is limited to observability coverage plus live cmux verification evidence.
- `git status --short`, `git diff --name-status`, `git diff --cached --name-status`, `git log --oneline --decorate -n 30`, and path-specific `git log`/file inspection were used as the authoritative audit inputs for the rewritten task.

## 2026-03-18 - Close observability coverage and record live cmux verification

Scope:
- Added focused regression coverage for the new plan-agent launcher observability events and payload contracts.
- Performed live cmux verification against the real `./bin/envctl` entrypoint for the created-workspace default path, explicit missing named-workspace path, and rerun into an existing workspace.
- Recorded exact scenario evidence and local prerequisites required to reproduce the verification on this repo.

Key behavior changes:
- No additional launcher runtime changes were required after the new tests and live verification; the existing starter-surface reuse and fallback behavior matched the expected contract.
- `tests/python/planning/test_plan_agent_launch_support.py` now locks the bounded payloads for:
  - `planning.agent_launch.workspace_surface_probe`
  - `planning.agent_launch.surface_fallback`
  - `planning.agent_launch.surface_created` including `source`
- Verified with real cmux that a newly created implementation workspace now reuses its starter surface instead of leaving behind a redundant extra tab, while reruns into an existing workspace still create exactly one new launch surface.

Files / modules touched:
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed (`Ran 30 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed (`Ran 55 tests`, `OK`)

Live verification commands + results:
- Repo-local wrapper prerequisite:
  - `cd /Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create/1 && python3.12 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -e '.[dev]'`
  - Reason: this repo's `./bin/envctl` wrapper resolves `python3` via `#!/usr/bin/env python3`, and the ambient interpreter in the cmux shell did not have required packages such as `rich`.
- Default missing-workspace interactive verification:
  - Command:
    - `cd /Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create/1 && PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create/1/.venv/bin:$PATH RUN_SH_RUNTIME_DIR=/tmp/envctl-live-default-interactive-20260318 TREES_STARTUP_ENABLE=false CMUX=true ./bin/envctl --plan refactoring/envctl-python-engine-full-gap-closure-plan`
  - Caller workspace: `workspace:13` titled `envctl-live-default-interactive-20260318`
  - Created target workspace: `workspace:14` titled `envctl-live-default-interactive-20260318 implementation`
  - Result:
    - `cmux list-pane-surfaces --workspace workspace:14` returned exactly one surface: `surface:33  refactoring_gap_closure_plan-1`
    - `cmux tree --workspace workspace:14` showed exactly one surface in the target workspace
    - `cmux read-screen --workspace workspace:14 --surface surface:33 --lines 120` showed the Codex session and `MAIN_TASK.md` content, proving the reused starter surface became the real launched plan-agent tab
- Existing-workspace rerun interactive verification:
  - Command:
    - `cd /Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create/1 && PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create/1/.venv/bin:$PATH RUN_SH_RUNTIME_DIR=/tmp/envctl-live-default-interactive-rerun-20260318 TREES_STARTUP_ENABLE=false CMUX=true ./bin/envctl --plan refactoring/envctl-python-engine-main-task-execution-plan`
  - Target workspace reused: `workspace:14`
  - Result:
    - `cmux list-pane-surfaces --workspace workspace:14` returned exactly two real surfaces after the rerun:
      - `surface:33  refactoring_gap_closure_plan-1`
      - `surface:34  refactoring_task_execution_plan-1`
    - `cmux tree --workspace workspace:14` confirmed no workspace recreation and exactly one newly added launch surface
- Explicit missing named-workspace interactive verification:
  - Command:
    - `cd /Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create/1 && PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create/1/.venv/bin:$PATH RUN_SH_RUNTIME_DIR=/tmp/envctl-live-explicit-interactive-20260318 TREES_STARTUP_ENABLE=false ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl-live-explicit-interactive-20260318 ./bin/envctl --plan refactoring/envctl-python-engine-ideal-state-finalization-plan`
  - Caller workspace: `workspace:15` titled `envctl-live-explicit-caller-20260318`
  - Created explicit target workspace: `workspace:16` titled `envctl-live-explicit-interactive-20260318`
  - Result:
    - `cmux list-pane-surfaces --workspace workspace:16` returned exactly one surface: `surface:36  refactoring_finalization_plan-1`
    - `cmux tree --workspace workspace:16` showed exactly one surface in the created workspace
    - `cmux read-screen --workspace workspace:16 --surface surface:36 --lines 120` showed the worktree `cd`, the `codex` launch, the Codex banner, and `MAIN_TASK.md`, proving the created named workspace also reused the starter surface instead of keeping a duplicate tab

Config / env / migrations:
- No new config keys or migrations.
- Live verification used `TREES_STARTUP_ENABLE=false` intentionally on this repo because the normal service startup path exits quickly due to the current missing startup command configuration; disabling startup kept `envctl` alive long enough for the background plan-agent bootstrap to finish in a real cmux session.

Risks / notes:
- Batch-mode runs in this repo were sufficient to confirm surface-count behavior, but interactive verification provided the reliable proof that the real launched tab completed bootstrap before the process exited.
- The live verification created additional worktrees under `trees/` for the exercised plans; that is expected for this task because the verification had to run the real `--plan` workflow end to end.

## 2026-03-19 - Harden starter-surface parsing against duplicate and invalid refs

Scope:
- Tightened the cmux starter-surface parser used by the newly created workspace probe.
- Added focused regression tests for duplicate surface refs and malformed `surface:` tokens so the launcher keeps reusing the starter surface when cmux output repeats the same handle.

Key behavior changes:
- `_surface_ids_from_list_output(...)` now accepts only numeric cmux surface handles that match `surface:<digits>`.
- The parser now de-duplicates repeated surface refs while preserving encounter order, preventing a false `ambiguous` probe result when `cmux list-pane-surfaces` echoes the same surface more than once.
- Starter-surface reuse remains conservative: only one unique valid surface ref results in reuse; anything else still falls back safely to `cmux new-surface`.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/broken_envctl_plan_agent_duplicate_starter_surface_on_workspace_create-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_surface_ids_parser_dedupes_repeated_surface_refs tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_surface_ids_parser_ignores_non_numeric_surface_tokens` -> passed (`Ran 2 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed (`Ran 41 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed (`Ran 58 tests`, `OK`)

Config / env / migrations:
- No config or env contract changes.
- No migrations.

Risks / notes:
- This hardening assumes valid cmux surface refs continue to use the existing numeric `surface:<n>` format described by current repo evidence and tests.
- The parser intentionally preserves first-seen order after de-duplication so downstream behavior stays stable if later code reuses the first detected starter surface.
