# Envctl Deep Refactor Remaining Orchestrator Work

## Context and objective

The previous task, now archived as `OLD_TASK_2.md`, was a broad "Envctl Deep
Codebase Refactor" plan. The last implementation pass completed several
ownership slices and opened PR #247:

- `f5c60a9 Introduce plan-agent launch intent boundary`
- `1f52d2c Split plan-agent intent tests by owner`
- `088d19d Move self-destruct worktree helpers to action owner`
- `5914614 Move action target resolution to target support`

Those commits are useful progress, but they do not complete the full deep
refactor definition of done. This task must finish the remaining refactor
end-to-end: reduce the largest orchestrators into clear coordination layers,
complete owner modules and focused tests for each major runtime area, preserve
all public envctl behavior, and run the required contract/release validation
before final PR handoff.

Authoritative implementation target: complete every remaining requirement below
inside this worktree. Do not treat PR #247 as complete for the original broad
task; treat it as the starting point for the remaining work.

## Remaining requirements (complete and exhaustive)

1. Thin `PythonEngineRuntime` into explicit runtime delegates.
   - Group remaining runtime facade methods by owner:
     dispatch/help, project/state resolution, lifecycle start/resume/stop,
     action command entry points, debug/doctor/release-gate commands,
     dashboard/interactive commands, service helpers, hook bridging, readiness,
     truth/state helpers, prompt install/utility commands, and artifact paths.
   - Move cohesive method clusters into existing `runtime/engine_runtime_*`
     support modules where an owner already exists.
   - Add new runtime owner modules only when no existing module has a clear
     responsibility.
   - Keep `PythonEngineRuntime` as the public CLI facade and compatibility
     object, but make it construction/delegation focused.
   - Preserve command dispatch behavior, exit status, help/config output,
     generated runtime feature inventory, and compatibility imports.
   - Add focused tests around facade/delegate boundaries so route selection,
     output shape, and exit codes cannot drift.

2. Decompose startup orchestration by lifecycle phase.
   - Extract plan-agent worktree preparation and launch handoff from
     `StartupOrchestrator` into a startup/planning coordinator with explicit
     input and result objects.
   - Extract restart/reuse/pre-stop policy into a startup policy module.
   - Extract success, degraded, and failure finalization into a finalizer module
     that owns user-facing summaries and debug-report references.
   - Extract requirement and service startup sequencing into service/bootstrap
     coordinators while preserving readiness and truth reconciliation.
   - Keep `StartupOrchestrator.execute` as the main sequence owner, but make it
     read as high-level orchestration rather than low-level launch/rendering
     logic.
   - Preserve tests for degraded handoff, plan-agent launch skip/resume,
     disabled modes, startup logs, state truth, restart behavior, and service
     readiness.

3. Finish action command decomposition.
   - Keep the completed action target and self-destruct worktree owner modules:
     `actions/action_target_support.py` and `actions/action_worktree_runner.py`.
   - Move `test` action execution, failed-test manifest handling, failed-test
     summary formatting, and suite overview printing into action/test owner
     modules.
   - Move `migrate` command resolution, environment hints, migration logs,
     compact failure output, result records, symbols, and result summary
     rendering into an action/migrate owner module.
   - Move project action environment/replacement construction, success/failure
     handlers, artifact persistence, report writing, PR cache clearing, and
     git-state summary helpers into reusable project-action owner modules.
   - Keep `ActionCommandOrchestrator` as the compatibility entry point, with
     each route delegating to focused helpers.
   - Preserve public behavior for `test`, `pr`, `commit`, `review`, `migrate`,
     `delete-worktree`, `blast-worktree`, and `self-destruct-worktree`.
   - Split `tests/python/actions/test_actions_parity.py` into smaller
     action-owned suites as each production seam is created, preserving all
     assertions and fixture behavior.

4. Separate planning worktree responsibilities.
   - Split `planning/worktree_domain.py` by owner:
     selection/menu/memory, worktree sync/create/delete, provenance and
     `MAIN_TASK.md` seeding, git hook policy, fresh AI worktree protection, and
     code-intelligence setup for Serena/CGC.
   - Keep public functions stable during the first pass by delegating behind
     compatibility wrappers.
   - Preserve strict write boundaries: plan operations may edit only the current
     checked-out worktree or generated plan worktrees.
   - Preserve Serena and CGC setup behavior, repo-local ignores, generated
     context selection, `.envctl-state/code-intelligence.json`, and
     `.envctl-state/worktree-provenance.json` compatibility.
   - Add tests that fail on accidental sibling-worktree writes, hook-policy
     drift, task seeding drift, and code-intelligence metadata drift.

5. Finish shared plan-agent transport vocabulary and coverage.
   - Keep the completed `planning/plan_agent/intent.py` selection boundary.
   - Extend shared vocabulary beyond basic transport/CLI/readiness to include
     prompt preset, command preview, session identity, failure reason, recovery
     guidance, and skipped/resumed launch context.
   - Route common option mapping and result rendering through shared helpers
     while keeping transport-specific modules for `cmux`, `tmux`, `omx`,
     OpenCode/Codex behavior, Superset, and recovery.
   - Add or split focused tests that exercise the same option matrix across:
     `--cmux`, `--tmux`, `--omx`, `--codex`, `--opencode`, `--ulw`,
     `--no-ulw-loop`, `--new-session`, `--headless`, direct-prompt behavior,
     skipped launches, resumed launches, and failure diagnostics.
   - Preserve OpenCode readiness failures with enough context to diagnose active
     command, expected prompt state, transport, and timeout.
   - Regenerate and compare `contracts/runtime_feature_matrix.json` only if the
     declared feature inventory intentionally changes.

6. Break requirements adapters into lifecycle components, starting with
   Supabase.
   - Split `requirements/supabase.py` into smaller components for
     configuration/env resolution, Docker/process lifecycle, health/readiness,
     database setup, QA/auth user setup, repair/reinit, and summary reporting.
   - Keep the public adapter API stable for callers in startup/runtime code.
   - Preserve real contract behavior for existing managed dependency flows,
     env projection, repair paths, user setup, database setup, and readiness
     status.
   - Apply the same pattern to other requirement adapters only when it reduces
     actual complexity without hiding important behavior behind generic
     abstractions.
   - Add adapter-level tests proving behavior before and after each split.

7. Split remaining oversized tests by behavior owner.
   - Continue splitting giant tests only after the related production seam
     exists.
   - Required target files to reduce or split by owner:
     `tests/python/planning/test_plan_agent_launch_support.py`,
     `tests/python/actions/test_actions_parity.py`,
     `tests/python/runtime/test_engine_runtime_real_startup.py`,
     `tests/python/requirements/test_requirements_adapters_real_contracts.py`,
     and `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`.
   - Preserve every behavior assertion, fixture contract, and regression case.
   - Keep test names descriptive and colocated with their owner module.

8. Tighten structure, generated contracts, and release checks.
   - Add or update lightweight structure/import-cycle checks only after the
     relevant production boundaries exist.
   - Make structural failures actionable by naming the owning module family and
     acceptable compatibility facades.
   - Re-run generators only when behavior or feature inventory changes:
     `scripts/generate_runtime_feature_matrix.py`,
     `scripts/generate_python_runtime_gap_report.py`, and
     `scripts/generate_python_engine_parity_manifest.py`.
   - Compare generated output to checked-in JSON artifacts and commit artifact
     updates only when intentional.
   - Keep `scripts/release_shipability_gate.py`, ruff, and the full Python test
     suite passing before final handoff.

9. Update contributor-facing documentation after each major extraction.
   - Keep `docs/reference/python-engine-architecture.md`,
     `docs/developer/module-layout.md`, and `AGENTS.md` aligned with actual
     owner modules and tooling guidance.
   - Preserve guidance that Serena is used for symbol navigation/reference
     checks, CGC is used for broad graph analysis, and native search is used for
     literal strings/config/docs.
   - Add short "how to change this area" notes for runtime, startup, actions,
     planning/worktrees, plan-agent transports, requirements, and dashboard/UI
     once each area has a stable owner boundary.

## Gaps from prior iteration (mapped to evidence)

Fully implemented in PR #247 / commits `f5c60a9`, `1f52d2c`, `088d19d`, and
`5914614`:

- Architecture inventory exists at `docs/reference/python-engine-architecture.md`
  with owner table, invariants, plan-agent vocabulary, and tool guidance.
- `docs/reference/README.md` links the architecture inventory.
- `docs/developer/module-layout.md` now records owner guidance for plan-agent
  intent, worktree action helpers, and action target resolution.
- Plan-agent transport/CLI/readiness intent moved to
  `python/envctl_engine/planning/plan_agent/intent.py`.
- `resolve_plan_agent_launch_config` consumes the shared plan-agent intent.
- Intent option-matrix tests live in
  `tests/python/planning/test_plan_agent_intent.py`.
- Self-destruct worktree handling and helper spawning moved to
  `python/envctl_engine/actions/action_worktree_runner.py`.
- Action target/project-scope resolution moved to
  `python/envctl_engine/actions/action_target_support.py`.
- Targeted action and planning tests passed locally, and PR #247 GitHub checks
  passed for `ruff`, `build & shipability`, and `pytest`.

Partially implemented:

- Step 1 architecture inventory is present, but it must be kept updated as
  remaining owner modules are created.
- Step 4 action decomposition has completed target resolution and self-destruct
  worktree ownership only. Test execution, migrate behavior, project action
  persistence, summaries, and test splitting remain.
- Step 6 plan-agent shared vocabulary has completed only basic launch intent.
  Command preview, session identity, failure reason, recovery guidance,
  skipped/resumed context, and complete option-matrix splitting remain.
- Step 8 giant-test splitting has begun only for plan-agent intent. The large
  launch, action parity, runtime startup, requirements, and dashboard tests
  remain mostly intact.

Not implemented:

- Runtime facade thinning.
- Startup lifecycle decomposition.
- Planning worktree-domain decomposition.
- Supabase requirements adapter decomposition.
- Requirements adapter component tests beyond existing coverage.
- Dashboard orchestrator/test decomposition.
- New structural guardrails for final owner boundaries.
- Generated contract regeneration/comparison for final state.
- Full release shipability gate and full Python suite after all remaining
  refactor work is complete.

## Acceptance criteria (requirement-by-requirement)

- Runtime facade acceptance:
  - `PythonEngineRuntime` is materially smaller and delegates grouped behavior
    to owner modules.
  - Runtime dispatch/help/config/action/lifecycle/debug/dashboard/service/truth
    behavior remains unchanged in focused runtime tests and generated feature
    inventory checks.

- Startup acceptance:
  - Startup phase modules own policy, plan-agent handoff, service/requirement
    sequencing, and finalization.
  - Startup tests continue to prove degraded handoff, skip/resume, disabled
    modes, logs, state truth, restart/reuse, and readiness behavior.

- Action acceptance:
  - `ActionCommandOrchestrator` delegates target resolution, worktree actions,
    test action details, migrate details, and project-action persistence to
    owner modules.
  - Action tests prove all public action command behavior and the split test
    suites preserve the previous parity assertions.

- Planning/worktree acceptance:
  - `worktree_domain.py` no longer owns unrelated selection, sync/create/delete,
    provenance/task seeding, hook policy, fresh AI protection, and
    code-intelligence internals directly.
  - Worktree tests prove no sibling worktree writes, no hook-policy drift, no
    task seeding drift, and no code-intelligence metadata drift.

- Plan-agent acceptance:
  - Shared vocabulary covers transport, CLI, readiness, preset, command preview,
    session identity, failure reason, recovery guidance, skipped/resumed
    context, direct prompts, and ULW/new-session/headless interactions.
  - Focused tests prove the full transport option matrix without relying only on
    the giant launch-support suite.

- Requirements acceptance:
  - Supabase adapter behavior is preserved through smaller components.
  - Requirements tests prove real adapter contracts, readiness, repair/reinit,
    DB/user setup, env/config behavior, and startup integration.

- Test/documentation/contract acceptance:
  - Oversized tests are split by owner where production seams exist.
  - Documentation names final owner modules and tooling boundaries.
  - Runtime feature matrix, Python runtime gap report, parity manifest,
    release shipability gate, ruff, and the full Python test suite pass before
    final PR handoff.

## Required implementation scope (frontend/backend/data/integration)

- Backend/Python engine:
  - Refactor Python modules under `python/envctl_engine/runtime/`,
    `python/envctl_engine/startup/`, `python/envctl_engine/actions/`,
    `python/envctl_engine/planning/`, `python/envctl_engine/requirements/`, and
    `python/envctl_engine/ui/` as required by the remaining requirements.
- Tests:
  - Add and split tests under `tests/python/runtime`, `tests/python/startup`,
    `tests/python/actions`, `tests/python/planning`,
    `tests/python/requirements`, `tests/python/ui`, and
    `tests/python/shared` as owner seams are created.
- Docs/contracts:
  - Update reference/developer docs and generated contracts only when the
    implementation changes the maintained source of truth.
- Frontend:
  - None expected unless dashboard/UI refactor touches browser-visible behavior.
- Data/migrations:
  - None expected. Preserve existing state artifacts and schemas.
- Runtime services:
  - Not required for pure Python refactor slices. Use envctl runtime scopes only
    if a change crosses runtime/service behavior and cannot be proven by unit or
    integration tests.

## Required tests and quality gates

Run targeted tests after each ownership area:

- Runtime:
  `uv run --extra dev pytest -q tests/python/runtime tests/python/test_runtime_feature_inventory.py`
- Startup:
  `uv run --extra dev pytest -q tests/python/startup tests/python/runtime/test_engine_runtime_real_startup.py`
- Actions:
  `uv run --extra dev pytest -q tests/python/actions`
- Planning and plan-agent:
  `uv run --extra dev pytest -q tests/python/planning`
- Requirements:
  `uv run --extra dev pytest -q tests/python/requirements`
- UI/dashboard:
  `uv run --extra dev pytest -q tests/python/ui`
- Shared structure/import checks:
  `uv run --extra dev pytest -q tests/python/shared/test_structure_layout.py tests/python/startup/test_support_module_decoupling.py tests/python/shared/test_utility_consolidation_contract.py`
- Static checks:
  `uv run --extra dev ruff check python tests scripts`

Before final handoff, run:

- Runtime feature matrix generator comparison using the checked-in timestamp.
- Python runtime gap report generator comparison using the checked-in timestamp.
- Python engine parity manifest generator comparison using the checked-in
  timestamp, if the manifest generator exists in this checkout.
- `uv run --extra dev python scripts/release_shipability_gate.py`.
- Full Python test suite with `uv run --extra dev pytest -q tests/python`.
- Open or update the PR, inspect unresolved review threads, and wait for all
  required GitHub checks to pass.

## Edge cases and failure handling

- Dynamic CLI dispatch can hide call sites. Preserve behavior-level dispatch
  tests and generated feature matrix checks for every runtime move.
- Moving user-facing summaries can change text. Preserve snapshot-like tests for
  launch guidance, prompt install output, startup failure summaries, migrate
  hints, action reports, and release-gate messages.
- Generated contracts can drift accidentally. Regenerate only intentionally and
  compare generator output before committing.
- Long-lived compatibility facades can become permanent. Document each facade's
  owner and remove redundant wrappers once call sites are updated.
- Broad refactors can conflict with active plan-agent work. Use small commits by
  ownership area and avoid touching unrelated files in a commit.
- Serena and CGC indexes can lag after structural moves. Let Serena refresh
  automatically, run `serena project health-check` if symbol results look
  stale, and refresh CGC with `cgc index . --context Envctl` after major
  structural changes.
- Worktree tasks must not mutate sibling worktrees unless the feature being
  tested intentionally creates or deletes generated envctl worktrees.

## Definition of done

- All remaining requirements above are fully implemented end-to-end.
- The largest orchestrators are thin coordination layers or explicitly
  documented compatibility facades.
- Each major runtime area has an obvious owner module and focused tests.
- Plan-agent transport flags and readiness behavior are covered by shared
  vocabulary and focused option-matrix tests.
- Supabase requirements behavior is preserved behind smaller components.
- Giant tests are split by behavior owner without losing assertions.
- Runtime feature matrix, Python runtime gap report, parity manifest,
  release shipability gate, ruff, and the full Python test suite pass.
- Documentation reflects final ownership boundaries and tooling guidance.
- The implementation is committed, pushed, PR review threads are inspected and
  addressed, and required GitHub checks pass before final handoff.
