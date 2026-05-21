# Envctl Remaining Runtime Orchestrator Decomposition

## Context and objective

The previous deep-refactor iteration is partially complete. Preserve the completed planning/worktree ownership slices and
finish the remaining refactor end-to-end in this checkout.

Current evidence shows the branch is reconciled with the worktree provenance source ref:

- `.envctl-state/worktree-provenance.json` identifies `source_ref` as
  `origin/codex/reuse-cgc-worktree-context`.
- `git merge-base HEAD origin/codex/reuse-cgc-worktree-context` resolves to
  `dc131e8461c70657c63e8faaea72f12a357de62e`, the same commit currently at that source ref.
- Committed divergence from that base contains the deep-refactor commits only:
  `67f588b`, `6a76bbe`, `ddcf515`, `c3bdb24`, `2e9fe27`, `628aa9a`, and `9991180`.

Completed and preserved planning ownership slices:

- `planning/worktree_code_intelligence.py` owns generated-worktree Serena/CGC setup.
- `planning/worktree_provenance.py` owns provenance, source-branch resolution, and active fresh-AI worktree protection.
- `planning/worktree_git_hooks.py` owns `ENVCTL_WORKTREE_GIT_HOOKS` parsing and disabled/inherit policy checks.
- `planning/worktree_main_task.py` owns generated worktree `MAIN_TASK.md` seeding, plan archival into `todo/done`,
  and numeric iteration gap selection.
- `planning/worktree_project_catalog.py` owns project candidate discovery, cleanup, and sorting for generated
  worktrees.
- `planning/worktree_selection_memory.py` owns plan selection memory path resolution, load/save behavior, and initial
  selected-count calculation.
- `planning/worktree_shared_artifacts.py` owns generated-worktree shared-artifact compatibility links.
- `planning/worktree_creation_recovery.py` owns partial worktree-add recovery and placeholder fallback behavior.
- `planning/worktree_plan_selection.py` owns fresh-AI plan-count adjustment, launch transport selection, and
  keep-plan flag/config parsing.
- `planning/worktree_creation_commands.py` owns git worktree-add branch naming, branch existence checks, start-point
  selection, and command execution.
- `planning/worktree_identity.py` owns the shared generated-worktree identity so branch names and envctl project names
  remain identical.
- `planning/worktree_planning_menu.py` owns interactive planning menu invocation, result normalization, fallback, and
  terminal-state cleanup.
- `planning/worktree_setup_entries.py` owns setup flag parsing, include-token resolution, and single/multi setup-entry
  application.
- `planning/worktree_sync_deletion.py` owns excess plan-worktree deletion ordering, fresh-AI protection skips, blast
  cleanup warnings, and delete failure propagation.
- `planning/worktree_domain.py` remains a compatibility facade for those extracted helpers.

Fully implement the remaining decomposition work without changing CLI semantics, persistent state formats, generated
contract formats, prompt preset behavior, plan-agent launch behavior, startup logs, debug reports, release-gate behavior,
or user-facing output except where a compatibility-preserving refactor requires a tested update.

All file edits must stay inside this checkout. Do not modify sibling worktrees or paths outside the current repo root.
The local `.envctl-state/worktree-provenance.json` change is state metadata and must stay out of unrelated
implementation commits unless a task explicitly requires changing it.

## Remaining requirements (complete and exhaustive)

1. Finish planning/worktree responsibility separation.
   - Keep the completed owner modules listed above as the implementation owners for their behavior.
   - Continue reducing `planning/worktree_domain.py` by extracting the remaining responsibilities into focused planning
     owner modules:
     - the remaining spinner-wrapped setup-worktree selection coordinator,
     - plan selection and prompt parsing beyond fresh-AI/keep-plan helpers,
     - worktree sync/create orchestration and deletion result summarization beyond git worktree-add command
       construction.
   - Keep public helper names and orchestrator call sites stable until callers are moved safely.
   - Preserve the strict boundary that planning operations only write inside the current checkout or generated plan
     worktrees.
   - Add focused tests for every extracted owner, including sibling-worktree safety, fresh-AI protection, provenance
     preservation, git-hook policy behavior, code-intelligence setup, `MAIN_TASK.md` seeding, plan archival, and
     iteration selection.

2. Thin `PythonEngineRuntime` into explicit runtime delegates.
   - Reduce `python/envctl_engine/runtime/engine_runtime.py` from a broad facade into construction, command dispatch,
     compatibility wrappers, and delegation to focused owner modules.
   - Group and move cohesive clusters into existing `runtime/engine_runtime_*_support.py` modules or new owner modules
     where no clear owner exists:
     - dispatch/help and command policy,
     - project resolution and target selection,
     - lifecycle start/resume/stop and cleanup,
     - action command entry points,
     - debug, doctor, release-gate, and generated contract helpers,
     - dashboard and interactive commands,
     - service command helpers and environment overlays,
     - hook bridging,
     - state truth, readiness, and listener reconciliation.
   - Preserve `PythonEngineRuntime` as the public CLI/test facade.
   - Preserve command routing behavior, exit statuses, output shapes, state writes, and generated runtime feature matrix
     contents unless a generator output change is intentional and committed with evidence.
   - Add focused runtime facade/delegate tests so route selection, exit status, and output cannot drift.

3. Decompose startup orchestration by lifecycle phase.
   - Extract plan-agent worktree preparation and launch handoff from `startup/startup_orchestrator.py` into a narrow
     planning/startup coordinator with explicit input/result objects.
   - Extract restart/reuse/pre-stop policy into a startup policy module.
   - Extract success, degraded, and failure finalization into helpers that own user-facing summaries and debug report
     references.
   - Extract requirement and service startup sequencing into a service bootstrap coordinator while preserving readiness
     and truth reconciliation semantics.
   - Keep `StartupOrchestrator.execute` as the readable high-level sequence owner.
   - Preserve behavior for degraded handoff, plan-agent launch skip/resume, disabled modes, startup logs, state truth,
     runtime startup integration, debug report references, and final summaries.

4. Split action command orchestration into action-owned helpers.
   - Move remaining target resolution and project scope selection logic into action target helpers.
   - Move `test` action execution and failed-test summary formatting into test action helpers.
   - Move `migrate` hints, migration logs, and migration result reporting into migrate action helpers.
   - Move remaining self-destruct worktree handling into worktree action helpers with explicit safety checks.
   - Move project action environment/replacement/artifact persistence into reusable project action support.
   - Keep `ActionCommandOrchestrator` as the compatibility entry point.
   - Split `tests/python/actions/test_actions_parity.py` into action-owned suites as production seams are extracted,
     preserving fixtures and assertion intent.

5. Normalize plan-agent transport concepts and option-matrix coverage.
   - Introduce or complete shared vocabulary for launch intent, selected surface, prompt preset, readiness expectation,
     command preview, session identity, failure reason, and recovery guidance.
   - Keep transport-specific process/session behavior in the existing transport modules:
     `planning/plan_agent/cmux_transport.py`, `tmux_transport.py`, `omx_transport.py`, `superset_transport.py`,
     OpenCode/Codex launch paths, workflow helpers, and recovery modules.
   - Route common option mapping and result rendering through shared helpers.
   - Add tests that exercise the same option matrix across `--cmux`, `--tmux`, `--omx`, `--codex`, `--opencode`,
     `--ulw`, `--no-ulw-loop`, `--new-session`, `--headless`, direct-prompt behavior, skipped launches, and resumed
     launches.
   - Keep OpenCode-specific readiness failures observable with active command, expected prompt state, transport, timeout,
     and recovery guidance.
   - Regenerate and compare `contracts/runtime_feature_matrix.json` only if declared feature inventory changes.

6. Break requirements adapters into lifecycle components, starting with Supabase.
   - Split `requirements/supabase.py` into smaller owners for:
     - configuration and env resolution,
     - Docker/process lifecycle,
     - health and readiness checks,
     - database setup,
     - QA/auth user setup,
     - repair and reinit,
     - summary reporting.
   - Keep the existing adapter API stable for startup and runtime callers.
   - Add adapter-level tests proving contract behavior before and after the split.
   - Apply the same component pattern to other adapters only where it reduces complexity without hiding behavior behind
     generic abstractions.

7. Split dashboard orchestration and oversized UI tests by behavior owner.
   - Reduce `ui/dashboard/orchestrator.py` to a coordination layer with explicit owners for backend resolution,
     rendering, restart selection, PR flow, command parsing, and terminal interaction.
   - Split `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` by behavior owner once production seams are
     in place.
   - Preserve dashboard rendering contracts, restart selector behavior, backend selection, PR flow behavior, and
     terminal command semantics.

8. Split remaining oversized tests after production seams exist.
   - Split tests by behavior owner, not arbitrary line count:
     - plan-agent launch options,
     - transport readiness,
     - action parity,
     - runtime startup,
     - requirement adapter contracts,
     - dashboard restart selector behavior.
   - Move tests in the same commit as the production extraction they protect where practical.
   - Preserve existing fixtures, assertions, and regression coverage.
   - Add structure/import guards only after realistic module boundaries exist, and include explicit waivers for
     legitimate compatibility facades.

9. Tighten generated contracts, docs, and release checks.
   - Keep `docs/reference/python-engine-architecture.md` aligned after each major extraction.
   - Add or update contributor-facing "how to change this area" notes for runtime, startup, actions, planning,
     transports, requirements, and dashboard code as owner modules become real.
   - Re-run generated contract scripts only when behavior or declared feature inventory intentionally changes:
     `scripts/generate_runtime_feature_matrix.py`,
     `scripts/generate_python_runtime_gap_report.py`,
     `scripts/generate_python_engine_parity_manifest.py`.
   - Compare generated JSON artifacts and commit updates only when intentional.
   - Keep import-cycle and structure-layout failures actionable by pointing to the owning module family.

10. Preserve all compatibility and persistent contracts.
    - Do not redesign the CLI or remove compatibility commands.
    - Do not resurrect the old shell runtime.
    - Do not change prompt preset semantics, runtime state schemas, generated contract formats, `.envctl-state`
      artifact shape, startup logs, debug reports, plan-agent launch semantics, release-gate expectations, or
      user-facing command output except where a compatibility-preserving update is explicitly required by the refactor.
    - Do not make application-service, infrastructure, database, or migration changes.

## Gaps from prior iteration (mapped to evidence)

Fully implemented:

- Branch/source reconciliation is complete: source ref `origin/codex/reuse-cgc-worktree-context` resolves to
  `dc131e8461c70657c63e8faaea72f12a357de62e`, and `git merge-base HEAD origin/codex/reuse-cgc-worktree-context`
  returned that same commit.
- Architecture inventory exists at `docs/reference/python-engine-architecture.md` and is linked from
  `docs/reference/README.md`.
- Generated-worktree code-intelligence setup is extracted to
  `python/envctl_engine/planning/worktree_code_intelligence.py`.
- Worktree provenance, branch resolution, and active fresh-AI worktree protection helpers are extracted to
  `python/envctl_engine/planning/worktree_provenance.py`.
- Worktree git-hook policy resolution is extracted to `python/envctl_engine/planning/worktree_git_hooks.py`.
- Generated worktree `MAIN_TASK.md` seeding, plan archival, and numeric iteration gap selection are extracted to
  `python/envctl_engine/planning/worktree_main_task.py`.
- Project candidate discovery, cleanup, and sorting are extracted to
  `python/envctl_engine/planning/worktree_project_catalog.py`.
- Plan selection memory load/save and initial selected-count calculation are extracted to
  `python/envctl_engine/planning/worktree_selection_memory.py`.
- Generated-worktree shared-artifact compatibility links are extracted to
  `python/envctl_engine/planning/worktree_shared_artifacts.py`.
- Partial worktree-add recovery and placeholder fallback behavior are extracted to
  `python/envctl_engine/planning/worktree_creation_recovery.py`.
- Fresh-AI plan-count adjustment, launch transport selection, and keep-plan flag/config parsing are extracted to
  `python/envctl_engine/planning/worktree_plan_selection.py`.
- Git worktree-add branch naming, branch existence checks, start-point selection, and command execution are extracted to
  `python/envctl_engine/planning/worktree_creation_commands.py`.
- Generated-worktree project and branch identity is centralized in
  `python/envctl_engine/planning/worktree_identity.py`.
- Interactive planning menu invocation, result normalization, fallback behavior, and terminal-state cleanup are
  extracted to `python/envctl_engine/planning/worktree_planning_menu.py`.
- Setup flag parsing, include-token resolution, and single/multi setup-entry application are extracted to
  `python/envctl_engine/planning/worktree_setup_entries.py`.
- Excess plan-worktree deletion ordering, fresh-AI protection skips, blast cleanup warnings, and delete failure
  propagation are extracted to `python/envctl_engine/planning/worktree_sync_deletion.py`.
- Structure guards exist in `tests/python/shared/test_structure_layout.py` for the planning owner modules.
- Focused planning tests exist for `worktree_git_hooks.py`, `worktree_main_task.py`, and
  `worktree_creation_commands.py`, `worktree_creation_recovery.py`, `worktree_identity.py`,
  `worktree_plan_selection.py`,
  `worktree_planning_menu.py`, `worktree_project_catalog.py`, `worktree_selection_memory.py`, and
  `worktree_setup_entries.py`, `worktree_sync_deletion.py`, and `worktree_shared_artifacts.py`.
- Most recent reported validation:
  - `uv run --extra dev pytest -q tests/python/planning/test_worktree_main_task.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_worktree_main_task_has_owned_module`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/planning/test_worktree_selection_memory.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_worktree_selection_memory_has_owned_module`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/planning tests/python/shared/test_structure_layout.py tests/python/startup/test_support_module_decoupling.py tests/python/shared/test_utility_consolidation_contract.py`
    -> `331 passed, 28 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/planning tests/python/planning tests/python/shared/test_structure_layout.py docs/reference/README.md docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.

Partially implemented:

- Planning/worktree split is started, but `worktree_domain.py` still owns the spinner-wrapped setup coordinator,
  prompt parsing beyond the extracted helpers, and sync/create orchestration plus deletion result summarization.
- Runtime support modules already exist under `runtime/engine_runtime_*_support.py`, but
  `runtime/engine_runtime.py` is still about 1,679 lines and still owns many delegate-worthy responsibilities.
- Startup support modules already exist, but `startup/startup_orchestrator.py` is still about 2,272 lines and still owns
  too many lifecycle phases.
- Actions have support modules, but `actions/action_command_orchestrator.py` is still about 2,880 lines and
  `tests/python/actions/test_actions_parity.py` is still about 6,869 lines.
- Architecture docs describe an ownership map, but they do not yet reflect final ownership boundaries for runtime,
  startup, actions, requirements, transports, dashboard, and remaining planning/worktree code.

Not implemented:

- `PythonEngineRuntime` has not been reduced to a thin facade.
- `StartupOrchestrator.execute` has not been decomposed into lifecycle-phase owners.
- Action command orchestration and action parity tests have not been fully split by action owner.
- Plan-agent shared transport vocabulary and full option-matrix tests are not complete;
  `tests/python/planning/test_plan_agent_launch_support.py` is still about 7,415 lines.
- Supabase adapter decomposition is not complete; `requirements/supabase.py` is still about 3,348 lines.
- Dashboard orchestration/test split is not complete; `ui/dashboard/orchestrator.py` is still about 2,209 lines and
  `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` is still about 3,494 lines.
- Generated contract generation/compare pass, full Python test suite, release shipability gate, and final GitHub check
  confirmation have not been completed for the full refactor.

## Acceptance criteria (requirement-by-requirement)

- `planning/worktree_domain.py` is reduced to a documented compatibility facade and remaining planning/worktree
  responsibilities are owned by focused modules with targeted tests.
- `PythonEngineRuntime` is reduced to construction, dispatch, delegation, and compatibility wrappers, with runtime
  delegate tests covering route selection, exit statuses, and output shape.
- `StartupOrchestrator.execute` remains the high-level sequence owner while lifecycle phases are delegated to focused
  startup/planning helpers with preserved degraded, disabled, resume, truth, and finalization behavior.
- `ActionCommandOrchestrator` remains the compatibility entry point while each action route delegates to action-owned
  helpers, and action tests are split without losing parity coverage.
- Plan-agent launch vocabulary is shared where behavior is common, transport-specific code remains transport-owned, and
  the full option matrix is covered by tests.
- Supabase adapter behavior is preserved behind smaller lifecycle/config/health/database/auth/repair/reporting pieces.
- Dashboard orchestration and restart-selector tests are split by behavior owner without changing UI behavior.
- Oversized tests are split only after corresponding production seams exist and existing assertions are preserved.
- Architecture docs, structure/import guards, and generated contracts reflect the final owner modules.
- Public CLI behavior, exit statuses, state artifacts, prompt install output, plan-agent launch behavior, generated
  contracts, release-gate behavior, startup logs, debug reports, and user-facing summaries are preserved.
- Targeted suites for each touched area pass, full Python tests pass, generated contract scripts have been run and
  compared, release shipability gate passes, and PR/GitHub check evidence is recorded.

## Required implementation scope (frontend/backend/data/integration)

- Backend/Python engine:
  - `python/envctl_engine/planning/`
  - `python/envctl_engine/runtime/`
  - `python/envctl_engine/startup/`
  - `python/envctl_engine/actions/`
  - `python/envctl_engine/requirements/`
  - `python/envctl_engine/ui/dashboard/`
  - `python/envctl_engine/state/` only if runtime/contract owner changes require it.
- Tests:
  - `tests/python/planning/`
  - `tests/python/runtime/`
  - `tests/python/startup/`
  - `tests/python/actions/`
  - `tests/python/requirements/`
  - `tests/python/ui/`
  - `tests/python/shared/`
- Docs/contracts:
  - `docs/reference/python-engine-architecture.md`
  - Relevant contributor/user docs when ownership guidance changes.
  - `contracts/*.json` only for intentional generated-output changes.
- Frontend:
  - None expected.
- Data/migrations:
  - None expected.
- Runtime services:
  - No application services are expected for normal validation of this refactor. If runtime validation is attempted and
    blocked by missing repo-local `.envctl` or lack of interactive TTY, report that exact blocker.

## Required tests and quality gates

Run targeted tests after each ownership slice:

- Planning/worktree:
  `uv run --extra dev pytest -q tests/python/planning tests/python/shared/test_structure_layout.py`.
- Runtime:
  `uv run --extra dev pytest -q tests/python/runtime tests/python/test_runtime_feature_inventory.py`.
- Startup:
  `uv run --extra dev pytest -q tests/python/startup tests/python/runtime/test_engine_runtime_real_startup.py`.
- Actions:
  `uv run --extra dev pytest -q tests/python/actions`.
- Requirements:
  `uv run --extra dev pytest -q tests/python/requirements`.
- UI/dashboard:
  `uv run --extra dev pytest -q tests/python/ui`.
- Shared structure/import:
  `uv run --extra dev pytest -q tests/python/shared/test_structure_layout.py tests/python/startup/test_support_module_decoupling.py tests/python/shared/test_utility_consolidation_contract.py`.
- Static check:
  `uv run --extra dev ruff check python tests scripts`.
- Generated contract checks:
  `uv run --extra dev python scripts/generate_runtime_feature_matrix.py`.
  `uv run --extra dev python scripts/generate_python_runtime_gap_report.py`.
  `uv run --extra dev python scripts/generate_python_engine_parity_manifest.py`.
  Compare resulting checked-in JSON artifacts and commit only intentional changes.
- Final gates:
  `uv run --extra dev pytest tests`.
  `uv run --extra dev python scripts/release_shipability_gate.py`.
  Push the branch, open/update PR #245 or its successor, inspect unresolved PR review threads, and wait for GitHub
  checks. If GitHub reports no checks, record the exact `gh`/API evidence instead of claiming CI passed.

## Edge cases and failure handling

- Dynamic CLI dispatch can hide call sites. Preserve behavior-level dispatch tests and generated feature matrix checks
  for every runtime route move.
- User-facing text can drift during extractions. Preserve assertions around launch guidance, prompt install output,
  failure summaries, debug report references, release-gate messages, startup summaries, and dashboard rendering.
- Generated contract files can drift during refactors. Regenerate intentionally and compare before committing.
- Compatibility wrappers can become permanent. Document remaining facades and remove redundant wrappers once call sites
  are safely moved.
- Planning/worktree changes must not write into sibling worktrees except generated plan worktrees selected by the
  operation.
- Fresh-AI worktree protection must continue to skip active generated worktrees during cleanup/delete flows.
- Supabase decomposition must preserve non-fatal repair/reinit behavior, QA/auth user setup semantics, readiness checks,
  and summary output.
- Dashboard restart selector behavior must remain stable across terminal/non-terminal and backend-resolution paths.
- Serena and CGC indexes can lag after structural moves. Use Serena for exact symbol navigation and diagnostics; use CGC
  context `Envctl` for broad graph checks. Run `serena project health-check` if symbol results look stale and refresh CGC
  with `cgc index . --context Envctl` after major structural changes if broad graph data is needed.
- Keep the current local `.envctl-state/worktree-provenance.json` edit out of unrelated implementation commits.

## Definition of done

- Every remaining requirement above is implemented end-to-end.
- `worktree_domain.py`, `engine_runtime.py`, `startup_orchestrator.py`, `action_command_orchestrator.py`,
  `requirements/supabase.py`, and `ui/dashboard/orchestrator.py` are thin coordination layers or explicitly documented
  compatibility facades with clear owner modules.
- Each major runtime area has focused owner modules and focused test suites.
- Plan-agent transport flags and readiness behavior are covered by a shared option matrix.
- Supabase requirements behavior is preserved behind smaller components.
- Dashboard orchestration and UI tests are split by behavior owner without losing coverage.
- Oversized tests are split by behavior without losing assertions or fixtures.
- Architecture docs, structure guards, import guards, and generated contracts reflect the final boundaries.
- `ruff`, targeted suites, full Python tests, generated contract checks, release shipability gate, and reported GitHub
  required checks pass or report exact no-check evidence.
- PR #245 or its successor is updated with final commits, validation evidence, and review-thread/check status.
