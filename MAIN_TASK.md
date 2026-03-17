# Envctl Dynamic Run Reuse And Smart Resume Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Reuse an existing `run_id` when the user is reopening the same effective environment instead of always creating a fresh run.
  - Extend run reuse beyond current service-bearing auto-resume so identical dashboard-only tree sessions can also reopen the same run when safe.
  - Keep resume truth-driven: every reuse path must still reconcile runtime health before the dashboard is shown as current.
  - Prevent wrong-run reuse by matching on stronger identity than just project names.
- Non-goals:
  - Reusing `session_id`; session boundaries should stay fresh per CLI launch.
  - Reusing runs across different modes (`main` vs `trees`).
  - Reusing runs when configuration, selected roots, or startup profile changed materially.
  - Scanning historical `runs/*` to build a best-effort merged candidate.
- Assumptions:
  - The correct candidate for reuse remains the latest scoped state returned by `RuntimeStateRepository.load_latest(...)`, not arbitrary historical runs (`python/envctl_engine/state/repository.py:182`).
  - A reused run may be reopened by many sessions over time; `session_id` continues to provide per-launch diagnostic separation (`python/envctl_engine/runtime/engine_runtime_event_support.py:119`).
  - The current tree/dashboard user complaint is a concrete symptom of a broader run-reuse policy gap, not just a dashboard rendering bug.

## Goal (user experience)
When a user launches `envctl` into the same repo, mode, and selected tree set with effectively the same startup configuration, envctl should reopen the existing run instead of minting a redundant new one. The dashboard should feel continuous, existing test/action state should still be present because the same run was reused, and runtime truth should still be rechecked so stale processes are not silently trusted. When the environment is materially different, envctl should clearly fall back to a fresh run.

## Business logic and data model mapping
- Fresh startup and run creation:
  - `python/envctl_engine/startup/startup_orchestrator.py:_create_session`
  - `python/envctl_engine/runtime/engine_runtime_runtime_support.py:new_run_id`
  - `python/envctl_engine/startup/finalization.py:build_planning_dashboard_state`
  - `python/envctl_engine/startup/finalization.py:build_success_run_state`
  - `python/envctl_engine/startup/finalization.py:build_failure_run_state`
- Current auto-resume / run reuse decisions:
  - `python/envctl_engine/startup/startup_orchestrator.py:_resolve_auto_resume`
  - `python/envctl_engine/runtime/engine_runtime_startup_support.py:auto_resume_start_enabled`
  - `python/envctl_engine/runtime/engine_runtime_startup_support.py:load_auto_resume_state`
  - `python/envctl_engine/startup/startup_selection_support.py:state_matches_selected_projects`
  - `python/envctl_engine/startup/startup_selection_support.py:state_covers_selected_projects`
  - `python/envctl_engine/startup/startup_selection_support.py:state_project_names`
- Resume behavior:
  - `python/envctl_engine/startup/resume_orchestrator.py:execute`
  - `python/envctl_engine/startup/resume_restore_support.py:restore_missing`
- Startup-disabled dashboard behavior:
  - `python/envctl_engine/startup/startup_orchestrator.py:_resolve_disabled_startup_mode`
  - `python/envctl_engine/config/__init__.py:EngineConfig.startup_enabled_for_mode`
- Inspection and diagnostics that must stay aligned:
  - `python/envctl_engine/runtime/inspection_support.py:_print_startup_explanation`
  - `python/envctl_engine/debug/debug_bundle_diagnostics.py`
- State repository and latest-view persistence:
  - `python/envctl_engine/state/repository.py:save_run`
  - `python/envctl_engine/state/repository.py:save_resume_state`
  - `python/envctl_engine/runtime/engine_runtime_artifacts.py:write_artifacts`
- Relevant tests:
  - `tests/python/runtime/test_engine_runtime_startup_support.py`
  - `tests/python/runtime/test_engine_runtime_real_startup.py`
  - `tests/python/startup/test_startup_orchestrator_flow.py`
  - `tests/python/runtime/test_lifecycle_parity.py`
  - `tests/python/runtime/test_engine_runtime_command_parity.py`
  - `tests/python/debug/test_debug_bundle_generation.py`

## Current behavior (verified in code)
- Fresh startup always allocates a new run id before any reuse decision:
  - `StartupOrchestrator._create_session(...)` sets `session.run_id = rt._new_run_id()` and prints it immediately.
  - `new_run_id(...)` always generates a new `run-<timestamp>-<random>` value and binds it to debug mode.
- Current run reuse exists, but it is narrow:
  - `_resolve_auto_resume(...)` can convert startup into `resume` for exact project match and trees subset match.
  - `_resolve_auto_resume(...)` can also preserve an existing run for plan superset expansion by keeping prior services/requirements in memory and only starting new contexts.
- Current matching is project-name based, not root/config based:
  - `state_matches_selected_projects(...)` compares selected context names to project names derived from `state.services` and `state.requirements`.
  - `state_covers_selected_projects(...)` uses the same project-name-only model.
- Current auto-resume candidate loading is restricted to states with resumable services:
  - `load_auto_resume_state(...)` rejects states with `metadata["failed"]` and rejects any state where `state_has_resumable_services(...)` is false.
  - This means dashboard-only planning states written by disabled startup mode are never eligible for reuse.
- Disabled startup mode always creates a fresh planning/dashboard run:
  - `_resolve_disabled_startup_mode(...)` builds a new planning dashboard state and writes artifacts immediately.
  - This happens before `_resolve_auto_resume(...)` in the startup phase order.
- Resume itself is already health-aware:
  - `ResumeOrchestrator.execute(...)` loads the latest state, reconciles truth, optionally restores missing services, saves the reconciled state, and optionally enters the dashboard.
- Inspection/debug surfaces reflect the current narrow policy:
  - `inspection_support._print_startup_explanation(...)` only reports exact/subset auto-resume.
  - debug diagnostics aggregate `state.auto_resume.skipped` reasons such as `project_selection_mismatch`.

## Root cause(s) / gaps
- The existing architecture already supports same-run reuse, but only for startup paths backed by active services. That is too narrow for the actual operator mental model of “same environment reopened.”
- Run-reuse eligibility is based on project names alone, which is unsafe if different roots or changed worktrees happen to share the same display names.
- Startup-disabled dashboard sessions short-circuit into fresh run creation before the reuse logic ever runs.
- There is no persisted startup identity/fingerprint in `RunState.metadata` to answer “is this still the same effective environment?” without brittle heuristics.
- `explain-startup` and debug diagnostics reflect current behavior and would become misleading if reuse semantics changed without updating them.
- Because a new run is created before the reuse decision, startup UX and run-history semantics are biased toward run proliferation rather than continuity.

## Plan
### 1) Introduce a unified run-reuse eligibility model
- Add a dedicated support module, likely under `python/envctl_engine/startup/` or `python/envctl_engine/runtime/`, for example `run_reuse_support.py`.
- Replace the current split between:
  - candidate loading in `load_auto_resume_state(...)`
  - name-only project matching in `state_matches_selected_projects(...)`
  - ad hoc branch logic in `_resolve_auto_resume(...)`
- The new helper should return a structured decision object containing:
  - `candidate_state`
  - `decision_kind`
    - `resume_exact`
    - `resume_subset`
    - `reuse_expand`
    - `resume_dashboard_exact`
    - `fresh_run`
  - `reason`
  - `selected_projects`
  - `state_projects`
  - optional mismatch details
- Reuse should continue to be latest-state only and mode-scoped only.

### 2) Persist a stable environment identity in run metadata
- Extend startup/finalization state builders to persist reuse-relevant metadata on every new run:
  - normalized selected project roots
  - startup-enabled flag for the mode
  - effective service enablement for backend/frontend
  - effective dependency enablement for the mode
  - a computed startup identity fingerprint
- The fingerprint should be built from stable, operator-meaningful config and selection inputs, not ephemeral runtime truth:
  - mode
  - selected project names + normalized roots
  - startup enabled
  - backend/frontend enabled flags
  - dependency enablement for the mode
  - possibly directories relevant to runtime start behavior (`BACKEND_DIR`, `FRONTEND_DIR`)
- Keep the fingerprint payload explicit enough to debug in metadata, and add a condensed hash for cheap equality checks.

### 3) Tighten project matching from names to project identity
- Replace name-only reuse decisions with a stronger identity model:
  - project name
  - normalized root from `metadata["project_roots"]`
- Exact reuse:
  - selected project identities equal prior project identities
- Subset reuse:
  - selected project identities are a subset of prior identities
- Expand reuse:
  - prior project identities are a subset of selected identities
- If prior root data is missing in older states, allow a backward-compatible fallback to name-only matching but mark the decision as weaker and emit a diagnostic reason.

### 4) Expand candidate eligibility beyond “has running services”
- Split “can reuse this run” from “can resume application services from this run.”
- Add two candidate classes:
  - service-bearing states: current resume semantics with truth reconciliation and optional restore
  - dashboard-only states: latest state with no resumable services but valid dashboard/project metadata for the same identity
- This change should allow a disabled-startup tree dashboard to reopen the same run when:
  - mode matches
  - selected project identities match
  - startup profile fingerprint matches
  - prior state is not marked failed
- Keep rejecting failed or mode-mismatched candidates.

### 5) Reorder startup flow so reuse is evaluated before forced fresh planning runs
- Today `_resolve_disabled_startup_mode(...)` runs before `_resolve_auto_resume(...)`.
- Refactor the startup phase order so that after project selection, envctl evaluates run reuse before deciding to build a fresh planning/dashboard run.
- Recommended sequence:
  1. validate route
  2. handle restart pre-stop
  3. select contexts
  4. evaluate run reuse
  5. if reuse applies, route into resume/reopen behavior
  6. otherwise, handle disabled-startup fresh dashboard state or normal startup
- This is the key orchestration change needed for dashboard-only runs to stay on the same `run_id`.

### 6) Add a dashboard-resume path for startup-disabled modes
- Introduce a reuse path distinct from service resume for startup-disabled dashboards.
- For `resume_dashboard_exact`:
  - load the existing latest state
  - verify identity and startup fingerprint match
  - optionally refresh dashboard-owned metadata that is derived from current config, such as hidden commands or banner text
  - save via `save_resume_state(...)` to keep latest-view files current
  - enter the interactive dashboard or return batch success as appropriate
- Do not fabricate services or requirements in this path.
- Keep `run_id` unchanged and `session_id` fresh.

### 7) Keep truth checks mandatory for service-bearing reuse
- Preserve the current resume contract for `resume_exact` and `resume_subset`:
  - `ResumeOrchestrator.execute(...)` stays the path of record
  - reconcile truth
  - optionally restore missing services
  - save reconciled state
- For `reuse_expand`, keep the existing incremental-start behavior but gate it behind the stronger identity/fingerprint checks.
- If truth reconciliation shows the candidate run is stale or the resume path fails, fall back to a fresh run and emit a specific skip reason.

### 8) Preserve clear run-history semantics
- Explicitly define the new run model in docs:
  - a run can span multiple CLI sessions if envctl determines the environment is the same
  - a session is always per launch
  - a fresh run is created only when identity or startup contract changed materially, or when reuse is unsafe
- Add metadata such as:
  - `run_reuse_count`
  - `last_reopened_at`
  - `last_reuse_reason`
- Keep these as metadata only; do not change repository pointer layout or per-run directory shape.

### 9) Update inspection, diagnostics, and operator explanations
- Extend `inspection_support._print_startup_explanation(...)` to surface the richer decision space:
  - `resume_exact`
  - `resume_subset`
  - `reuse_expand`
  - `resume_dashboard_exact`
  - precise mismatch reasons such as `project_root_mismatch`, `startup_fingerprint_mismatch`, `failed_state`, `mode_mismatch`
- Extend debug diagnostics aggregation to preserve the new skip reasons without breaking existing summaries.
- Emit new startup events such as:
  - `state.run_reuse.evaluate`
  - `state.run_reuse.applied`
  - `state.run_reuse.skipped`
  - `state.dashboard_resume`

### 10) Keep fallback behavior explicit and safe
- Fresh run should still be the fallback when:
  - `--no-resume` is present
  - mode differs
  - project roots differ
  - startup fingerprint differs
  - previous state is failed
  - reconcile/restore detects unrecoverable drift
- The fallback should not silently mutate the previous run into an incompatible shape.
- The user-facing inspection/debug output should explain why a fresh run was chosen.

## Tests (add these)
### Backend tests
- Extend `tests/python/runtime/test_engine_runtime_startup_support.py`
  - new run-reuse eligibility helper accepts exact root/config match
  - root mismatch rejects reuse even when project names match
  - startup fingerprint mismatch rejects reuse
  - dashboard-only latest state is eligible for dashboard resume
  - failed state remains ineligible
- Extend `tests/python/startup/test_startup_orchestrator_flow.py`
  - disabled startup mode reopens an existing dashboard run instead of building a fresh one when identity matches
  - disabled startup mode still creates a fresh planning state when identity or fingerprint differs

### Frontend tests
- Extend `tests/python/runtime/test_engine_runtime_command_parity.py`
  - `explain-startup --json` reports the richer run-reuse decision and reason for disabled-startup dashboards
- Extend `tests/python/runtime/test_lifecycle_parity.py`
  - resumed/reopened run output remains consistent with existing resume banner rules
  - fresh session retains a new session id even when run id is reused

### Integration/E2E tests
- Extend `tests/python/runtime/test_engine_runtime_real_startup.py`
  - exact tree-plan match reuses the prior run id
  - disabled tree dashboard relaunch reuses the prior run id instead of creating a new one
  - config/profile change forces a fresh run
  - project-root change forces a fresh run
  - `--no-resume` forces a fresh run even when identity matches
  - expand path still preserves existing run and starts only new projects under the stronger identity checks
- Extend `tests/python/debug/test_debug_bundle_generation.py`
  - new run-reuse skip reasons appear in diagnostics summaries

## Observability / logging (if relevant)
- Emit a structured reuse evaluation event before the decision is applied:
  - candidate run id
  - current session id
  - mode
  - selected project identities
  - fingerprint match result
  - final decision kind
- Emit explicit skip reasons instead of overloading everything into `project_selection_mismatch`.
- Keep `explain-startup` aligned with the same decision helper to avoid drift between runtime behavior and inspection output.

## Rollout / verification
- Phase 1:
  - add persisted startup identity/fingerprint metadata
  - add run-reuse decision helper with unit coverage
- Phase 2:
  - refactor startup orchestration order so reuse is evaluated before disabled-startup fresh state creation
  - implement dashboard-resume path and preserve current service resume path
- Phase 3:
  - update inspection/debug surfaces
  - expand integration coverage and relaunch scenarios
- Verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_startup_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_orchestrator_flow`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity tests.python.runtime.test_lifecycle_parity`
  - `PYTHONPATH=python python3 -m unittest tests.python.debug.test_debug_bundle_generation`

## Definition of done
- Exact same-environment launches reuse the prior `run_id` instead of creating a redundant new run.
- Reused runs still go through truth-aware resume or dashboard-reopen validation before being treated as current.
- Disabled-startup tree dashboards can reopen the same run when project identity and startup fingerprint match.
- Different project roots or materially different startup configuration force a fresh run.
- `session_id` remains fresh on every CLI launch.
- `explain-startup` and debug diagnostics accurately describe the reuse decision.

## Risk register (trade-offs or missing tests)
- Risk: broadening run reuse can blur the meaning of a run from “one startup attempt” into “one environment lineage.”
  - Mitigation: document the new semantics explicitly and keep fresh sessions distinct with new `session_id`s.
- Risk: weak identity matching could reopen the wrong run for a renamed or moved tree.
  - Mitigation: require root-aware identity and startup fingerprint matching; only use name-only fallback for older states with missing root metadata.
- Risk: reused dashboard-only states could look current even when config changed.
  - Mitigation: include startup-enabled/service/dependency profile data in the fingerprint and reject reuse on mismatch.
- Risk: orchestration-order changes could regress existing exact/subset/expand auto-resume flows.
  - Mitigation: preserve current branch semantics and extend the existing real-startup tests rather than replacing them.

## Open questions (only if unavoidable)
- None. The repo evidence is sufficient to plan a stricter same-run reuse design built on the existing auto-resume architecture.
