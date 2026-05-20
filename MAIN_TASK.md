# Envctl Deep Refactor Remaining Orchestrator Decomposition

## Context and objective

The prior `Envctl Deep Codebase Refactor` task is only partially implemented in this worktree. Preserve the completed
planning ownership slices and finish the remaining refactor end-to-end.

Current committed evidence on branch `refactoring_envctl_deep_codebase_refactor-4`:

- `67f588b Refactor worktree code intelligence setup`
  - Added `docs/reference/python-engine-architecture.md`.
  - Moved generated-worktree code-intelligence setup from `planning/worktree_domain.py` into
    `planning/worktree_code_intelligence.py`.
  - Added structure guards in `tests/python/shared/test_structure_layout.py`.
- `6a76bbe Move worktree provenance helpers`
  - Moved worktree provenance, branch resolution, and fresh-AI worktree protection helpers into
    `planning/worktree_provenance.py`.
  - Updated the architecture inventory and structure guards.

The objective of this next iteration is to complete the remaining deep refactor scope: reduce the largest orchestrators
to thin coordination layers or documented compatibility facades, give each major runtime area an obvious owner module and
focused tests, preserve public behavior and generated contracts, and run the required validation gates before handoff.

Do all file edits only inside this checkout. Do not modify sibling worktrees or paths outside this repo root.

## Remaining requirements (complete and exhaustive)

1. Reconcile branch base and current task state before further implementation.
   - The worktree provenance says `source_ref` is `origin/codex/reuse-cgc-worktree-context`, currently observed at
     `dc131e8`, while the committed refactor branch is based on merge base `a4a17bf`.
   - Rebase, merge, or otherwise reconcile with the current source ref before final validation unless repo evidence shows
     doing so would break the intended stacked PR shape.
   - Preserve the existing implementation commits' behavior while resolving any conflicts.
   - Keep the pre-existing `.envctl-state/worktree-provenance.json` state artifact out of unrelated implementation
     commits unless the task explicitly requires changing it.

2. Finish planning/worktree responsibility separation.
   - Keep `planning/worktree_code_intelligence.py` and `planning/worktree_provenance.py` as owners for their extracted
     behavior.
   - Continue splitting `planning/worktree_domain.py` along the remaining responsibilities:
     selection/menu/memory, worktree sync/create/delete, `MAIN_TASK.md` seeding, git hook policy, fresh AI worktree
     protection call sites, and generated worktree safety boundaries.
   - Keep public functions used by callers stable while moving implementations behind owner modules.
   - Preserve the strict boundary that plan operations only edit inside the current checkout or generated plan
     worktrees.
   - Add or update focused tests that make accidental sibling-worktree writes, provenance drift, code-intelligence
     drift, and git-hook policy drift fail early.

3. Thin `PythonEngineRuntime` into explicit runtime delegates.
   - Group methods by responsibility: dispatch/help, project resolution, lifecycle start/resume/stop, action command
     entry points, debug/doctor/release-gate commands, dashboard/interactive commands, service command helpers, hook
     bridging, truth/readiness helpers, and compatibility shims.
   - Move cohesive clusters into existing `runtime/engine_runtime_*_support.py` modules or new owner modules only where
     no clear owner exists.
   - Keep `PythonEngineRuntime` as the public CLI/test facade, but reduce it to construction, delegation, and documented
     compatibility wrappers.
   - Preserve command routing behavior in `runtime/command_router.py`, exit statuses, output shape, and generated runtime
     feature matrix contents unless a generator change is intentional and documented.
   - Add focused runtime facade/delegate tests so moved methods cannot silently change route selection, exit status, or
     output.

4. Decompose startup orchestration by lifecycle phase.
   - Extract plan-agent worktree preparation and launch handoff from `startup/startup_orchestrator.py` into a
     planning/startup coordinator with narrow input/result objects.
   - Extract restart/reuse/pre-stop policy into a startup policy module.
   - Extract success, degraded, and failure finalization into finalizer/renderer helpers that own user-facing summaries
     and debug report references.
   - Extract requirement and service startup sequencing into a service bootstrap coordinator while preserving readiness
     and truth reconciliation semantics.
   - Keep `StartupOrchestrator.execute` as the high-level sequence owner.
   - Preserve tests for degraded handoff, plan-agent launch skip/resume, disabled modes, startup logs, state truth, and
     runtime startup integration.

5. Split action command orchestration into action-owned helpers.
   - Move remaining target resolution and project scope selection logic into action target helpers.
   - Move `test` action execution and failed-test summary formatting into test action helpers.
   - Move `migrate` hints, migration logs, and migration result reporting into migrate action helpers.
   - Move remaining self-destruct worktree handling into worktree action helpers with explicit safety checks.
   - Move project action environment/replacement/artifact persistence into reusable project action support.
   - Keep `ActionCommandOrchestrator` as the compatibility entry point, but make each action route call a focused helper.
   - Split `tests/python/actions/test_actions_parity.py` into action-owned suites after each production extraction while
     preserving behavior assertions.

6. Normalize plan-agent transport concepts.
   - Introduce or complete shared vocabulary for launch intent, selected surface, prompt preset, readiness expectation,
     command preview, session identity, failure reason, and recovery guidance.
   - Keep transport-specific behavior in `planning/plan_agent/cmux_transport.py`, `tmux_transport.py`,
     `omx_transport.py`, `superset_transport.py`, OpenCode/Codex launch paths, and recovery modules.
   - Route common option mapping and result rendering through shared helpers.
   - Add tests that exercise the same option matrix across `--cmux`, `--tmux`, `--omx`, `--codex`, `--opencode`,
     `--ulw`, `--no-ulw-loop`, `--new-session`, `--headless`, direct-prompt behavior, and skipped/resumed launches.
   - Keep OpenCode-specific readiness failures observable with active command, expected prompt state, transport, timeout,
     and recovery guidance.
   - Regenerate and compare `contracts/runtime_feature_matrix.json` only if the declared feature inventory changes.

7. Break requirements adapters into lifecycle components, starting with Supabase.
   - Split `requirements/supabase.py` into smaller owners for configuration/env resolution, Docker/process lifecycle,
     health/readiness checks, database setup, QA/auth user setup, repair/reinit, and summary reporting.
   - Keep the existing adapter API stable for callers in startup and runtime code.
   - Add adapter-level tests proving real contract behavior before and after the split.
   - Apply the same pattern to other adapters only where it reduces complexity without hiding important behavior behind
     generic abstractions.

8. Split oversized tests after production seams exist.
   - Split large tests by behavior owner, not by arbitrary line count:
     plan-agent launch options, transport readiness, action parity, runtime startup, requirement adapter contracts, and
     dashboard restart selector behavior.
   - Move tests in the same commit as the production extraction they protect when practical.
   - Preserve fixtures and assertion intent; do not reduce coverage through mechanical movement.
   - Add lightweight structure/import guards only after realistic module boundaries exist. Any guard for large modules
     must include explicit waivers for legitimate aggregators.

9. Tighten generated contracts, docs, and release checks.
   - Keep `docs/reference/python-engine-architecture.md` aligned after each major extraction.
   - Add short contributor-facing "how to change this area" notes for runtime, startup, actions, planning, transports,
     requirements, and dashboard code once the corresponding owner modules are real.
   - Re-run generated contract scripts only when behavior or declared feature inventory intentionally changes:
     `scripts/generate_runtime_feature_matrix.py`, `scripts/generate_python_runtime_gap_report.py`, and
     `scripts/generate_python_engine_parity_manifest.py`.
   - Compare generated JSON artifacts and commit updates only when intentional.
   - Keep import-cycle and structure-layout failures actionable by pointing to the owning module family.

10. Preserve all compatibility and persistent contracts.
    - Do not redesign the CLI or remove compatibility commands.
    - Do not resurrect the old shell runtime.
    - Do not change prompt preset semantics, runtime state schemas, generated contract formats, `.envctl-state`
      artifact shape, startup logs, debug reports, plan-agent launch semantics, release-gate expectations, or user-facing
      command output except where a compatibility-preserving update is explicitly required by the refactor.
    - Do not make application-service or infrastructure changes.

## Gaps from prior iteration (mapped to evidence)

Fully implemented in this worktree:

- Architecture inventory exists at `docs/reference/python-engine-architecture.md` and is linked from
  `docs/reference/README.md`.
- Generated-worktree code-intelligence behavior is extracted to `python/envctl_engine/planning/worktree_code_intelligence.py`.
- Worktree provenance and fresh-AI worktree protection helpers are extracted to
  `python/envctl_engine/planning/worktree_provenance.py`.
- Worktree git-hook policy resolution is extracted to `python/envctl_engine/planning/worktree_git_hooks.py`.
- `planning/worktree_domain.py` keeps compatibility wrappers for the extracted planning helpers.
- Structure guards exist in `tests/python/shared/test_structure_layout.py`.
- Targeted validation reported before this rollover:
  - `uv run --extra dev pytest -q tests/python/planning tests/python/shared/test_structure_layout.py tests/python/startup/test_support_module_decoupling.py tests/python/shared/test_utility_consolidation_contract.py`
    -> `313 passed, 28 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/planning tests/python/planning tests/python/shared/test_structure_layout.py docs/reference/README.md`
    -> passed.
  - `git diff --check` -> passed.

Partially implemented:

- Planning/worktree split has started, but `worktree_domain.py` still contains selection, menu, memory,
  sync/create/delete, `MAIN_TASK.md` seeding, cleanup, and sorting responsibilities.
- Documentation has a first architecture inventory, but it does not yet reflect final ownership boundaries for every
  extracted runtime area.

Not implemented in this worktree:

- Runtime facade thinning for `PythonEngineRuntime`; `python/envctl_engine/runtime/engine_runtime.py` is still about
  1,679 lines.
- Startup lifecycle extraction; `python/envctl_engine/startup/startup_orchestrator.py` is still about 2,272 lines.
- Action orchestration extraction and action-owned test splitting; `actions/action_command_orchestrator.py` is still
  about 2,880 lines and `tests/python/actions/test_actions_parity.py` is still about 6,869 lines.
- Plan-agent transport vocabulary normalization and shared option-matrix coverage; `tests/python/planning/test_plan_agent_launch_support.py`
  is still about 7,368 lines.
- Supabase requirements adapter decomposition; `requirements/supabase.py` is still about 3,348 lines.
- Dashboard orchestration/test split; `ui/dashboard/orchestrator.py` is still about 2,209 lines and
  `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` is still about 3,494 lines.
- Generated contract generation/compare pass, full release shipability gate, and full Python test suite validation.
- GitHub checks for PR #245 did not run; `statusCheckRollup` was empty and no check runs/status contexts were reported
  for head commit `ce9ce49`.

## Acceptance criteria (requirement-by-requirement)

- Branch/source reconciliation is documented in git history or PR notes, and the final branch is based on the intended
  source ref or explicitly remains stacked for a justified reason.
- `worktree_domain.py`, `engine_runtime.py`, `startup_orchestrator.py`, `action_command_orchestrator.py`,
  `requirements/supabase.py`, and `ui/dashboard/orchestrator.py` are reduced to thin coordination layers or explicitly
  documented facades with clear owner modules.
- Each major runtime area has focused owner modules and focused tests:
  runtime, startup, actions, planning/worktrees, plan-agent transports, requirements, dashboard/UI, state/contracts.
- Public CLI behavior, exit statuses, state artifacts, prompt install output, plan-agent launch behavior, generated
  contracts, release-gate behavior, and user-facing summaries are preserved.
- Plan-agent launch option matrix is covered across all supported surfaces and flags listed in the requirements.
- Supabase adapter behavior is preserved behind smaller lifecycle/config/health/database/auth/repair/reporting pieces.
- Oversized tests are split by behavior owner without losing existing assertions or fixtures.
- Architecture docs and structure/import guards reflect the final owner modules.
- Generated contract scripts have been run and checked; checked-in JSON artifacts are unchanged or intentionally updated.
- `ruff`, relevant targeted suites, full Python test suite, generated contract checks, and release shipability gate pass.
- PR is updated with commits and validation evidence, and all required GitHub checks pass if GitHub reports any.

## Required implementation scope (frontend/backend/data/integration)

- Backend/Python engine:
  - `python/envctl_engine/runtime/`
  - `python/envctl_engine/startup/`
  - `python/envctl_engine/actions/`
  - `python/envctl_engine/planning/`
  - `python/envctl_engine/requirements/`
  - `python/envctl_engine/ui/dashboard/`
  - `python/envctl_engine/state/` only if contract or runtime owner changes require it.
- Tests:
  - `tests/python/runtime/`
  - `tests/python/startup/`
  - `tests/python/actions/`
  - `tests/python/planning/`
  - `tests/python/requirements/`
  - `tests/python/ui/`
  - `tests/python/shared/`
- Docs/contracts:
  - `docs/reference/python-engine-architecture.md`
  - Relevant developer/user docs if ownership guidance changes.
  - `contracts/*.json` only when generator output changes intentionally.
- Frontend:
  - None expected.
- Data/migrations:
  - None expected.
- Runtime services:
  - No application services are required for normal validation of this refactor. If runtime validation is attempted and
    blocked by missing repo-local `.envctl` or lack of interactive TTY, report that explicitly.

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
  Push the branch, open/update the PR, and wait for GitHub checks. If GitHub reports no checks, record that exact
  evidence instead of claiming CI passed.

## Edge cases and failure handling

- Dynamic CLI dispatch can hide call sites. Preserve behavior-level dispatch tests and generated feature matrix checks
  for every runtime route move.
- User-facing text can drift during extractions. Preserve assertions around launch guidance, prompt install output,
  failure summaries, debug report references, and release-gate messages.
- Generated contract files can drift during refactors. Regenerate intentionally and compare before committing.
- Compatibility wrappers can become permanent. Document each remaining facade and remove redundant wrappers once call
  sites are safely updated.
- Serena and CGC indexes can lag after structural moves. Use Serena for exact symbol navigation and diagnostics; use CGC
  context `Envctl` for broad graph checks. Run `serena project health-check` if symbol results look stale and refresh CGC
  with `cgc index . --context Envctl` after major structural changes if broad graph data is needed.
- The worktree currently has local state-file edits in `.envctl-state/worktree-provenance.json`; do not include them in
  unrelated implementation commits.
- Existing PR #245 is a draft stacked on `codex/reuse-cgc-worktree-context`; decide whether to keep it stacked or
  reconcile with the updated source branch before final validation.

## Definition of done

- All remaining requirements above are implemented end-to-end.
- The largest orchestrators are reduced to thin coordination layers or clearly justified/documented facades.
- Each major runtime area has an obvious owner module and focused test suite.
- Plan-agent transport flags and readiness behavior are covered by a shared option matrix.
- Supabase requirements behavior is preserved behind smaller components.
- Oversized tests are split by behavior without losing assertions or fixtures.
- Architecture docs, structure guards, import guards, and generated contracts reflect the final boundaries.
- `ruff`, targeted suites, full Python tests, generated contract checks, release shipability gate, and reported GitHub
  required checks pass.
- PR #245 or its successor is updated with the final commits and validation evidence.
