# Envctl Interactive Restart Shared Dependency Truth Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep shared Redis, Supabase, and n8n dependency rows truthful after an interactive app-only restart in trees mode.

**Architecture:** Treat this as a state/truth reconciliation bug, not a plan-agent launch bug. Preserve app-only restart semantics, then make dependency truth reconciliation resolve shared dependency identity from the requirements record and shared-dashboard metadata instead of blindly using the `RunState.requirements` dictionary key.

**Tech Stack:** Python 3.12, `unittest`, envctl Python runtime, Docker-backed dependency adapters, dashboard rendering/state truth modules.

---

## Goals / non-goals / assumptions (if relevant)

Goals:
- After pressing `r` in interactive trees mode and restarting only app services, previously healthy shared dependencies must remain healthy in the dashboard when their containers/ports are still reachable.
- Preserve existing behavior where selecting dependency resources in the restart selector sets `restart_include_requirements=True` and restarts dependencies.
- Make the state truth pass use the correct shared dependency project/root/container identity for shared tree dependencies.
- Add regression coverage for the reported sequence, not just isolated rendering or selector helpers.

Non-goals:
- Do not change OpenCode/tmux plan-agent launch readiness; PR #199 already owns that path.
- Do not hide real dependency failures. If Redis/n8n/Supabase are actually stopped, mapped to a different port, or unhealthy, the dashboard should still show failure.
- Do not change service counts to include dependency rows; this plan only covers dependency truth and rendering after restart.
- Do not introduce a state schema migration unless tests prove existing state cannot be safely interpreted.

Assumptions:
- The user-provided reproduction is authoritative: app services restart successfully, while dependency rows flip from healthy/unreachable mix to all `n/a [Unreachable]` under `Shared dependencies:`.
- Redis and n8n becoming unreachable after an app-only restart is the primary regression signal because Supabase was already unreachable before restart.
- Full-stack runtime validation is useful because the bug crosses dashboard input, restart orchestration, runtime state, Docker dependency identity, and rendering.

## Goal (user experience)

When an operator runs `envctl` in trees interactive mode and presses `r` to restart app services, the next dashboard render should still show shared dependencies using their real health. If Redis and n8n were healthy before the restart and were not selected for dependency restart, they should remain visible with URLs and `[Healthy]`, not become `n/a [Unreachable]`. If a dependency was already unreachable, it may remain unreachable, but healthy dependencies must not be downgraded by state-key or project-root confusion.

## Business logic and data model mapping

- Interactive command loop:
  - `python/envctl_engine/ui/command_loop.py:run_dashboard_command_loop(...)` reads `Enter command:`, dispatches the route, reloads state, and calls dashboard rendering again.
- Interactive restart selector:
  - `python/envctl_engine/ui/dashboard/orchestrator.py:DashboardOrchestrator._apply_restart_selection(...)` decides whether restart is a project/service selector or resource selector.
  - `python/envctl_engine/ui/dashboard/orchestrator.py:DashboardOrchestrator._apply_restart_resource_tokens(...)` sets `services`, `restart_service_types`, and `restart_include_requirements`.
- Restart orchestration:
  - `python/envctl_engine/startup/startup_orchestrator.py:StartupOrchestrator._handle_restart_prestop(...)` terminates selected services, preserves untouched requirements, and rewrites `restart` into a synthetic `start` route with `_restart_*` flags.
  - `python/envctl_engine/startup/startup_selection_support.py:_restart_include_requirements(...)` defines when dependency restart is included.
- Shared dependency startup/reuse:
  - `python/envctl_engine/startup/startup_execution_support.py:_requirements_for_project_context(...)` routes trees/shared dependency mode to `_shared_main_requirements(...)`.
  - `python/envctl_engine/startup/startup_execution_support.py:_shared_main_requirements(...)` caches the shared requirements result.
  - `python/envctl_engine/startup/startup_execution_support.py:_load_or_start_shared_main_requirements(...)` reuses existing main requirements if strict readiness permits, otherwise starts requirements for a synthetic `Main` context.
  - `python/envctl_engine/startup/startup_execution_support.py:_annotate_shared_main_requirements(...)` stamps canonical shared container names for Redis, n8n, and Supabase using the execution root and `project_name="Main"`.
- State model and finalization:
  - `python/envctl_engine/startup/session.py:StartupSession.merged_requirements` merges `preserved_requirements` with `requirements_by_project`, with new project requirements overlaying preserved entries.
  - `python/envctl_engine/startup/finalization.py:_build_run_state(...)` writes `dependency_mode`, `shared_dependencies`, `dashboard_dependency_scope`, and `dashboard_shared_dependency_project` metadata.
- Dashboard truth/rendering:
  - `python/envctl_engine/runtime/engine_runtime_dashboard_truth.py:dashboard_reconcile_for_snapshot(...)` calls `_reconcile_state_truth(...)` before dashboard rendering.
  - `python/envctl_engine/runtime/engine_runtime_state_truth.py:reconcile_requirements_truth(...)` iterates requirements and mutates component `runtime_status`.
  - `python/envctl_engine/runtime/engine_runtime_state_truth.py:_project_root_for_state(...)` currently uses the requirements dictionary key to resolve `metadata["project_roots"]`.
  - `python/envctl_engine/runtime/engine_runtime_state_truth.py:_requirement_owner_mismatch(...)` checks expected dependency container names and mapped ports.
  - `python/envctl_engine/ui/dashboard/rendering.py:_dashboard_dependency_line(...)` renders `n/a` when badge severity is failure, including `runtime_status="unreachable"`.

## Current behavior (verified in code)

- App-only restart can intentionally exclude dependencies.
  - `DashboardOrchestrator._apply_restart_resource_tokens(...)` sets `restart_include_requirements` to `bool(selected_dependencies)`, so service-only restart sets it to `False`.
  - Existing tests in `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` assert service-only restarts set `restart_include_requirements=False` and dependency selection sets it to `True`.
- Restart pre-stop preserves requirement records when dependencies are not included.
  - `StartupOrchestrator._handle_restart_prestop(...)` stores old requirements in `session.preserved_requirements` when `include_requirements` is false for a project.
- Trees mode shared dependencies are represented as shared `Main` requirements even when the dashboard has multiple worktree rows.
  - `_shared_main_requirements(...)` returns a requirements object whose `project` is normally `Main`.
  - `tests/python/ui/test_dashboard_rendering_parity.py` already verifies legacy shared tree dependencies can be keyed under worktree names while `RequirementsResult.project` is `Main` and render once under `Shared dependencies:`.
- Rendering healthy shared dependencies is already supported when truth reconciliation is disabled in tests.
  - `test_dashboard_groups_shared_tree_dependencies_once_after_projects` stubs `engine._reconcile_state_truth = lambda _state: []` and asserts Redis, Supabase, and n8n render with URLs and `[Healthy]`.
- Runtime truth reconciliation is the likely downgrade point.
  - `dashboard_reconcile_for_snapshot(...)` invokes `_reconcile_state_truth(...)` before rendering.
  - `reconcile_requirements_truth(...)` passes the requirements dict key as `project` into `reconcile_project_requirement_truth(...)`.
  - `_project_root_for_state(...)` also resolves root by that dict key.
  - In shared tree states, that key can be a worktree name while the dependency stack belongs to `RequirementsResult.project == "Main"` and the execution root.
- The exact visible symptom is produced by rendering code.
  - `_dashboard_dependency_line(...)` sets `url = "n/a"` for failure severity, and `dependency_status_badge("unreachable", ...)` renders `[Unreachable]`.

## Root cause(s) / gaps

- There is no regression test for the full reported sequence: trees/shared dashboard state, app-only interactive restart, preserved shared dependencies, truth reconciliation, and final dashboard output.
- `reconcile_requirements_truth(...)` lacks a shared-dependency identity resolver. It assumes the state requirements key is the project identity and root lookup key.
- Shared dependencies can be duplicated under worktree keys for dashboard grouping compatibility, while their canonical owner is `Main`. This creates a mismatch between:
  - `state.requirements` key, for example `feature-a-1`
  - `requirements.project`, often `Main`
  - `metadata.dashboard_shared_dependency_project`, usually `Main`
  - `metadata.project_roots`, often only worktree roots in dashboard states
  - expected dependency container names, which `_annotate_shared_main_requirements(...)` builds using execution root and `Main`
- Existing rendering tests intentionally bypass truth reconciliation, so they prove formatting but not the before-render mutation that the user hit.
- Existing state truth tests cover basic owner mismatch and unreachable behavior, but not shared tree requirements keyed under worktree names.

## Plan

### 1) Add a failing state-truth regression for shared requirements keyed by worktree name

- [ ] Extend `tests/python/runtime/test_engine_runtime_state_truth.py` with a test named `test_shared_tree_requirements_use_canonical_project_for_truth`.
- [ ] Build a `RunState` with `mode="trees"`, `requirements={"feature-a-1": RequirementsResult(project="Main", redis={...}, n8n={...})}`, and metadata containing:
  - `dashboard_dependency_scope="shared"`
  - `dashboard_shared_dependency_project="Main"`
  - `project_roots={"feature-a-1": <worktree-root>, "Main": <repo-root>}` if the planned implementation uses explicit `Main` root fallback.
- [ ] Use a fake runner whose `wait_for_port(...)` returns true for Redis/n8n ports and whose Docker `run(...)` methods report canonical Main containers and matching host ports.
- [ ] Run: `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_state_truth.EngineRuntimeStateTruthTests.test_shared_tree_requirements_use_canonical_project_for_truth`
- [ ] Expected before implementation: FAIL because reconciliation uses the worktree key/root or otherwise cannot preserve healthy shared dependency status.
- [ ] Expected after implementation: PASS with Redis and n8n `runtime_status == "healthy"` and no issues for those components.

Implementation guidance for the fake runner:

```python
class _Runner:
    def run(self, cmd, *, cwd=None, env=None, timeout=None):
        args = tuple(cmd)
        if args[:4] == ("docker", "ps", "-a", "--filter"):
            name_filter = next((part for part in args if str(part).startswith("name=")), "")
            container_name = name_filter.removeprefix("name=").strip("^").strip("$")
            return SimpleNamespace(returncode=0, stdout=f"{container_name}\n", stderr="")
        if args[:2] == ("docker", "port"):
            container = str(args[2])
            if "redis" in container:
                return SimpleNamespace(returncode=0, stdout="6379/tcp -> 0.0.0.0:6485\n", stderr="")
            if "n8n" in container:
                return SimpleNamespace(returncode=0, stdout="5678/tcp -> 0.0.0.0:5784\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def wait_for_port(self, port, timeout):
        return port in {6485, 5784}
```

### 2) Add a dashboard regression that keeps healthy shared dependencies healthy through reconciliation

- [ ] Extend `tests/python/ui/test_dashboard_rendering_parity.py` with `test_dashboard_shared_dependencies_survive_truth_reconcile_after_app_restart`.
- [ ] Create a temporary repo/runtime, instantiate `PythonEngineRuntime`, and do not stub `_reconcile_state_truth`.
- [ ] Build a trees `RunState` like the user report:
  - services for one worktree backend/frontend/voice runtime with `status="running"`
  - shared requirements under the worktree key with `RequirementsResult(project="Main", redis={"enabled": True, "success": True, "final": 6485}, n8n={"enabled": True, "success": True, "final": 5784}, supabase={"enabled": True, "success": False})`
  - metadata `dashboard_dependency_scope="shared"` and `dashboard_shared_dependency_project="Main"`
- [ ] Use a fake process runner or monkeypatch dependency owner checks so Redis/n8n are reachable and Supabase remains unhealthy/unreachable.
- [ ] Render `engine._print_dashboard_snapshot(state)` into a buffer.
- [ ] Assert Redis and n8n render with URLs and `[Healthy]`, not `n/a [Unreachable]`.
- [ ] Assert Supabase remains a failure if the test models it as failed, proving the fix does not mask real failures.

### 2.5) Add a restart state-merge regression for app-only restart preserving shared dependency state

- [ ] Extend `tests/python/startup/test_startup_spinner_integration.py` with `test_restart_service_only_preserves_shared_tree_dependency_state`.
- [ ] Model a previous `RunState(mode="trees")` with running worktree app services, shared dependency metadata, and `requirements` entries whose `RequirementsResult.project == "Main"`.
- [ ] Dispatch a restart route equivalent to selecting one app service only:
  - `command="restart"`
  - `mode="trees"`
  - `flags={"restart_service_types": ["backend"], "restart_include_requirements": False}`
- [ ] Assert the resulting serialized or in-memory run state keeps:
  - `metadata["dependency_mode"] == "shared"`
  - `metadata["shared_dependencies"] is True`
  - `metadata["dashboard_dependency_scope"] == "shared"`
  - `metadata["dashboard_shared_dependency_project"] == "Main"`
  - shared requirements still identify `project == "Main"`
- [ ] Assert restart does not call `_release_requirement_ports(...)` for preserved shared requirements.

### 3) Implement a canonical shared dependency truth identity helper

- [ ] Modify `python/envctl_engine/runtime/engine_runtime_state_truth.py` only after the failing tests above exist.
- [ ] Add a small helper near `_project_root_for_state(...)`, for example `_requirement_truth_identity(state, key, requirements) -> tuple[str, Path | None]`.
- [ ] The helper should return the project/root used for dependency owner checks, following this order:
  1. If `state.metadata["dashboard_dependency_scope"] == "shared"` and `requirements.project` is non-empty, use `requirements.project` as the truth project.
  2. Else if `state.metadata["dashboard_shared_dependency_project"]` is non-empty and the requirements record appears to describe dashboard dependencies, use that project.
  3. Else use the existing dict key.
  4. Resolve the root by the truth project first, then by the original dict key, then by no root.
- [ ] Keep behavior unchanged for isolated tree dependencies and main-mode dependencies.
- [ ] Use the helper inside `reconcile_requirements_truth(...)` for both sequential and threaded paths so `reconcile_project_requirement_truth(...)` receives the canonical project/root pair.
- [ ] Keep issue reporting useful: issues should use the canonical truth project for shared dependencies if that is what was probed, while preserving component and port fields.

### 4) Preserve container-name precedence and avoid false positives

- [ ] Do not remove existing `container_name` handling in `_requirement_owner_mismatch(...)`.
- [ ] If a component already has `container_name`, the helper should mainly provide the right root/project for Docker command context and fallback identity.
- [ ] If no `container_name` exists, shared dependencies should compute expected names as `Main` dependencies, not worktree dependencies.
- [ ] Add assertions that isolated tree dependencies still use their own project key and can be marked unreachable when their own container/port is missing.

### 5) Verify restart selector semantics remain unchanged

- [ ] Run the existing selector tests that lock in app-only versus dependency restart flags:
  - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector.DashboardOrchestratorRestartSelectorTests.test_restart_selector_service_selection_restarts_selected_service_only`
  - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector.DashboardOrchestratorRestartSelectorTests.test_interactive_restart_offers_running_dependencies_even_without_stopped_services`
- [ ] Do not change `DashboardOrchestrator._apply_restart_resource_tokens(...)` unless these tests prove selector flags are the real cause.

### 6) Add instrumentation only if tests expose ambiguity

- [ ] If the regression cannot be reproduced with state-only tests, add one narrowly scoped event in `reconcile_requirements_truth(...)`, guarded by existing runtime emit availability, for shared dependency identity decisions:
  - event name: `requirements.truth.identity`
  - payload: `state_key`, `truth_project`, `has_project_root`, `shared_scope`
- [ ] Do not print this to normal stdout.
- [ ] Do not add persistent state fields for this diagnostic unless implementation proves they are needed.

## Tests (add these)

Backend tests:
- `tests/python/runtime/test_engine_runtime_state_truth.py`
  - Add `test_shared_tree_requirements_use_canonical_project_for_truth`.
  - Add or extend an isolated dependency assertion to ensure isolated tree dependencies still reconcile by their own key/root.
- `tests/python/startup/test_startup_spinner_integration.py`
  - Add `test_restart_service_only_preserves_shared_tree_dependency_state` to cover restart pre-stop, `StartupSession.merged_requirements`, and final state metadata.
- `tests/python/startup/test_startup_orchestrator_profiles.py`
  - Add coverage only if implementation changes finalization metadata. Expected likely no change.

Frontend tests:
- Not applicable; this is terminal dashboard rendering, not browser UI.

Integration/E2E tests:
- `tests/python/ui/test_dashboard_rendering_parity.py`
  - Add `test_dashboard_shared_dependencies_survive_truth_reconcile_after_app_restart`.
  - Assert healthy shared Redis/n8n remain URL + `[Healthy]` after normal dashboard truth reconciliation.
  - Assert a genuinely failed Supabase row still renders as a failure.
- Existing selector tests to rerun:
  - `tests.python.ui.test_dashboard_orchestrator_restart_selector`
- Existing broad suites to rerun:
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_state_truth tests.python.runtime.test_engine_runtime_dashboard_truth tests.python.ui.test_dashboard_rendering_parity tests.python.ui.test_dashboard_orchestrator_restart_selector tests.python.startup.test_startup_orchestrator_profiles tests.python.startup.test_startup_spinner_integration`

Manual QA:
- Launch with `envctl --entire-system --headless` from the implementation worktree if the environment supports Docker dependencies.
- In an interactive run matching the reported flow, press `r`, select app services only, and verify Redis/n8n remain `[Healthy]` with URLs in the next dashboard render.
- If Docker dependencies are unavailable, run `envctl health --json` or inspect the saved run state after the regression path and document the environment limitation.

## Observability / logging (if relevant)

- Prefer tests over new logs.
- If needed for diagnosis, emit `requirements.truth.identity` through `runtime._emit` only; do not add user-facing output.
- Include state key, canonical truth project, and whether a project root was found. Do not include secrets, environment variables, or Docker command stderr beyond existing patterns.

## Rollout / verification

Implementation launch scope: use `--entire-system` because this bug crosses interactive dashboard behavior, runtime truth reconciliation, Docker-backed dependency ownership, and terminal output. The auto-launch command is:

```bash
envctl --plan broken/envctl-interactive-restart-shared-dependency-truth --tmux --opencode --entire-system --headless --new-session
```

Verification sequence for the implementer:

1. Run the new focused state-truth test and confirm it fails before implementation.
2. Run the new dashboard rendering regression and confirm it fails before implementation.
3. Implement the minimal truth-identity helper.
4. Run focused tests:
   - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_state_truth`
   - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_rendering_parity`
5. Run restart selector tests to prove app-only/dependency restart flags did not regress:
   - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector`
6. Run the combined regression suite:
   - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_state_truth tests.python.runtime.test_engine_runtime_dashboard_truth tests.python.ui.test_dashboard_rendering_parity tests.python.ui.test_dashboard_orchestrator_restart_selector tests.python.startup.test_startup_orchestrator_profiles tests.python.startup.test_startup_spinner_integration`
7. Run `lsp_diagnostics` on modified files.
8. Perform manual QA with `envctl --entire-system --headless` and, where possible, the interactive `r` flow from the user report.

## Definition of done

- New regression tests fail before the implementation and pass after it.
- Healthy shared Redis/n8n dependencies are not downgraded to `n/a [Unreachable]` after app-only restart/dashboard truth reconciliation.
- Genuinely failed dependencies still render as failure.
- App-only restart still sets `restart_include_requirements=False`; dependency restart still sets it to `True`.
- No new LSP diagnostics on modified Python files.
- Focused and combined regression suites pass.
- Manual QA is executed and recorded with actual command output or an explicit environment limitation.

## Risk register (trade-offs or missing tests)

- Docker ownership checks are environment-sensitive. Unit tests must use deterministic fake runners, while manual QA should document whether Docker dependencies were available.
- Existing states may lack `metadata.project_roots["Main"]`. The helper must safely fall back to component `container_name` and the original key root instead of requiring a migration.
- Shared requirements can appear under multiple worktree keys. The implementation should avoid duplicate conflicting mutations by using deterministic identity resolution, not by suppressing reconciliation entirely.
- Supabase has special status behavior when no DB port is present. Tests should avoid overfitting Redis/n8n expectations onto Supabase.

## Open questions (only if unavoidable)

None. The user report and repo evidence are sufficient to plan the fix.
