# Startup Orchestration Decision Boundary Refactor

## Goals / non-goals / assumptions

Goals:
- Refactor startup orchestration so route validation, project selection, run reuse, project execution, plan-agent handoff, and finalization have clear ownership boundaries.
- Make startup decisions explicit before side effects whenever possible, especially for resume/reuse/expand, shared dependency reuse, and partial project startup.
- Preserve current user-visible behavior and event names while reducing the chance that future tree, dependency, or plan-agent fixes require editing `StartupOrchestrator` directly.
- Add characterization and ownership tests so the refactor can be staged safely.

Non-goals:
- Do not rework Supabase internals here. `todo/plans/refactoring/envctl-supabase-startup-state-machine-refactor.md` owns that adapter-level refactor.
- Do not rework plan-agent transport internals here. `todo/plans/refactoring/plan-agent-launch-support-modularization.md` owns transport/workflow modularization.
- Do not change CLI flags, runtime defaults, dependency enablement, port allocation rules, dashboard metadata, or state file format unless a test proves the current behavior is wrong.
- Do not remove compatibility facades in the first pass.

Assumptions:
- This is behavior-preserving architecture work. Any behavior change discovered during implementation should either be covered by a separate broken plan or called out explicitly in the implementation PR.
- Full-stack validation applies because the boundary touches managed dependencies, app service startup, plan-agent launch, dashboard state, and interactive/headless output.
- The existing dirty worktree contains unrelated plan/release work; implementation should avoid unrelated files except where tests/docs need targeted updates.

## Goal (user experience)

Developers should keep using the same commands, including `envctl --main`, `envctl --tree`, `envctl --plan ... --tmux --entire-system`, `restart`, and `resume`. Startup should remain at least as fast and reliable as today, but maintainers should be able to reason about a run through explicit objects: what projects were selected, which prior state is reused, which projects must start, which services/requirements are preserved, which plan-agent session exists, and what final state will be written.

## Business logic and data model mapping

- Main coordinator:
  - `python/envctl_engine/startup/startup_orchestrator.py:StartupOrchestrator.execute(...)` is the top-level startup control path.
  - `StartupOrchestrator._resolve_run_reuse(...)` applies `RunReuseDecision` and mutates `StartupSession`.
  - `StartupOrchestrator._start_selected_contexts(...)` owns tree-level parallel execution, spinner wiring, local startup failure degradation, and result recording.
  - `StartupOrchestrator._finalize_success(...)` and `_finalize_failure(...)` write artifacts, emit summaries, attach plan-agent sessions, and enter the dashboard.
- Session/state objects:
  - `python/envctl_engine/startup/session.py:StartupSession` is the mutable run accumulator.
  - `StartupSession.merged_services` and `merged_requirements` merge preserved state with newly started project results.
  - `python/envctl_engine/startup/finalization.py:build_success_run_state(...)` and `build_failure_run_state(...)` project `StartupSession` into `RunState`.
- Run reuse:
  - `python/envctl_engine/startup/run_reuse_support.py:evaluate_run_reuse(...)` returns `RunReuseDecision`.
  - `python/envctl_engine/runtime/engine_runtime_startup_support.py:evaluate_run_reuse(...)` is the runtime facade that delegates to the startup module.
  - Decisions include `resume_exact`, `resume_subset`, `reuse_expand`, `resume_dashboard_exact`, and `fresh_run`.
- Per-project startup:
  - `python/envctl_engine/startup/startup_execution_support.py:start_project_context(...)` reserves project ports, starts requirements, validates readiness, syncs Supabase auth users, starts services, and returns `ProjectStartupResult`.
  - `python/envctl_engine/startup/requirements_execution.py:start_requirements_for_project(...)` handles requirement-level parallelism through `ENVCTL_REQUIREMENTS_PARALLEL`.
  - `python/envctl_engine/startup/service_execution.py:start_project_services(...)` prepares and attaches backend/frontend/additional services through service-level parallel controls.
- Existing tests:
  - `tests/python/startup/test_startup_orchestrator_flow.py` covers disabled startup, plan-agent bootstrap, run reuse, and failure run IDs.
  - `tests/python/startup/test_startup_spinner_integration.py` covers progress/spinner behavior, shared dependencies, restart preservation, and service selection.
  - `tests/python/startup/test_support_module_decoupling.py` proves earlier extraction work around requirement/service execution.
  - `tests/python/runtime/test_engine_runtime_real_startup.py` covers real startup command behavior, tree parallelism, and service parallelism.
  - `tests/python/runtime/test_lifecycle_parity.py` covers resume, stale restore, cleanup, and lifecycle parity.

## Current behavior (verified in code)

- `StartupOrchestrator` is a 2,266-line class. AST inspection shows it owns 2,181 LOC and roughly 321 branch nodes.
- `_resolve_run_reuse(...)` is roughly 309 LOC. It evaluates reuse, emits events, calls `_resume(...)`, mutates `StartupSession`, restores preserved services/requirements, filters `contexts_to_start`, handles dashboard-only resume, and may terminate existing services for fresh-start replacement.
- `_start_selected_contexts(...)` is roughly 214 LOC. It decides tree-level parallelism, configures spinner callbacks, starts projects sequentially or through `ThreadPoolExecutor`, handles plan-agent degraded handoff, records results, and renders warnings.
- `start_project_context(...)` is already extracted to `startup_execution_support.py`, but it still receives progress callbacks through route flags and returns only a low-level result. The outer orchestration plan is still implicit in mutable session fields.
- `start_project_services(...)` is a separate hotspot: about 832 LOC and 101 branch nodes. It should remain a downstream service-start owner, but startup orchestration should not grow more logic around service prep/attach details.
- The developer guide `docs/developer/startup-resume-deep-dive.md` documents the desired conceptual phases, but code ownership does not mirror those phases. The guide names route parsing, selection, auto-resume, Docker prewarm, per-project startup, requirement startup, and service startup as distinct layers.
- Existing support-module tests already assert that `startup_execution_support` re-exports extracted requirement/service owners, which shows the repo accepts compatibility facades while ownership moves.

## Root cause(s) / gaps

- Startup has an implicit plan encoded through mutable `StartupSession` updates instead of a typed execution plan.
- Run reuse evaluation is partially pure, but applying the decision is side-effect-heavy and lives inside the main orchestrator.
- Project execution combines orchestration policy and UI mechanics: worker selection, spinner mode, progress routing, result ordering, warning rendering, and degraded plan-agent handoff are interleaved.
- Finalization repeatedly rebuilds `RunState` from mutable session state, so failures in reuse/expand paths can accidentally reuse the wrong run id or preserved state unless each branch is tested directly.
- There is no module ownership guard preventing `startup_orchestrator.py` from becoming the default place for every new startup fix.

## Plan

### 1) Add characterization tests before extraction

- Extend `tests/python/startup/test_startup_orchestrator_flow.py` with tests for:
  - `reuse_expand` preserving existing project services/requirements while starting only newly selected projects.
  - `reuse_expand` stale-state skip falling back to a fresh run without preserving stale services.
  - `resume_exact` / `resume_subset` failed resume restoring the previous fresh-run id behavior.
  - `resume_dashboard_exact` writing dashboard metadata without starting services.
- Extend `tests/python/startup/test_startup_spinner_integration.py` with one focused test that verifies project spinner success rows include restored projects and newly started projects in a reuse-expand run.
- Keep these tests on the current public behavior before moving code.

### 2) Introduce explicit startup planning models

- Add `python/envctl_engine/startup/execution_plan.py`.
- Define small internal dataclasses:
  - `StartupExecutionPlan`: selected contexts, contexts to start, resumed context names, preserved services, preserved requirements, base metadata, effective route, reuse decision kind, and finalization hint.
  - `StartupProjectWorkItem`: project context, display name, mode, route, run id, and whether the item is newly started or restored.
  - `RunReuseApplicationResult`: status, return code when orchestration should stop, updated route, preserved state, contexts to start, emitted event payload hints.
- Keep models internal to startup. They should be serializable enough for tests but should not become persisted state.
- Initially build these objects from the existing `StartupSession` so the first step is additive and low-risk.

### 3) Extract run-reuse application from `StartupOrchestrator`

- Add `python/envctl_engine/startup/run_reuse_application.py`.
- Move the decision-application logic out of `_resolve_run_reuse(...)` in stages:
  - exact/subset resume route construction and resume failure fallback;
  - `reuse_expand` preserved service/requirement application;
  - dashboard-only resume metadata update;
  - dashboard-stopped-service restore route rewrite;
  - fresh-start replacement service selection.
- Keep `StartupOrchestrator._resolve_run_reuse(...)` as the side-effect boundary at first: it should call the new helper, apply returned session changes, and preserve existing event names.
- Use `RunReuseDecision` from `run_reuse_support.py`; do not duplicate identity comparison logic.
- Preserve these event contracts:
  - `state.run_reuse.evaluate`
  - `state.run_reuse.applied`
  - `state.run_reuse.skipped`
  - `state.auto_resume`
  - `state.auto_resume.skipped`
  - `state.dashboard_resume`
  - `state.run_reuse.replace_existing_services`

### 4) Extract project execution coordination

- Add `python/envctl_engine/startup/project_execution.py`.
- Move the policy portion of `_start_selected_contexts(...)` behind a helper such as `execute_project_startup_plan(...)`.
- The new helper should own:
  - tree-level worker decision from `runtime._tree_parallel_startup_config(...)`;
  - `startup.execution` event emission;
  - sequential vs `ThreadPoolExecutor` execution;
  - stable result ordering by `session.contexts_to_start`;
  - failure aggregation;
  - route progress flag injection.
- Leave spinner rendering either in the orchestrator or in a small `startup/project_progress.py` helper. The important boundary is that execution returns structured `ProjectStartupResult` records and local failure data instead of mutating session from multiple places.
- Preserve behavior for degraded plan-agent handoff: local startup failures may become warnings only when a plan-agent session is already running and the existing command conditions are met.

### 5) Make `StartupSession` a state accumulator, not the planner

- Keep `StartupSession` as the mutable accumulator used by finalization and dashboard state.
- Add methods or helper functions that apply a `StartupExecutionPlan` to a session in one place:
  - apply selected contexts;
  - apply preserved services/requirements;
  - apply project startup results;
  - apply degraded plan-agent local failures.
- Avoid having reuse, execution, and finalization each mutate the same fields independently.
- Add tests around `StartupSession.merged_services` / `merged_requirements` when preserved and newly started projects overlap.

### 6) Narrow `StartupOrchestrator.execute(...)` into phase orchestration

- After helpers exist, make `execute(...)` read as a small phase list:
  - validate route;
  - prestop restart;
  - select contexts;
  - plan/dry-run setup;
  - plan-agent launch;
  - resolve/apply reuse;
  - disabled-startup handling;
  - prepare execution;
  - execute project plan;
  - reconcile truth;
  - finalize.
- Keep the phase order unchanged.
- Keep compatibility wrapper methods for existing tests if needed, but route implementation to the new modules.
- Add a module layout test to prevent new large helper bodies from being added back to `startup_orchestrator.py`.

### 7) Keep finalization behavior stable and add boundaries

- Keep `python/envctl_engine/startup/finalization.py` as the owner for `RunState` construction.
- Add tests in `tests/python/startup/test_startup_finalization.py` or extend `test_startup_orchestrator_profiles.py` for:
  - shared dependency dashboard metadata;
  - plan-agent metadata;
  - failed-state metadata;
  - preserved + newly started service merge order.
- Ensure failure finalization still:
  - allocates a fresh run id after failed resume/reuse-expand startup;
  - terminates only services started during this attempt;
  - releases the port allocator session;
  - writes failure artifacts with selected contexts and errors.

### 8) Update developer docs and ownership tests

- Update `docs/developer/startup-resume-deep-dive.md` so conceptual phases map to the new owner modules.
- Add `tests/python/startup/test_startup_module_layout.py`:
  - assert `startup_orchestrator.py` imports from the new modules;
  - assert `run_reuse_application.py` does not import UI/dashboard modules;
  - assert `project_execution.py` does not import finalization or dashboard rendering;
  - assert `StartupOrchestrator` remains below an agreed size after extraction.
- If a strict LOC ceiling is too brittle initially, assert symbol ownership instead: `_resolve_run_reuse` and `_start_selected_contexts` should be thin wrappers.

## Tests (add these)

Backend tests:
- `tests/python/startup/test_startup_execution_plan.py`
  - Verify `StartupExecutionPlan` builds selected/restored/new-project work items without mutating session.
  - Verify preserved service and requirement application for reuse-expand.
- `tests/python/startup/test_startup_run_reuse_application.py`
  - Verify exact/subset resume route construction.
  - Verify reuse-expand applies preserved state and computes `contexts_to_start`.
  - Verify stale reuse-expand returns a fresh-start path.
  - Verify dashboard-stopped-service restore route rewrite.
- `tests/python/startup/test_startup_project_execution.py`
  - Verify sequential and parallel execution preserve deterministic result recording.
  - Verify aggregated failures and degraded plan-agent handoff behavior.
  - Verify `startup.execution` event payloads are unchanged.
- `tests/python/startup/test_startup_module_layout.py`
  - Verify owner-module boundaries and prevent new startup-orchestrator growth.
- Extend existing:
  - `tests/python/startup/test_startup_orchestrator_flow.py`
  - `tests/python/startup/test_startup_spinner_integration.py`
  - `tests/python/startup/test_startup_orchestrator_profiles.py`
  - `tests/python/runtime/test_engine_runtime_real_startup.py`
  - `tests/python/runtime/test_lifecycle_parity.py`

Frontend tests:
- Not applicable. No browser frontend is changed.

Integration/E2E tests:
- Focused startup suite:
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_orchestrator_flow`
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_spinner_integration`
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_support_module_decoupling`
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_orchestrator_profiles`
- Runtime lifecycle suite:
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_lifecycle_parity`
- Full test run before merge:
  - `.venv/bin/python -m pytest -q`
- Manual smoke when Docker/runtime prerequisites are available:
  - `envctl --tree --headless`
  - `envctl --tree --parallel-trees --headless`
  - `envctl --plan refactoring/startup-orchestration-decision-boundaries --tmux --entire-system --headless --tmux-new-session`

## Observability / logging

- Preserve existing event names and payload shapes during the refactor.
- Add no new user-facing logs unless they explain a newly explicit phase boundary.
- If adding internal debug events, keep them behind existing debug/timing controls and avoid secrets or full environment maps.
- Preserve progress behavior:
  - single spinner for one-project startup;
  - project spinner group for multi-project rich startup;
  - shared dependency progress under the selected tree project;
  - degraded plan-agent handoff messaging.

## Rollout / verification

Implementation launch scope: `--entire-system`, because this refactor crosses startup selection, dependency startup, backend/frontend/additional service launch, plan-agent handoff, dashboard state, and runtime truth reconciliation.

Recommended Codex cycles: `7`. Rationale: this is high-complexity architecture-sensitive work across startup orchestration, state reuse, progress UI, tests, and docs, and it needs multiple follow-up passes to keep behavior stable.

Auto-launch command:

```bash
ENVCTL_PLAN_AGENT_CODEX_CYCLES=7 envctl --plan refactoring/startup-orchestration-decision-boundaries --tmux --entire-system --headless --tmux-new-session
```

Implementation sequence:
1. Land characterization tests against current behavior.
2. Add planning dataclasses without changing behavior.
3. Extract run-reuse application behind existing orchestrator wrappers.
4. Extract project execution coordination behind existing orchestrator wrappers.
5. Tighten `StartupSession` mutation points.
6. Add module ownership tests and update developer docs.
7. Run focused startup/runtime suites and the full pytest suite.

## Definition of done

- `StartupOrchestrator` is a phase coordinator, not the owner of run-reuse application and project execution internals.
- Run reuse application is testable without running the full startup command.
- Project execution coordination is testable without route validation, plan-agent launch, or dashboard finalization.
- Existing event names, output, run ids, dashboard metadata, and state persistence behavior remain compatible.
- Reuse-expand, exact/subset resume, dashboard resume, disabled startup, plan-agent degraded handoff, shared dependencies, and restart preservation have focused coverage.
- Developer docs identify the new startup owner modules.
- Full pytest passes.

## Risk register

- Risk: splitting side-effect-heavy code can accidentally change event order or run id ownership. Mitigation: add characterization tests first and keep wrapper methods until behavior is stable.
- Risk: project spinner behavior is easy to regress when execution moves out of the orchestrator. Mitigation: keep spinner integration tests and preserve route progress callback semantics during the first pass.
- Risk: plan-agent degraded handoff crosses startup and plan-agent modules. Mitigation: keep transport internals out of this refactor and only move startup-side handoff state handling.
- Risk: size/ownership tests can become brittle. Mitigation: prefer symbol ownership assertions first, then add LOC ceilings only after the extraction settles.
