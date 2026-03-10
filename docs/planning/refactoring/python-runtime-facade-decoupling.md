# Python Runtime Facade Decoupling and Policy Ownership Refactor

## Goals / non-goals / assumptions

### Goals
- Restore `python/envctl_engine/runtime/engine_runtime.py` to the architecture documented in `docs/developer/module-layout.md:33-35` and `docs/developer/python-runtime-guide.md:77-80`: a thin composition root over domain-owned behavior.
- Eliminate cross-domain dependence on underscore-prefixed runtime helpers by introducing explicit collaborator interfaces and moving behavior ownership into the modules that already claim to own it.
- Centralize command and lifecycle policy so `skip_startup`, `load_state`, `no_resume`, readiness gating, and mode-resolution rules are defined once and consumed consistently.
- Separate core behavior from side effects in startup, resume, planning, diagnostics, and action flows so those behaviors can be tested without dragging in terminal UI, spinner, artifact, or compatibility concerns.
- Keep user-visible CLI behavior stable while making future changes to startup/resume/actions/state safer and easier to verify.

### Non-goals
- No shell-runtime deletion or retirement work in this plan. That remains downstream of this refactor and belongs to `todo/plans/refactoring/shell-runtime-retirement.md`.
- No new command surface, feature expansion, or UI redesign.
- No intentional changes to persisted state schema or pointer semantics unless the implementation proves a contract change is necessary and separately planned.
- No migration of runtime planning behavior from `todo/plans` to `docs/planning`; `docs/planning` is for engineering plans, while runtime planning continues to use `ENVCTL_PLANNING_DIR` (`docs/reference/configuration.md:45`, `docs/reference/important-flags.md:91-99`, `docs/user/planning-and-worktrees.md:7-24`).

### Assumptions
- Python remains the supported runtime path (`docs/reference/important-flags.md:20-23`, `docs/reference/configuration.md:47`).
- Readiness and shipability are product-level governance surfaces, not just internal docs, because they are emitted, persisted, and tested (`python/envctl_engine/runtime/runtime_readiness.py:33-83`, `python/envctl_engine/shell/release_gate.py:35-121`, `tests/python/runtime/test_cutover_gate_truth.py`, `tests/python/runtime/test_release_shipability_gate.py`).
- The existing test suite is the primary source of behavior truth during the refactor. New work should extend characterization before changing structure.
- The codebase is in an active migration state, so the safest implementation strategy is strangler-style replacement with compatibility shims, not a flag-day rewrite.

## Goal (user experience)
Users should see no regressions in how `envctl` parses commands, resolves modes, starts or resumes environments, runs actions, prints diagnostics, or writes runtime artifacts. The visible result of this work is not a new feature; it is a more reliable CLI whose internal design matches its documentation, making readiness gates more trustworthy and reducing the frequency of subtle regressions when future runtime logic changes.

## Business logic and data model mapping

### Runtime entry and routing
- Launcher and CLI handoff are documented in `docs/developer/python-runtime-guide.md:21-28`.
- Command parsing and route construction live in `python/envctl_engine/runtime/command_router.py` (`Route`, `parse_route`, parser phases).
- Command dispatch lives in `python/envctl_engine/runtime/engine_runtime_dispatch.py:9-44`.

### Runtime composition and collaborators
- `PythonEngineRuntime` is the composition root in `python/envctl_engine/runtime/engine_runtime.py:328-1564`.
- Existing protocol seeds already exist in `python/envctl_engine/shared/protocols.py:9-100`.
- A minimal runtime adapter already exists in `python/envctl_engine/runtime/runtime_context.py:10-18` but is too small to support current orchestration boundaries.

### Lifecycle and planning behavior
- Startup flow: `python/envctl_engine/startup/startup_orchestrator.py:67-971`.
- Startup helpers: `python/envctl_engine/startup/startup_execution_support.py`, `python/envctl_engine/startup/startup_selection_support.py`, `python/envctl_engine/runtime/engine_runtime_startup_support.py:11-182`.
- Resume flow: `python/envctl_engine/startup/resume_orchestrator.py:45-185` and `python/envctl_engine/startup/resume_restore_support.py`.
- Planning/worktree selection: `python/envctl_engine/planning/worktree_domain.py:334-983`.

### Actions, state, and diagnostics
- Action commands: `python/envctl_engine/actions/action_command_orchestrator.py:47-957`.
- State commands (`logs`, `health`, `errors`, `clear-logs`): `python/envctl_engine/state/action_orchestrator.py:25-752`.
- Doctor, cutover truth, and readiness evaluation: `python/envctl_engine/debug/doctor_orchestrator.py:11-293`.
- Readiness artifact generation: `python/envctl_engine/runtime/runtime_readiness.py:14-107` and `python/envctl_engine/runtime/engine_runtime_artifacts.py`.

### State and artifact contracts
- Core runtime state model: `python/envctl_engine/state/models.py:9-121`.
- Persistence, pointers, legacy compatibility, and scoped/runtime artifacts: `python/envctl_engine/state/repository.py:21-483`.

### UI and interaction boundaries
- Runtime/UI bridge: `python/envctl_engine/runtime/engine_runtime_ui_bridge.py:18-123`.
- Interactive terminal session and fallback behavior: `python/envctl_engine/ui/terminal_session.py`.
- Selector/backend resolution lives in `python/envctl_engine/ui/backend.py`, `python/envctl_engine/ui/backend_resolver.py`, and related UI modules.

## Current behavior (verified in code)

### 1. `PythonEngineRuntime` is still a compatibility bus, not a thin bridge
- `python/envctl_engine/runtime/engine_runtime.py:331-397` rebinds planning, requirements, bootstrap, env, and dashboard helpers directly onto the runtime class.
- The same class later exposes action, truth, cleanup, event, path, and command helpers (`python/envctl_engine/runtime/engine_runtime.py:963-1550`).
- `tests/python/runtime/test_engine_runtime_dispatch.py:20-47` and `python/envctl_engine/runtime/engine_runtime_dispatch.py:9-44` show dispatch still assumes a broad runtime surface instead of narrow domain contracts.

### 2. Command policy is duplicated in the parser and then reinterpreted downstream
- `python/envctl_engine/runtime/command_router.py:494-579` resolves command/mode behavior and injects defaults.
- `python/envctl_engine/runtime/command_router.py:582-710` repeats policy work when binding flags.
- `tests/python/runtime/test_cli_router_parity.py:53-99` explicitly asserts command families imply flags like `skip_startup` and `load_state`, so those semantics are contract-level behavior today.

### 3. Startup and resume mix behavior, policy, UI, and persistence
- `python/envctl_engine/startup/startup_orchestrator.py:67-260` handles readiness gate enforcement, restart-prestop spinner lifecycle, plan selection, runtime events, and user-facing prints before core startup work even begins.
- `python/envctl_engine/startup/resume_orchestrator.py:45-185` mixes state load, readiness enforcement, reconcile/restore behavior, event emission, save-resume-state, and human-readable output.
- `tests/python/startup/test_support_module_decoupling.py:50-128` already tries to enforce that support modules can work with smaller collaborator surfaces, but the production orchestration still depends on many runtime-private helpers.

### 4. Action and state orchestrators still depend on `runtime: Any`
- `python/envctl_engine/actions/action_command_orchestrator.py:47-235` calls `_discover_projects`, `_selectors_from_passthrough`, `_select_project_targets`, `_try_load_existing_state`, `_project_name_from_service`, and `_emit` on a runtime object typed as `Any`.
- `python/envctl_engine/state/action_orchestrator.py:29-260` performs the same pattern for state load, truth reconciliation, log printing, service selection, and target grouping.
- The code is partially modularized, but ownership is still inverted: orchestrators depend on runtime internals instead of the runtime depending on orchestrator contracts.

### 5. Doctor and cutover gates are deeply entangled with runtime internals
- `python/envctl_engine/debug/doctor_orchestrator.py:15-131` reads runtime paths, config, process-runner diagnostics, state compatibility, parity manifest state, readiness contracts, and writes readiness artifacts.
- `python/envctl_engine/debug/doctor_orchestrator.py:133-293` mixes command parity, runtime truth, lifecycle, and shipability evaluation, then emits cutover events used by tests like `tests/python/runtime/test_cutover_gate_truth.py:78-202` and `tests/python/runtime/test_engine_runtime_command_parity.py:67-260`.

### 6. State contracts are only partially typed
- `python/envctl_engine/state/models.py:35-109` normalizes requirement components through `RequirementComponentResult`, but still stores them as `dict[str, dict[str, Any]]`.
- `python/envctl_engine/state/models.py:113-121` leaves `RunState.metadata` as `dict[str, Any]`, making cutover-sensitive runtime flags loosely typed.
- `python/envctl_engine/state/repository.py:173-237` falls back across scoped JSON, shell compatibility state, scoped pointers, legacy JSON, legacy shell state, and legacy pointers, often with broad exception swallowing.
- `tests/python/state/test_state_repository_contract.py` and `tests/python/state/test_state_shell_compatibility.py` prove this is intentional behavior that must be preserved during migration.

### 7. Planning/worktree behavior still couples selection, mutation, UI, and terminal recovery
- `python/envctl_engine/planning/worktree_domain.py:334-449` combines plan resolution, worktree sync, duplicate detection, event emission, and user-facing prints.
- `python/envctl_engine/planning/worktree_domain.py:487-512` catches all exceptions during interactive selection and silently falls back to current counts, which is operationally convenient but architecturally risky.
- `tests/python/planning/test_planning_worktree_setup.py:35-200` covers many of these paths and should be treated as characterization, not implementation guidance.

### 8. Governance surfaces are inconsistent enough to block a confident refactor
- `tests/python/runtime/test_runtime_feature_inventory.py:115-122` asserts zero gaps and `ready_for_shell_retirement == true`.
- The generated report/contract layer can still indicate retirement is not ready.
- `todo/plans/README.md:21-29` defines standards that still refer to `docs/planning`, while runtime planning behavior continues to use `todo/plans` through config and user docs.

## Root cause(s) / gaps

### Root cause 1: the runtime object graph violates documented ownership
The codebase documents domain-owned behavior with a thin runtime bridge, but the actual object graph centers everything on `PythonEngineRuntime`. This is the primary cause behind the private helper sprawl, `Any` usage, and rebinding aliases.

### Root cause 2: command and lifecycle policy do not have a single owner
Mode resolution, startup skipping, state loading, resume behavior, and readiness gating are split across parser phases, runtime helper methods, and orchestrators. This makes structural cleanup dangerous because policy is implicit and duplicated.

### Root cause 3: behavioral cores are not isolated from side effects
Startup, resume, worktree planning, and doctor flows all mix decision-making with spinner/UI lifecycle, event emission, artifact writing, terminal handling, and compatibility fallback paths. As a result, there is no small, testable core to extract first.

### Root cause 4: compatibility contracts are embedded everywhere instead of being isolated
Legacy state reads/writes, compatibility pointers, shell-era hooks, readiness artifacts, and shipability checks are mixed into normal runtime paths. These are necessary today, but they are not isolated behind explicit compatibility boundaries.

### Root cause 5: governance does not provide a fully trustworthy definition of "done"
Readiness contracts, inventory assertions, and planning standards are close to each other but not fully aligned. That makes a large refactor harder to sequence safely because not all verification surfaces agree.

## Plan

### 1) Freeze governance and define authoritative truths before structural work
- Reconcile the shell-retirement truth model:
  - Align `contracts/python_runtime_gap_report.json`, `contracts/runtime_feature_matrix.json`, `python/envctl_engine/runtime_feature_inventory.py`, and `tests/python/runtime/test_runtime_feature_inventory.py` so the repo has one clear answer to whether shell retirement is ready.
  - Ensure `python/envctl_engine/shell/release_gate.py` and `python/envctl_engine/runtime/runtime_readiness.py` agree on what blocks shipability.
- Document the split between engineering plans and runtime planning:
  - `docs/planning/**` is for human implementation plans.
  - runtime plan discovery remains `ENVCTL_PLANNING_DIR`-driven and defaults to `todo/plans`.
- Deliverable:
  - updated docs and tests that remove ambiguity about readiness and planning path semantics.
- Why first:
  - without this, the refactor can pass one gate and fail another for reasons unrelated to the code changes.

### 2) Add characterization tests for the seams that the refactor will move
- Add a dedicated parser-policy contract suite:
  - `tests/python/runtime/test_command_policy_contract.py` (new)
  - capture representative command families and all implicit lifecycle flags they must produce.
- Expand orchestration seam tests:
  - extend `tests/python/startup/test_support_module_decoupling.py` to cover startup, resume, and worktree helpers that should operate on narrow collaborators.
  - extend `tests/python/state/test_state_action_orchestrator_logs.py` for selection and output behavior under protocol-backed runtime stubs.
- Expand readiness/shipability characterization:
  - strengthen `tests/python/runtime/test_cutover_gate_truth.py`
  - strengthen `tests/python/runtime/test_engine_runtime_command_parity.py`
  - keep `tests/python/runtime/test_release_shipability_gate.py` authoritative for release gate behavior.
- Acceptance criteria:
  - every behavior to be structurally moved has at least one direct test that does not depend on implementation file layout.

### 3) Introduce a real runtime collaboration model from existing protocol seeds
- Extend `python/envctl_engine/shared/protocols.py` with the runtime-facing collaborator groups actually needed by orchestrators, rather than using one giant runtime type.
- Replace the minimal `python/envctl_engine/runtime/runtime_context.py` with a richer adapter object that exposes:
  - config/env access
  - state repository access
  - port allocation and process runtime
  - emit/event interface
  - selection/UI hooks
  - command/policy access
  - artifact-path access where still needed
- Proposed protocol slices:
  - `RuntimePolicyContext`
  - `RuntimeStateAccess`
  - `RuntimeEmitter`
  - `RuntimeTargetSelection`
  - `RuntimeLifecycleOps`
  - `RuntimeArtifactPaths`
- Implementation rule:
  - protocols must represent stable collaboration boundaries, not mirror every private runtime method one-for-one.

### 4) Centralize command policy into one canonical module
- Create `python/envctl_engine/runtime/command_policy.py`.
- Move the following out of scattered parser/orchestrator logic into explicit policy structures/functions:
  - command requires startup / skips startup
  - command requires state / may load state
  - command forces or disables auto-resume
  - command legality by mode
  - readiness-gate enforcement scope
- Refactor `parse_route` so it only parses tokens and route structure; policy enrichment should happen once through the new command-policy layer.
- Update `engine_runtime_dispatch.py` and orchestrators to consume the same policy object rather than inferring behavior from flag combinations.
- Tests to update/add:
  - `tests/python/runtime/test_cli_router_parity.py`
  - `tests/python/runtime/test_engine_runtime_dispatch.py`
  - new `tests/python/runtime/test_command_policy_contract.py`

### 5) Split startup into policy/core/effects layers
- Current hotspots:
  - `python/envctl_engine/startup/startup_orchestrator.py`
  - `python/envctl_engine/startup/startup_execution_support.py`
  - `python/envctl_engine/startup/startup_selection_support.py`
  - `python/envctl_engine/runtime/engine_runtime_startup_support.py`
- Target layering:
  - `startup_policy.py`: readiness gate decisions, restart semantics, tree-selection policy, parallelism decisions.
  - `startup_core.py`: pure or near-pure project/context planning and execution decisions.
  - `startup_effects.py`: spinner, event emission, output rendering, artifact writes.
  - orchestrator remains as composition/wiring only.
- Immediate extraction targets:
  - restart-prestop selection/preservation logic from `startup_orchestrator.py:86-190`
  - phase emission helper contract from `startup_orchestrator.py:196-221`
  - readiness gate invocation from `startup_orchestrator.py:216-221`
  - context startup flow from `startup_execution_support.py` behind explicit collaborators.
- Guardrails:
  - do not change start/restart user-visible messages in the same PR as structural extraction.

### 6) Split resume into state reconciliation, restore planning, and interactive/output layers
- Current hotspots:
  - `python/envctl_engine/startup/resume_orchestrator.py`
  - `python/envctl_engine/startup/resume_restore_support.py`
- Target layering:
  - `resume_policy.py`: restore-enabled decision, strict-resume gating, legacy-resume policy.
  - `resume_core.py`: reconcile -> determine missing services -> build restore plan -> compute save result.
  - `resume_effects.py`: spinner, events, interactive loop entry, human-readable output.
- Immediate extraction targets:
  - `restore_enabled()` logic from `resume_orchestrator.py:187-193`
  - legacy-resume/reconcile/restore decision tree from `resume_orchestrator.py:75-148`
  - save-and-print phase from `resume_orchestrator.py:149-185`
- Tests to lean on:
  - `tests/python/runtime/test_lifecycle_parity.py`
  - `tests/python/runtime/test_cutover_gate_truth.py`
  - `tests/python/startup/test_resume_progress.py`

### 7) Move action and state command orchestration off the raw runtime facade
- Replace `runtime: Any` in:
  - `python/envctl_engine/actions/action_command_orchestrator.py`
  - `python/envctl_engine/state/action_orchestrator.py`
- Introduce collaborator adapters specific to these areas:
  - target discovery and selection
  - state access and filtering
  - action command environment building
  - log/health output services
  - spinner/event emission
- Keep command-family specific helpers in their existing domains:
  - test execution in `actions/action_test_*`
  - worktree deletion in `actions/action_worktree_runner.py`
  - state filtering and payload formatting in `state/action_orchestrator.py` until their owning service is clear.
- Objective:
  - by the end of this phase, action/state orchestrators should no longer need underscore-prefixed runtime calls except through intentional adapters.

### 8) Isolate doctor/readiness/shipability as governance services, not runtime internals
- Extract from `python/envctl_engine/debug/doctor_orchestrator.py`:
  - runtime diagnostics payload construction
  - readiness gate evaluation
  - shipability delegation
  - event emission for cutover gates
- Create explicit services such as:
  - `runtime_readiness_service.py`
  - `cutover_gate_service.py`
  - `doctor_report_builder.py`
- Keep `DoctorOrchestrator` as a coordinator that formats output and calls services.
- Required compatibility:
  - preserve current `cutover.gate.fail_reason` and `cutover.gate.evaluate` event schemas used by tests.

### 9) Normalize the state contract and isolate compatibility reads/writes
- Keep the persisted on-disk schema stable for the initial refactor.
- Internally, strengthen types by introducing structured wrappers for:
  - runtime metadata currently stored in `RunState.metadata`
  - requirement components currently stored as nested `dict[str, Any]`
- Isolate compatibility behavior into explicit modules:
  - scoped runtime JSON reads/writes
  - shell-state reads
  - pointer resolution
  - legacy mirror writes
- Refactor `python/envctl_engine/state/repository.py` so the fallback chain is declarative and testable, not hidden behind nested `try/except` blocks.
- Tests to update/add:
  - `tests/python/state/test_state_repository_contract.py`
  - `tests/python/state/test_state_shell_compatibility.py`
  - `tests/python/state/test_state_roundtrip.py`

### 10) Separate planning/worktree behavior from terminal presentation and recovery
- Split `python/envctl_engine/planning/worktree_domain.py` into:
  - plan resolution and selection mapping
  - worktree sync/mutation engine
  - terminal selection presentation/recovery wrapper
  - archive/done-root handling
- Preserve all user-visible plan behavior and path semantics validated in:
  - `tests/python/planning/test_planning_worktree_setup.py`
  - `tests/python/planning/test_planning_selection.py`
  - `tests/python/planning/test_planning_textual_selector.py`
- Specific risk to address:
  - `worktree_domain.py:507-512` currently falls back broadly on interactive exceptions; the refactor should make this behavior explicit and test-covered.

### 11) Shrink `PythonEngineRuntime` last, not first
- Once the new command-policy layer, runtime adapters, and domain services are in place:
  - remove rebinding aliases from `engine_runtime.py`
  - replace remaining underscore-private service exposure with explicit collaborator objects
  - reduce `PythonEngineRuntime` to constructor wiring, high-level dispatch entrypoints, and temporary backwards-compatible delegators where still needed.
- Success metric:
  - `engine_runtime.py` should primarily construct collaborators and expose only a minimal, intentional surface.

### 12) Update docs, inventories, and release governance after the structural move
- Update:
  - `docs/developer/module-layout.md`
  - `docs/developer/python-runtime-guide.md`
  - any related architecture docs that still describe the current facade-heavy reality
- Re-generate or realign:
  - `contracts/runtime_feature_matrix.json`
  - `contracts/python_runtime_gap_report.json`
  - any scripts that derive them
- Ensure all references in tests and docs reflect actual ownership after the refactor, not intended future state.

## Tests (add these)

### Backend tests
- New: `tests/python/runtime/test_command_policy_contract.py`
  - validates canonical policy mapping by command family and mode.
- Extend: `tests/python/runtime/test_cli_router_parity.py`
  - parser contract remains unchanged while policy ownership moves.
- Extend: `tests/python/runtime/test_engine_runtime_dispatch.py`
  - dispatch uses stable collaborator interfaces rather than runtime-private breadth.
- Extend: `tests/python/startup/test_support_module_decoupling.py`
  - support modules operate on protocol-backed stubs only.
- Extend: `tests/python/runtime/test_cutover_gate_truth.py`
  - runtime-readiness enforcement remains consistent across start/resume/doctor.
- Extend: `tests/python/runtime/test_engine_runtime_command_parity.py`
  - preserve doctor payloads, cutover events, and runtime-readiness artifact behavior.
- Extend: `tests/python/state/test_state_repository_contract.py`
  - explicit compat-mode and pointer fallback coverage.
- Extend: `tests/python/state/test_state_shell_compatibility.py`
  - preserve shell-state parsing and pointer-loading behavior.
- Extend: `tests/python/state/test_state_action_orchestrator_logs.py`
  - logs/health/errors continue to work through narrow collaborators.
- Extend: `tests/python/planning/test_planning_worktree_setup.py`
  - worktree sync and plan archiving remain stable under refactored planning services.

### Frontend tests
- None required as a dedicated frontend stream, but UI-adjacent runtime interaction contracts must remain covered by existing Python tests around terminal/backend behavior.

### Integration/E2E tests
- Run full Python suite:
  - `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
- Run BATS suite:
  - `bats tests/bats/*.bats`
- Add or retain targeted runtime end-to-end checks for:
  - doctor/cutover truth
  - start/resume parity
  - actions parity
  - runtime truth health reporting

## Observability / logging
- Preserve current event names and core fields for:
  - `startup.phase`
  - `resume.phase`
  - `state.reconcile`
  - `cutover.gate.fail_reason`
  - `cutover.gate.evaluate`
  - `ui.spinner.lifecycle`
  - `artifacts.runtime_readiness_report`
- Add contract assertions where missing in `tests/python/debug/test_debug_event_contract.py` and related debug suites.
- Ensure any new policy/core/effects layers keep event emission at the effects layer so pure logic stays testable without event side effects.

## Rollout / verification

### Rollout strategy
- Land this refactor as a sequence of small, green batches, not a single branch-sized rewrite.
- Freeze unrelated runtime PRs while each major phase is landing, especially parser/startup/resume/state-repository work.
- Use compatibility adapters to allow old and new collaborators to coexist temporarily.

### Batch order
1. Governance alignment and characterization tests.
2. Command-policy extraction.
3. Runtime protocol/context expansion.
4. Startup split.
5. Resume split.
6. Action/state orchestrator migration.
7. Doctor/governance service extraction.
8. State repository/internal contract cleanup.
9. Planning/worktree split.
10. Runtime facade shrink and doc/inventory updates.

### Verification commands
- `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
- `bats tests/bats/*.bats`
- `./.venv/bin/python scripts/release_shipability_gate.py --repo .`
- Targeted suites per phase before and after each structural move.

### Rollback strategy
- Keep delegating wrappers in `PythonEngineRuntime` until all consumers of a moved seam are updated.
- If a phase breaks behavior, revert that batch only; do not continue with downstream phases until the seam is green again.
- Do not change state format and compatibility behavior in the same change set as command-policy or orchestrator extraction.

## Definition of done
- `PythonEngineRuntime` no longer rebinds domain behavior as a large private API surface.
- Command policy is represented once in a dedicated module and consumed consistently by parser/dispatch/orchestrators.
- Startup, resume, action, state, doctor, and planning flows depend on explicit collaborator interfaces rather than `runtime: Any` and private runtime methods.
- Runtime readiness, cutover truth, shipability, and inventory expectations are internally consistent and pass.
- Full Python unit suite passes.
- Full BATS suite passes.
- Developer docs describe the real runtime ownership model rather than an aspirational future state.

## Risk register
- High: hidden coupling to runtime-private helpers may surface only after protocol migration.
  - Mitigation: characterize first; migrate one orchestrator family at a time.
- High: readiness and retirement governance drift can produce false confidence or false failures.
  - Mitigation: align contracts/tests before structural refactor.
- High: state repository fallback behavior is compatibility-critical and easy to simplify incorrectly.
  - Mitigation: preserve on-disk schema; isolate compat logic without changing semantics first.
- Medium: startup/resume side effects are intertwined with UI and eventing, so behavior-preserving extraction is easy to underestimate.
  - Mitigation: separate policy/core/effects explicitly and preserve event contracts.
- Medium: planning/worktree flows contain broad fallback behavior around interactive selection.
  - Mitigation: make fallback semantics explicit before refactoring the terminal path.

## Open questions
- None that block implementation planning. If implementation later requires changing persisted state schema, shell-retirement criteria, or runtime planning root semantics, that should be scoped as follow-up work rather than folded into this refactor.
