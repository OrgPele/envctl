# Envctl Plan Cmux AI Terminal Launch

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Add an optional `--plan` workflow mode that, when enabled, opens one new `cmux` terminal surface for each newly created planning worktree.
  - In each launched surface, enter the created worktree, start the selected AI CLI (`codex` or `opencode`), and trigger the envctl-managed implementation command automatically.
  - Keep the feature bounded to envctl-managed planning/worktree flows rather than ad hoc terminal automation scattered across startup code.
  - Preserve current `--plan` behavior exactly when the feature is disabled or when no new worktrees are created.
- Non-goals:
  - Changing normal service startup, dashboard, resume, or runtime-state semantics beyond emitting bounded launch diagnostics.
  - Auto-launching AI terminals for existing worktrees on every `--plan` rerun in the first iteration.
  - Extending the feature to `--setup-worktrees`, `--setup-worktree`, direct `resume`, `restart`, or `--planning-prs` in the first iteration.
  - Implementing generic editor/window-management integration beyond `cmux`.
- Assumptions:
  - The intended target is the caller’s current `cmux` workspace/window, not arbitrary detached workspaces elsewhere on the machine.
  - The right first trigger set is “newly created planning worktrees during this `--plan` sync”, because rerunning `--plan` against already-existing worktrees should not silently duplicate tabs/surfaces.
  - The AI command should be envctl-owned rather than depending on a user’s undocumented local alias; repo evidence currently exposes `implement_task`, not `implement_plan`, so the feature must define a canonical preset/command contract explicitly.
  - `cmux` command capabilities are available externally and include `new-surface`, `respawn-pane`, `send`, `send-key`, `rename-tab`, and caller-scoped environment variables such as `CMUX_WORKSPACE_ID` / `CMUX_SURFACE_ID` (`cmux --help`).

## Goal (user experience)
When the operator runs `envctl --plan` with the feature enabled and envctl creates new worktrees, envctl should also open matching `cmux` terminal surfaces in the current workspace, one per new worktree. Each new surface should remain a normal interactive shell tab: envctl should rename it, type `cd <worktree>`, type the configured AI CLI (`codex` or `opencode`), then type the envctl implementation slash command, leaving the session interactive so the operator can continue working in that same tab when the agent finishes. If the feature is disabled, prerequisites are missing, or no new worktrees were created, `--plan` should keep its current behavior and print/emit a clear skip reason instead of partially launching terminals.

## Business logic and data model mapping
- `--plan` route parsing and command ownership:
  - `python/envctl_engine/runtime/command_router.py:parse_route`
  - `python/envctl_engine/runtime/command_router.py:_phase_resolve_command_mode`
  - `python/envctl_engine/runtime/command_router.py:_phase_bind_flags`
- Startup orchestration and current planning entrypoint:
  - `python/envctl_engine/startup/startup_orchestrator.py:StartupOrchestrator.execute`
  - `python/envctl_engine/startup/startup_orchestrator.py:_select_contexts`
  - `python/envctl_engine/runtime/engine_runtime.py:_select_plan_projects`
- Planning/worktree creation and `MAIN_TASK.md` seeding:
  - `python/envctl_engine/planning/worktree_domain.py:_select_plan_projects`
  - `python/envctl_engine/planning/worktree_domain.py:_sync_plan_worktrees_from_plan_counts`
  - `python/envctl_engine/planning/worktree_domain.py:_sync_single_plan_worktree_target`
  - `python/envctl_engine/planning/worktree_domain.py:_create_feature_worktrees`
  - `python/envctl_engine/planning/worktree_domain.py:_seed_main_task_from_plan`
  - `python/envctl_engine/planning/__init__.py:planning_feature_name`
  - `python/envctl_engine/planning/__init__.py:select_projects_for_plan_files`
- Runtime/config/process helpers that would own the new integration:
  - `python/envctl_engine/config/__init__.py:EngineConfig`
  - `python/envctl_engine/runtime/cli.py:check_prereqs`
  - `python/envctl_engine/runtime/engine_runtime_commands.py:split_command`
  - `python/envctl_engine/runtime/engine_runtime_commands.py:command_exists`
  - `python/envctl_engine/shared/process_runner.py:ProcessRunner.run`
- AI prompt preset ownership:
  - `python/envctl_engine/runtime/prompt_install_support.py:run_install_prompts_command`
  - `python/envctl_engine/runtime/prompt_install_support.py:_available_presets`
  - `python/envctl_engine/runtime/prompt_templates/implement_task.md`
  - `python/envctl_engine/runtime/prompt_templates/create_plan.md`
- Relevant docs/tests:
  - `docs/user/planning-and-worktrees.md`
  - `docs/user/ai-playbooks.md`
  - `docs/reference/commands.md`
  - `tests/python/planning/test_planning_worktree_setup.py`
  - `tests/python/runtime/test_engine_runtime_real_startup.py`
  - `tests/python/runtime/test_prompt_install_support.py`
  - `tests/python/runtime/test_prereq_policy.py`
  - `tests/python/startup/test_startup_orchestrator_flow.py`

## Current behavior (verified in code)
- `plan` is a normal startup route that resolves through planning/worktree selection before any startup/resume logic:
  - `StartupOrchestrator.execute(...)` runs `_select_contexts(...)`, then disabled-startup/auto-resume/startup phases.
  - `_select_contexts(...)` calls `rt._select_plan_projects(route, project_contexts)` when `route.command == "plan"`.
- Planning selection can create/delete worktrees and seed `MAIN_TASK.md`, but it does not surface a structured “created worktrees” result today:
  - `_select_plan_projects(...)` resolves plan counts and calls `_sync_plan_worktrees_from_plan_counts(...)`.
  - `_sync_single_plan_worktree_target(...)` calls `_create_feature_worktrees(...)` when desired count exceeds existing count.
  - `_create_feature_worktrees(...)` creates git worktrees, writes provenance, and calls `_seed_main_task_from_plan(...)`, but returns only `str | None` for error and discards the created targets once finished.
- Worktree creation is currently file/system oriented only:
  - New plan-created worktrees get `MAIN_TASK.md` copied from the selected plan file.
  - No code in `planning/`, `startup/`, or runtime dispatch launches user terminals, editors, `cmux`, `codex`, or `opencode`.
- Installed AI prompt support is currently file installation only:
  - `run_install_prompts_command(...)` writes prompt files to user-local CLI directories.
  - Built-in preset registry currently includes `implement_task`, `review_task_imp`, `continue_task`, `merge_trees_into_dev`, and `create_plan`.
  - Default preset is `_DEFAULT_PRESET = "implement_task"`.
- The repo does not currently expose the user-mentioned `implement_plan` preset/command:
  - `docs/user/ai-playbooks.md`, `docs/reference/commands.md`, and `tests/python/runtime/test_prompt_install_support.py` all lock in `implement_task` and `create_plan`, not `implement_plan`.
- Config and prereq surfaces do not currently know about this feature:
  - `EngineConfig` has planning path/root settings (`ENVCTL_PLANNING_DIR`, `TREES_DIR_NAME`) but nothing for `cmux`, AI CLI selection, or automated post-plan launch.
  - `check_prereqs(...)` only checks for `git`, conditional `docker`, conditional `lsof`, and the Python `rich` module.
- `--planning-prs` is already a plan-adjacent special flow that intentionally skips startup after acting on the selected plan contexts:
  - `StartupOrchestrator._resolve_auto_resume(...)` branches on `route.flags["planning_prs"]` and runs PR actions instead of normal startup.
  - That makes `--planning-prs` a separate behavior surface that should not implicitly inherit terminal-launch side effects in the first change.

## Root cause(s) / gaps
- The planning layer does not currently preserve enough structured information about newly created worktrees to support a clean post-create launch hook.
- There is no isolated module that owns “launch external agent terminals for new plan worktrees”; adding shell/`cmux` calls directly inside low-level worktree helpers would make planning logic harder to test and reason about.
- The runtime/config layer has no opt-in settings for:
  - feature enablement
  - AI CLI choice
  - preset/command name
  - launch shell/command override
  - failure policy when `cmux` or the AI CLI is unavailable
- The prompt installer contract and the requested `/implement_plan` command name do not currently align.
- Tests currently verify worktree creation, plan sync, and prompt installation independently, but there is no coverage for a combined “new worktree -> AI surface launched” flow.

## Plan
### 1) Define a narrow first-version feature contract
- Scope the feature to `route.command == "plan"` only, and only when the route is using the normal planning/worktree-selection flow rather than `route.flags["planning_prs"]`.
- Trigger launches only for worktrees created during the current planning reconciliation, not all selected contexts and not all pre-existing trees.
- Default behavior when disabled must remain exactly as it is today: no extra prerequisites, no terminal launch, no new output beyond existing planning/startup messaging.
- First-version failure policy should be explicit:
  - if the feature is disabled: do nothing
  - if enabled but no new worktrees were created: do nothing and emit a skip event
  - if enabled but envctl is not running inside `cmux` and no explicit workspace target is configured: skip/fail with a clear message
  - if enabled but `cmux` or the selected AI CLI executable is missing: stop before launch side effects and report the missing executable(s)
- Document this as a local interactive productivity feature, not a headless/CI workflow primitive.

### 2) Add explicit config/env ownership for plan terminal launch
- Extend `python/envctl_engine/config/__init__.py` defaults and `EngineConfig` to carry a small, explicit feature surface. Recommended first-version keys:
  - `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=false`
  - `ENVCTL_PLAN_AGENT_CLI=codex`
  - `ENVCTL_PLAN_AGENT_PRESET=implement_plan`
  - `ENVCTL_PLAN_AGENT_SHELL=zsh`
  - `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=true`
  - optional advanced override: `ENVCTL_PLAN_AGENT_CLI_CMD=` for custom executable/path
- Keep the feature config-driven rather than adding new CLI parser flags in the first iteration; the user asked for an optional feature “when set to on”, and config/env keeps the route surface smaller.
- Reuse the normal config precedence rules already implemented in `load_config(...)` so `.envctl`, environment overrides, `show-config`, and tests remain consistent.
- Add docs for the new keys to the relevant user/reference surfaces once implementation exists.

### 3) Introduce a structured planning sync result that preserves newly created worktrees
- Refactor the current tuple/string return flow around `_sync_plan_worktrees_from_plan_counts(...)` and `_create_feature_worktrees(...)` so planning code can return structured metadata instead of only `projects, error`.
- Recommended shape:
  - a small dataclass such as `PlanWorktreeSyncResult` or `PlanSelectionResult`
  - fields for:
    - `raw_projects`
    - `selected_contexts`
    - `created_worktrees` (name/root/plan file)
    - `removed_worktrees`
    - `archived_plan_files`
    - `error`
- `_create_feature_worktrees(...)` should return the actual created targets for this sync pass, not just success/failure.
- `_select_plan_projects(...)` should become the place that aggregates:
  - selected plan contexts
  - created worktrees
  - any sync error
- This keeps low-level worktree creation pure and gives startup/orchestration layers a reliable handoff point for launching terminals after successful planning sync.

### 4) Add a dedicated plan-agent launch support module
- Introduce a focused support/orchestrator module, for example:
  - `python/envctl_engine/planning/plan_agent_launch_support.py`
  - or `python/envctl_engine/planning/cmux_agent_launch.py`
- This module should own:
  - config resolution for the feature
  - prerequisite validation for `cmux` + selected AI CLI
  - `cmux` workspace/surface targeting
  - AI CLI launch command construction
  - command/preset injection after the CLI starts
  - bounded event emission / user-facing skip reasons
- Keep `worktree_domain.py` free of raw `cmux` command composition beyond calling this helper with a structured list of created worktrees.
- Use existing helpers/patterns where possible:
  - `command_exists(...)` for executable detection
  - `ProcessRunner.run(...)` for shelling out
  - `_command_env(...)` for consistent env propagation where appropriate

### 5) Standardize the envctl-owned AI command contract
- Resolve the mismatch between the requested `/implement_plan` name and the repo’s current `implement_task` preset before wiring automated launch behavior.
- Recommended first-version contract:
  - add a new prompt template alias `python/envctl_engine/runtime/prompt_templates/implement_plan.md`
  - keep `implement_task.md` for backward compatibility
  - make the new feature default to `/implement_plan`
  - allow `ENVCTL_PLAN_AGENT_PRESET` to override this when needed
- Update `prompt_install_support.py`, docs, and tests so `install-prompts --preset all` installs the new alias too.
- If implementation decides not to add an alias, then the feature must default to `/implement_task` and document that explicitly; do not silently assume `/implement_plan` already exists because repo evidence says it does not.

### 6) Define the `cmux` launch choreography explicitly and isolate quoting/ordering
- The launch helper should follow a deterministic sequence per created worktree:
  1. identify the target `cmux` workspace/pane from caller context (prefer `CMUX_WORKSPACE_ID` / `CMUX_SURFACE_ID`; avoid global workspace scanning in v1)
  2. create a new terminal surface in that workspace/window and leave it as a normal shell surface
  3. rename the new tab/surface to the worktree/project name for operator clarity
  4. type `cd <worktree-root>` into the shell and press Enter
  5. type the selected AI CLI executable (`codex` or `opencode`) into the shell and press Enter
  6. after the AI CLI is visibly active, type the slash command text (for example `/implement_plan`) and press Enter
- Keep command/text composition centralized and quoted safely; avoid ad hoc string concatenation in multiple files.
- Do not use a headless or one-shot shell command such as `zsh -lc 'cd ... && codex ...'` as the primary workflow. The feature should drive a live shell surface by typing into it so the operator can keep using that same terminal session afterward.
- Use `cmux send` + `cmux send-key Enter` for each typed step (`cd`, CLI launch, slash command`) rather than hiding those steps inside an initial pane bootstrap command.
- Add a short bounded wait/retry strategy between:
  - surface creation and the first typed shell command
  - AI CLI launch and slash-command send
  so envctl does not type ahead of the actual interactive process state.
- Keep all `cmux` command sequencing in one helper so later timing adjustments do not touch planning logic.

### 7) Hook terminal launch after successful planning sync, not deep inside creation loops
- Do not launch terminals directly from `_create_feature_worktrees(...)`; that function currently runs inside per-plan reconciliation and would create partial side effects before the overall selection result is known.
- Preferred orchestration point:
  - after `_select_plan_projects(...)` has finished syncing and resolved the selected contexts
  - before startup continues into disabled-startup / auto-resume / service launch
- Concretely, this likely means either:
  - extending `StartupOrchestrator._select_contexts(...)` to receive a structured planning-selection result and invoke the launch helper there, or
  - adding a thin post-selection planning hook in the planning orchestrator that runs once per command after sync succeeds
- This ordering preserves a clean contract:
  - plan selection/sync succeeds first
  - new worktree launch side effects happen once
  - normal startup logic continues unchanged afterward

### 8) Keep runtime-state persistence and diagnostics bounded
- Do not persist raw `cmux` surface IDs or shell commands into run state; they are UI/session-ephemeral and not part of envctl’s durable environment truth.
- Instead, emit bounded events such as:
  - `planning.agent_launch.evaluate`
  - `planning.agent_launch.skipped`
  - `planning.agent_launch.surface_created`
  - `planning.agent_launch.command_sent`
  - `planning.agent_launch.failed`
- Event payloads should include:
  - feature enabled/disabled
  - selected AI CLI
  - created worktree count
  - launched worktree names
  - skip/failure reason
- If a small persisted summary is helpful, keep it to counts/reasons in `RunState.metadata` only; do not serialize live `cmux` refs or full shell commands.

### 9) Extend prereq/inspection/doc surfaces only when the feature is enabled
- Keep `check_prereqs(...)` unchanged for the default-off path so ordinary `plan` users do not suddenly require `cmux`, `codex`, or `opencode`.
- Add a feature-aware prereq branch that activates only when `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` resolves true and the route is `plan`.
- Update `show-config`/docs so operators can see the effective feature settings.
- Update user docs:
  - `docs/user/planning-and-worktrees.md` for the new optional post-plan launch behavior
  - `docs/user/ai-playbooks.md` for the new recommended multi-worktree AI flow
  - `docs/reference/commands.md` for config/preset naming and installation expectations
- If `explain-startup --json` currently owns all pre-start explanation surfaces for `plan`, add a bounded note there so operators can see whether post-plan AI terminal launch will run or be skipped.

### 10) Preserve clear first-version safety boundaries
- First implementation should skip launch entirely for:
  - `--planning-prs`
  - no newly created worktrees
  - missing `cmux` caller context when strict context is required
  - missing AI CLI executable
  - planning sync failures
- Do not let a partial launch continue silently after one worktree succeeds and another fails; the helper should return per-worktree outcomes and print/emit a clear summary.
- Keep launch failures separate from worktree creation failures:
  - failed worktree creation should behave exactly as today
  - successful worktree creation plus failed terminal launch should preserve the new worktree and report the launch error cleanly

## Tests (add these)
### Backend tests
- Extend `tests/python/planning/test_planning_worktree_setup.py`:
  - `_create_feature_worktrees(...)` or the new sync result captures created worktree roots/names explicitly
  - plan sync with mixed existing/new targets reports only the newly created worktrees as launch candidates
  - launch hook is not invoked when sync fails
  - `MAIN_TASK.md` seeding still happens before launch candidates are returned
- Add a focused unit test module for the new launch helper, for example `tests/python/planning/test_plan_agent_launch_support.py`:
  - disabled feature -> skip result
  - enabled feature with no created worktrees -> skip result
  - missing `cmux` -> failure/skip reason
  - missing selected AI CLI executable -> failure/skip reason
  - command composition for `codex` and `opencode`
  - `cmux` command sequencing uses `new-surface`, rename, `send`, and `send-key` in the expected order for `cd`, CLI launch, and slash-command typing
  - workspace context resolution prefers caller env (`CMUX_WORKSPACE_ID`, `CMUX_SURFACE_ID`)
- Extend `tests/python/runtime/test_prereq_policy.py`:
  - ordinary `plan` still does not require `cmux` or AI CLIs when feature is disabled
  - enabled plan-agent mode fails prereq validation cleanly when `cmux` or selected AI CLI is missing

### Frontend tests
- Extend `tests/python/runtime/test_prompt_install_support.py`:
  - new alias preset `implement_plan` is discovered and installed if that design is chosen
  - generated output/docs remain ordered and deterministic for `--preset all`
- Extend `tests/python/runtime/test_engine_runtime_command_parity.py` only if `explain-startup --json` or command-surface inspection changes:
  - plan-agent launch state/reason is surfaced consistently when enabled

### Integration/E2E tests
- Extend `tests/python/runtime/test_engine_runtime_real_startup.py`:
  - `--plan` with feature enabled and one newly created worktree invokes the launch helper exactly once for that new worktree
  - rerunning the same `--plan` with no new worktrees does not relaunch surfaces
  - mixed selection where one worktree already exists and one is newly created launches only the new one
  - `--planning-prs` does not invoke the launch helper
  - launch failure reports cleanly while preserving successful worktree creation
- Extend `tests/python/startup/test_startup_orchestrator_flow.py`:
  - planning-selection handoff into the new post-sync launch hook happens before normal startup continuation
  - disabled-startup planning mode still gets the same post-plan launch behavior when the feature is enabled, because the feature is about worktree creation rather than service startup

## Observability / logging (if relevant)
- Emit bounded events rather than raw shell/script output.
- Print one concise operator-facing summary after the launch phase, for example:
  - launched surfaces count
  - skipped count
  - failure count with short reason
- Avoid printing raw `cmux` command strings unless debug mode explicitly asks for them.
- If a readiness/inspection surface is updated, reuse the same reason vocabulary as runtime events to avoid drift.

## Rollout / verification
- Implement in this order:
  1. config/env surface plus structured planning sync result
  2. isolated `cmux`/AI launch helper with unit tests
  3. planning/startup orchestration hook
  4. prompt preset alias/contract resolution
  5. docs and inspection/prereq updates
- Verification commands for implementation phase:
  - `PYTHONPATH=python python3 -m unittest tests.python.planning.test_planning_worktree_setup`
  - `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prereq_policy`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prompt_install_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_orchestrator_flow`
- Manual verification targets:
  - inside an existing `cmux` workspace, run `envctl --plan <selection>` with the feature enabled and verify one new surface opens per newly created worktree
  - confirm each new surface stays a normal interactive shell tab, is renamed correctly, receives typed `cd <worktree>`, then typed `codex`/`opencode`, then typed `/implement_plan`
  - confirm the operator can continue using the same terminal session after the AI CLI finishes rather than landing in a closed or headless session
  - rerun the same `--plan` and confirm no duplicate surfaces are opened when no additional worktrees are created
  - disable the feature and confirm `--plan` behavior matches today exactly

## Definition of done
- `envctl --plan` can optionally launch `cmux` AI terminals for newly created worktrees when explicitly enabled.
- The launch logic is isolated in a dedicated helper/module rather than embedded in low-level worktree creation code.
- Worktree creation still seeds `MAIN_TASK.md`, writes provenance, and behaves as before when the feature is disabled.
- The feature has explicit prereq/config/docs coverage and does not affect default-off users.
- The canonical AI command contract (`implement_plan` alias or documented alternative) is explicit and tested.
- Automated tests cover planning sync metadata, launch helper behavior, prompt preset contract, and real startup handoff.

## Risk register (trade-offs or missing tests)
- Risk: `cmux` timing between CLI launch and slash-command send may be flaky across machines.
  - Mitigation: centralize the typed-input wait/send policy in one helper, use bounded retries, and keep targeted unit/integration coverage around command ordering.
- Risk: tying the feature to `CMUX_WORKSPACE_ID` / caller context may be too strict for some workflows.
  - Mitigation: start with caller-context targeting for safety; add explicit workspace overrides only if real usage proves necessary.
- Risk: adding an `implement_plan` alias changes the prompt installer contract and may surprise users who only know `implement_task`.
  - Mitigation: keep `implement_task` intact, add the alias as backward-compatible expansion, and document both names clearly.
- Risk: launch side effects could accidentally fire for existing worktrees if the planning sync summary is underspecified.
  - Mitigation: capture created worktrees explicitly in structured sync results and lock the behavior with tests.

## Open questions (only if unavoidable)
- None. Repo evidence is sufficient to write the implementation plan. The one contract mismatch (`implement_plan` vs `implement_task`) should be resolved as part of implementation rather than blocking the plan.
