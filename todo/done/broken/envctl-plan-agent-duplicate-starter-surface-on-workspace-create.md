# Envctl Plan-Agent Duplicate Starter Surface On Workspace Create Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Eliminate the redundant cmux starter tab/surface that appears when `envctl --plan` creates a new target workspace such as `"<current workspace> implementation"`.
  - Preserve the current successful launch flow for the real plan-agent surface: rename tab, respawn shell, `cd` into the worktree, launch the configured AI CLI, and send the configured preset.
  - Keep existing behavior unchanged when envctl launches into an already-existing workspace or an explicitly targeted workspace handle that does not require workspace creation.
  - Make the fix robust against cmux variations by reusing the starter surface only when envctl can identify it unambiguously.
- Non-goals:
  - Changing workspace naming rules such as the default `"<current workspace> implementation"` target.
  - Redesigning the prompt submission/bootstrap sequence for Codex or OpenCode beyond the surface-selection issue.
  - Changing worktree deletion/cleanup behavior in this slice.
  - Adding a new top-level CLI flag or config key for “reuse starter surface.”
- Assumptions:
  - In the cmux version currently used on this machine, `cmux new-workspace` creates an initial starter surface automatically.
  - Read-only live evidence supports that assumption: `cmux tree --workspace workspace:4` showed one pane with two surfaces under `envctl implementation`, one starter surface titled `…/projects/current/envctl` and one launched worktree surface titled `features_review_preset-1`.
  - `cmux list-pane-surfaces --workspace <workspace-ref>` is a stable enough probe for counting starter surfaces immediately after workspace creation, but the implementation should retain a safe fallback when that probe is empty or ambiguous.

## Goal (user experience)
When the operator runs `CMUX=true ./bin/envctl --plan` and envctl has to create the default implementation workspace first, the new workspace should end up with only the real launched plan-agent tab. The operator should not see a second, redundant starter tab that was created implicitly by cmux during workspace creation. Re-running `--plan` against an already existing implementation workspace should continue to open only the new real launched tab as it does today.

## Business logic and data model mapping
- Primary launch orchestration:
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:launch_plan_agent_terminals`
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:_launch_single_worktree`
- Surface creation and bootstrap:
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:_create_surface`
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:_start_background_surface_bootstrap`
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:_run_surface_bootstrap`
- Workspace resolution and creation:
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:_ensure_workspace_id`
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:_default_workspace_target`
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:_ensure_configured_workspace_id`
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:_create_named_workspace`
- Existing launch data structures that may need to carry more metadata:
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:PlanAgentLaunchConfig`
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:PlanAgentLaunchOutcome`
  - `/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py:PlanAgentLaunchResult`
- Current regression coverage that codifies the existing sequence:
  - `/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py:test_enabled_feature_defaults_to_created_implementation_workspace`
  - `/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py:test_cmux_alias_enables_default_implementation_workspace_launch`
  - `/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py:test_missing_named_workspace_is_created_before_surface_launch`
- User-visible documentation that describes the current behavior:
  - `/Users/kfiramar/projects/current/envctl/docs/reference/configuration.md`
  - `/Users/kfiramar/projects/current/envctl/docs/reference/commands.md`
  - `/Users/kfiramar/projects/current/envctl/docs/user/planning-and-worktrees.md`

## Current behavior (verified in code)
- The launch flow always creates an explicit surface for each created worktree:
  - `launch_plan_agent_terminals(...)` loops over `created_worktrees` and calls `_launch_single_worktree(...)`.
  - `_launch_single_worktree(...)` immediately calls `_create_surface(...)`.
  - `_create_surface(...)` runs `["cmux", "new-surface", "--workspace", workspace_id]`.
- The default implementation workspace is created on demand when it does not already exist:
  - `_ensure_workspace_id(...)` resolves the default `"<current workspace> implementation"` title via `_default_workspace_target(...)`.
  - If no workspace ref exists yet, `_ensure_workspace_id(...)` calls `_create_named_workspace(...)`.
  - `_create_named_workspace(...)` runs `["cmux", "new-workspace", "--cwd", str(runtime.config.base_dir)]`, then `current-workspace` if needed, then `rename-workspace`.
- There is no branch that reuses a surface from a just-created workspace:
  - `_create_named_workspace(...)` returns only `(workspace_ref, error)`.
  - `_launch_single_worktree(...)` only receives a `workspace_id`, not any “starter surface” metadata.
  - Because of that, workspace creation and surface creation are fully separate steps.
- Existing unit tests explicitly assert the current duplicate-producing sequence:
  - `test_enabled_feature_defaults_to_created_implementation_workspace` expects:
    - `cmux list-workspaces`
    - `cmux new-workspace --cwd ...`
    - `cmux current-workspace`
    - `cmux rename-workspace --workspace workspace:9 "envctl implementation"`
    - `cmux new-surface --workspace workspace:9`
  - `test_missing_named_workspace_is_created_before_surface_launch` asserts the same pattern for an explicit missing workspace title.
- Docs describe the same two-step model at a user level:
  - `docs/user/planning-and-worktrees.md` says “when a named target workspace does not exist yet, envctl creates it and then launches the new plan-agent surfaces there.”
  - `docs/reference/commands.md` and `docs/reference/configuration.md` likewise describe create-then-launch behavior.
- Read-only live cmux evidence matches the user report:
  - `cmux list-workspaces` showed `workspace:4  envctl implementation`.
  - `cmux tree --workspace workspace:4` showed one pane with two surfaces:
    - `surface:20 [terminal] "…/projects/current/envctl"`
    - `surface:21 [terminal] "features_review_preset-1" [selected]`
  - That is consistent with cmux auto-creating a starter surface on workspace creation and envctl then creating a second explicit launch surface.

## Root cause(s) / gaps
- Envctl models workspace creation and surface creation as independent steps, but cmux already creates an initial surface during `new-workspace` in the observed environment.
- `_create_named_workspace(...)` throws away any chance to reuse the starter surface because it returns only a workspace ref, not a richer workspace-creation result.
- `_launch_single_worktree(...)` has no ability to distinguish:
  - “workspace already existed, create a new launch surface”
  - from
  - “workspace was just created and already has a starter surface that can be reused”
- There is no helper to inspect a newly created workspace and identify its starter surface in a bounded, deterministic way.
- Current tests lock in the bug by asserting `new-workspace` followed by `new-surface` on the newly created workspace paths.
- Current events and summary output only count envctl’s explicit launched surfaces, so the redundant starter surface is invisible to runtime diagnostics.

## Plan
### 1) Introduce an explicit workspace-resolution result instead of passing only a workspace id
- Replace the plain `str | None` workspace return path with a small internal dataclass or tuple that carries:
  - `workspace_id`
  - `created` boolean
  - optional `starter_surface_id`
- Thread that richer result through:
  - `_ensure_workspace_id(...)`
  - `_ensure_configured_workspace_id(...)`
  - `_create_named_workspace(...)`
  - `launch_plan_agent_terminals(...)` / `_launch_single_worktree(...)`
- Keep the public `PlanAgentLaunchResult` / `PlanAgentLaunchOutcome` contract stable unless implementation evidence shows an extra field is necessary.

### 2) Probe newly created workspaces for a single starter surface
- Add a helper in `plan_agent_launch_support.py`, for example:
  - `_list_workspace_surfaces(runtime, workspace_id)`
  - `_starter_surface_for_new_workspace(runtime, workspace_id)`
- Use cmux commands that are already supported by the current CLI:
  - prefer `cmux list-pane-surfaces --workspace <workspace-ref>`
  - parse `surface:<n>` refs from that output
- Reuse the starter surface only when the signal is unambiguous:
  - exactly one surface exists in the newly created workspace immediately after `new-workspace`
  - the command succeeds
- If the probe fails, returns zero surfaces, or returns multiple surfaces, treat the result as ambiguous and fall back safely to the current explicit `new-surface` path.

### 3) Reuse the starter surface when a workspace was created in the same launch flow
- Update `_launch_single_worktree(...)` so it accepts an optional pre-existing surface id from the workspace-resolution result.
- If a starter surface id is present:
  - skip `_create_surface(...)`
  - treat the starter surface as the launch surface
  - emit the same `planning.agent_launch.surface_created`-equivalent event or a more explicit event that preserves downstream diagnostics
- Continue to run the normal bootstrap sequence on that reused surface:
  - `rename-tab`
  - `respawn-pane`
  - `cd <worktree>`
  - AI CLI launch
  - prompt submission
- Preserve the current behavior for existing workspaces:
  - if envctl resolved an already-existing workspace by title or handle, still call `new-surface`
  - only the “workspace created during this launch” path should attempt reuse

### 4) Add a bounded fallback path instead of assuming starter-surface reuse is always possible
- If a newly created workspace cannot be probed reliably, keep the current launch behavior as the safe fallback:
  - create an explicit new surface
  - do not block or fail the plan-agent launch just because starter-surface reuse was ambiguous
- Emit bounded diagnostics when fallback happens, for example:
  - workspace created
  - starter surface probe result (`none`, `ambiguous`, `probe_failed`)
  - explicit `new-surface` fallback used
- This makes the fix safe across cmux versions where starter-surface enumeration might differ.

### 5) Update tests to flip the expectation from “create then new-surface” to “reuse when created”
- Extend `/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py` with focused cases:
  - default implementation workspace created on demand, starter surface detected, `new-surface` not called
  - explicit missing named workspace created on demand, starter surface detected, `new-surface` not called
  - ambiguous starter probe falls back to `new-surface`
  - existing workspace resolution still uses `new-surface`
- Update the existing tests that currently assert:
  - `new-workspace`
  - `current-workspace`
  - `rename-workspace`
  - `new-surface`
  so they instead assert:
  - `new-workspace`
  - optional `current-workspace`
  - `rename-workspace`
  - `list-pane-surfaces --workspace ...`
  - no `new-surface` when reuse is unambiguous
- Keep the bootstrap assertions identical for the reused starter surface:
  - `rename-tab`
  - `respawn-pane`
  - `send`
  - `send-key`
  - screen-readiness polling

### 6) Keep docs aligned with the corrected surface behavior
- Update the plan-agent launch docs to clarify the user-visible behavior:
  - when envctl creates a missing target workspace, it reuses the initial cmux starter surface for the launch when possible instead of opening a redundant extra tab
- Target docs:
  - `/Users/kfiramar/projects/current/envctl/docs/reference/configuration.md`
  - `/Users/kfiramar/projects/current/envctl/docs/reference/commands.md`
  - `/Users/kfiramar/projects/current/envctl/docs/user/planning-and-worktrees.md`
- The docs should describe the user-facing result, not the internal probe/fallback details, except for a short note if fallback leaves behavior unchanged on unsupported cmux variants.

## Tests (add these)
### Backend tests
- Extend `/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py`
  - `test_created_default_workspace_reuses_single_starter_surface`
  - `test_created_named_workspace_reuses_single_starter_surface`
  - `test_created_workspace_falls_back_to_new_surface_when_starter_probe_is_ambiguous`
  - `test_existing_workspace_still_creates_new_surface`
  - add parser coverage for any new helper that reads `list-pane-surfaces` output
- Extend `/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_command_parity.py`
  - only if needed to keep `--explain-startup` / launch-summary expectations aligned after event payload adjustments

### Frontend tests
- None.
  - This bug is in the backend cmux launcher/orchestration path, not in the dashboard/Textual UI layer.

### Integration/E2E tests
- Prefer a narrow manual or future smoke check rather than a broad E2E harness in this slice, because the behavior depends on the local cmux binary:
  - create a missing implementation workspace via `CMUX=true ./bin/envctl --plan`
  - verify the new workspace contains only one launch surface for the created worktree
  - verify rerunning into the now-existing workspace still behaves normally
- If the repo later adds cmux CLI smoke coverage, add one focused test for the “missing workspace -> one launched tab” case only.

## Observability / logging (if relevant)
- Add bounded launch diagnostics around the new reuse/fallback decision:
  - workspace created
  - starter surface detected / not detected / ambiguous
  - reused starter surface vs created explicit new surface
- Keep payloads bounded to refs/counts/reason strings, not full `cmux tree` output.
- Preserve the existing high-level launch summary text so operators still see `Plan agent launch opened N cmux surface(s).`
- Consider whether `planning.agent_launch.surface_created` should include a `source` field such as `starter_reused` or `new_surface`.

## Rollout / verification
- Implementation order:
  1. add surface-listing helper and parser tests
  2. change workspace-resolution return contract
  3. update launch path to reuse starter surfaces when unambiguous
  4. update docs
- Verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity`
- Manual verification:
  1. Ensure the target implementation workspace does not already exist.
  2. Run `CMUX=true ./bin/envctl --plan`.
  3. Confirm envctl still reports one launched surface.
  4. Run `cmux tree --workspace <workspace-ref>` and confirm only one surface exists for the created worktree launch, with no extra starter tab left behind.
  5. Repeat with `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=<new-title> ./bin/envctl --plan` for an explicit missing workspace title.
  6. Repeat when the workspace already exists and confirm envctl still opens one new real launch surface there.

## Definition of done
- When envctl creates a missing target workspace for plan-agent launch, it reuses the starter surface or otherwise avoids leaving a redundant extra starter tab behind.
- Existing-workspace launches continue to create one new explicit launch surface as before.
- Launcher tests cover both the reuse path and the safe fallback path.
- User-facing docs describe the corrected behavior for newly created workspaces.
- Manual verification against real cmux confirms the implementation workspace no longer ends up with both a starter surface and a launched worktree surface after a first-run `CMUX=true ./bin/envctl --plan`.

## Risk register (trade-offs or missing tests)
- `cmux new-workspace` starter-surface behavior may vary by cmux version.
  - Mitigation: reuse only when starter-surface detection is unambiguous and preserve a safe fallback.
- `list-pane-surfaces` output is another CLI contract envctl will need to parse.
  - Mitigation: keep the parser narrow, add focused parser tests, and avoid depending on labels beyond `surface:<n>` refs.
- If the starter surface is reused, bootstrap now mutates a surface that cmux created implicitly rather than one envctl created explicitly.
  - Mitigation: keep the same bootstrap contract (`rename-tab`, `respawn-pane`, launch commands) and validate it in existing launch-sequence tests.

## Open questions (only if unavoidable)
- None.
