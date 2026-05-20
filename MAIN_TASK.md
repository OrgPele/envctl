# Envctl Deep Refactor Remaining Ownership Splits

## Context and objective

The previous task, now archived as `OLD_TASK_2.md`, started the broad
`Envctl Deep Codebase Refactor` plan. It completed the first architecture
inventory and a narrow action-command ownership slice, then opened the stacked
PR `https://github.com/OrgPele/envctl/pull/246`.

The current branch is based on `origin/codex/reuse-cgc-worktree-context`.
Committed divergence from that base contains these completed commits:

- `d4e7c5f Start deep codebase refactor ownership seams`
- `cc81c3b Move action worktree root helpers to target support`
- `cb0284f Extract action summary formatting helpers`

This iteration must finish the remaining deep refactor end-to-end without
changing supported CLI behavior, plan-agent semantics, prompt install behavior,
runtime state schemas, generated contract formats, or application-service
infrastructure. Preserve the new architecture inventory and completed action
helper seams, then continue reducing the largest orchestration modules into
clear owner modules with focused tests and contract validation.

## Remaining requirements (complete and exhaustive)

1. Complete the action-command ownership split.
   - Keep `ActionCommandOrchestrator` as the compatibility entry point for
     `test`, `pr`, `commit`, `review`, `migrate`, `delete-worktree`,
     `blast-worktree`, and `self-destruct-worktree`.
   - Preserve the completed target-resolution helpers in
     `python/envctl_engine/actions/action_target_support.py`.
   - Preserve the completed failure-summary helpers in
     `python/envctl_engine/actions/action_summary_support.py`.
   - Move remaining project-action success/failure persistence, PR cache
     clearing, review artifact extraction, and project action report writing out
     of `ActionCommandOrchestrator` into an action-owned support module.
   - Move migrate result records, migration result rendering, migration failure
     logs, migration env-source hints, and migrate project context construction
     into a migrate-owned helper module.
   - Move test suite overview rendering, failed-test artifact persistence, and
     failed-test collection wrappers into `action_test_support.py`,
     `action_test_runner.py`, or another test-action owner module.
   - Keep public method wrappers only where tests or compatibility callers still
     require them, and make wrappers delegate to owner modules.
   - Split or add focused tests for each extracted owner module while keeping
     `tests/python/actions/test_actions_parity.py` behavior coverage intact.

2. Thin `PythonEngineRuntime` into explicit runtime delegates.
   - Group methods by dispatch/help, project discovery and resolution,
     lifecycle start/resume/stop, action command entry points,
     debug/doctor/release-gate commands, dashboard/interactive commands,
     service command helpers, hook bridging, and truth/readiness helpers.
   - Move cohesive method clusters into existing runtime support modules where
     ownership already exists.
   - Add new runtime support modules only when no existing owner module fits.
   - Preserve `PythonEngineRuntime` as the public CLI/test facade with
     construction, delegation, and compatibility shims.
   - Preserve `command_router.py` route behavior and
     `contracts/runtime_feature_matrix.json` output unless an intentional
     compatibility-preserving contract update is required.
   - Add focused facade/delegate tests proving route selection, exit status,
     event/status output, and generated feature inventory do not drift.

3. Decompose startup orchestration by lifecycle phase.
   - Keep `StartupOrchestrator.execute` as the main sequence owner.
   - Extract plan-agent worktree preparation and launch handoff into a
     planning/startup coordinator with a narrow input and result object.
   - Extract restart, reuse, and pre-stop policy into a startup policy module.
   - Extract success, degraded, and failure finalization into a finalizer or
     renderer module that owns user-facing summaries and debug report
     references.
   - Extract requirement and service startup sequencing into a service
     bootstrap coordinator while preserving readiness and truth reconciliation.
   - Preserve behavior for degraded handoff, plan-agent launch skip/resume,
     disabled modes, startup logs, runtime state truth, and failure reports.

4. Separate planning worktree responsibilities.
   - Split `python/envctl_engine/planning/worktree_domain.py` along existing
     responsibilities: selection/menu/memory, sync/create/delete operations,
     provenance and `MAIN_TASK.md` seeding, git hook policy, fresh AI worktree
     protection, and code-intelligence setup.
   - Keep public functions stable during the first pass; move implementation
     behind them before simplifying call sites.
   - Preserve the strict boundary that plan operations only edit inside the
     current checked-out worktree or generated plan worktrees.
   - Preserve Serena and CGC setup behavior, including repo-local ignores,
     inherited source CGC context behavior, isolated context metadata when
     applicable, and deletion cleanup for generated contexts.
   - Add tests that fail on accidental sibling-worktree writes, hook-policy
     drift, provenance drift, and code-intelligence metadata drift.

5. Normalize plan-agent transport concepts.
   - Introduce shared vocabulary and helper types for launch intent, selected
     surface, prompt preset, readiness expectation, command preview, session
     identity, failure reason, and recovery guidance.
   - Keep transport-specific modules for `tmux`, `cmux`, `omx`, OpenCode,
     Codex, Superset, ULW, and recovery behavior.
   - Route common option mapping and result rendering through shared helpers
     without changing transport-specific command execution.
   - Add a shared option matrix covering `--cmux`, `--tmux`, `--omx`,
     `--codex`, `--opencode`, `--ulw`, `--no-ulw-loop`, `--new-session`,
     `--headless`, direct-prompt behavior, skipped launches, and resumed
     launches.
   - Keep OpenCode and Superset readiness failures observable with active
     command, expected prompt state, transport, timeout, and recovery guidance.
   - Preserve runtime feature matrix generation unless an intentional contract
     update is required.

6. Break requirements adapters into lifecycle components, starting with
   Supabase.
   - Preserve the existing adapter API used by startup and runtime callers.
   - Split `python/envctl_engine/requirements/supabase.py` into focused
     configuration/env resolution, Docker/process lifecycle, health/readiness,
     database setup, QA/auth user setup, repair/reinit, and summary reporting
     components.
   - Add adapter-level tests proving real contract behavior before and after
     the split.
   - Apply the same extraction pattern to other requirement adapters only where
     it reduces complexity without hiding important behavior behind generic
     abstractions.

7. Reduce dashboard and terminal UI orchestration blast radius.
   - Keep `python/envctl_engine/ui/dashboard/orchestrator.py` as the
     compatibility coordinator.
   - Move rendering-only behavior to dashboard rendering modules.
   - Move PR flow behavior to `ui/dashboard/pr_flow.py`.
   - Move terminal-specific behavior to `ui/dashboard/terminal_ui.py`.
   - Preserve restart selector behavior, dashboard status text, command-loop
     interactions, and tests that protect browser/terminal-visible output.

8. Split oversized tests after production seams exist.
   - Split large tests by behavior owner, not by arbitrary line count:
     plan-agent launch options, transport readiness, action parity, runtime
     startup, requirement adapter contracts, and dashboard restart selector
     behavior.
   - Move assertions in the same commit as the production extraction they
     protect whenever practical.
   - Preserve fixtures and assertion names that prove compatibility behavior.
   - Add lightweight structure tests only after realistic module boundaries
     exist; do not add hard size limits before the refactor has created
     defensible ownership boundaries.

9. Tighten generated contracts and release checks.
   - Re-run and update generated artifacts only when behavior or declared
     feature inventory intentionally changes:
     `scripts/generate_runtime_feature_matrix.py`,
     `scripts/generate_python_runtime_gap_report.py`, and
     `scripts/generate_python_engine_parity_manifest.py`.
   - Keep `scripts/release_shipability_gate.py` passing throughout the refactor.
   - Add contract tests for any new ownership map or architecture inventory if
     the repo should treat it as a maintained source of truth.
   - Make import-cycle and structure-layout failures actionable by pointing to
     the owning module family.

10. Keep contributor-facing documentation aligned with the implementation.
    - Preserve and update `docs/reference/python-engine-architecture.md` after
      each major extraction.
    - Keep `docs/developer/module-layout.md`, `docs/developer/architecture-overview.md`,
      and `AGENTS.md` aligned with actual tooling and module ownership.
    - Document how to change runtime, startup, actions, planning, transports,
      requirements, and dashboard code once the relevant ownership boundaries
      are in place.

## Gaps from prior iteration (mapped to evidence)

Fully implemented in the prior iteration:

- Architecture inventory exists at
  `docs/reference/python-engine-architecture.md` and is guarded by
  `tests/python/shared/test_structure_layout.py`.
- Action target/project resolution now lives in
  `python/envctl_engine/actions/action_target_support.py`:
  `resolve_action_targets`, `projects_for_services`,
  `repo_root_from_worktree_layout`, and `main_repo_root_for_worktree`.
- `ActionCommandOrchestrator.resolve_targets`,
  `_main_repo_root_for_worktree`, `_repo_root_from_worktree_layout`, and
  `projects_for_services` delegate to action target helpers.
- Failure summary formatting and migrate failure headline selection now live in
  `python/envctl_engine/actions/action_summary_support.py`.
- `ActionCommandOrchestrator` summary static methods delegate to
  `action_summary_support` compatibility wrappers.
- Focused tests were added:
  `tests/python/actions/test_action_target_support.py`,
  `tests/python/actions/test_action_summary_support.py`, and the architecture
  inventory assertion in `tests/python/shared/test_structure_layout.py`.
- Local validation from the prior implementation pass:
  - `uv run --extra dev python -m pytest -q tests/python/actions` passed.
  - `uv run --extra dev python -m pytest -q tests/python/actions tests/python/shared/test_structure_layout.py`
    passed with 223 tests, 36 subtests, and one existing
    `PytestCollectionWarning`.
  - Focused Ruff checks for touched action/support files passed.
- PR `https://github.com/OrgPele/envctl/pull/246` was opened as a stacked PR
  against `codex/reuse-cgc-worktree-context`; GitHub reported no status checks
  for that branch and no review threads.

Partially implemented:

- Action command orchestration is smaller, but
  `python/envctl_engine/actions/action_command_orchestrator.py` is still a large
  compatibility coordinator. It still owns project action result persistence,
  migrate reporting/log rendering, test overview rendering, failed-test
  persistence wrappers, status/color helpers, and compatibility methods.
- Action tests now include focused owner tests, but
  `tests/python/actions/test_actions_parity.py` remains large and still carries
  many behavior assertions that should move alongside future production seams.

Not implemented:

- Runtime facade thinning beyond pre-existing support modules.
- Startup lifecycle phase decomposition.
- Planning worktree responsibility split.
- Shared plan-agent transport vocabulary and option matrix.
- Supabase requirements adapter lifecycle split.
- Dashboard orchestration split.
- Oversized non-action test splits.
- Final generated contract verification, release shipability gate, full Python
  suite, final PR update, and required GitHub status-check confirmation.

Current size evidence from the audit:

- `python/envctl_engine/runtime/engine_runtime.py`: 1679 lines.
- `python/envctl_engine/startup/startup_orchestrator.py`: 2272 lines.
- `python/envctl_engine/actions/action_command_orchestrator.py`: 2572 lines.
- `python/envctl_engine/planning/worktree_domain.py`: 2377 lines.
- `python/envctl_engine/requirements/supabase.py`: 3348 lines.
- `python/envctl_engine/ui/dashboard/orchestrator.py`: 2209 lines.
- `tests/python/planning/test_plan_agent_launch_support.py`: 7368 lines.
- `tests/python/actions/test_actions_parity.py`: 6869 lines.
- `tests/python/runtime/test_engine_runtime_real_startup.py`: 6055 lines.
- `tests/python/requirements/test_requirements_adapters_real_contracts.py`:
  3732 lines.
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`: 3494
  lines.

Git evidence used for this audit:

- `git status --short`
- `git diff --name-status`
- `git diff --cached --name-status`
- `git log --oneline --decorate -n 30`
- `git merge-base HEAD origin/codex/reuse-cgc-worktree-context`
- `git diff --name-status $(git merge-base HEAD origin/codex/reuse-cgc-worktree-context)..HEAD`
- `git log --oneline --decorate $(git merge-base HEAD origin/codex/reuse-cgc-worktree-context)..HEAD`
- `gh pr view 246 --json number,title,url,baseRefName,headRefName,state,statusCheckRollup,comments,reviewDecision`

## Acceptance criteria (requirement-by-requirement)

- Action commands:
  - `ActionCommandOrchestrator` delegates remaining project action persistence,
    migrate reporting/logs, and test overview/artifact helpers to owner modules.
  - Public command behavior and private compatibility wrappers remain covered by
    focused owner tests and action parity tests.
  - `uv run --extra dev python -m pytest -q tests/python/actions` passes.

- Runtime facade:
  - `PythonEngineRuntime` is reduced to construction, delegation, and
    compatibility shims for the moved method clusters.
  - Runtime command route selection, exit statuses, events, and feature
    inventory remain unchanged unless contract artifacts are intentionally
    regenerated.
  - Runtime tests and runtime feature inventory tests pass.

- Startup:
  - `StartupOrchestrator.execute` reads as sequence orchestration and delegates
    policy, plan-agent handoff, service/requirements bootstrap, and finalization
    details to focused modules.
  - Existing startup/resume/degraded/failure-report tests pass.

- Planning/worktrees:
  - `worktree_domain.py` delegates selection, lifecycle, provenance, hook
    policy, fresh-AI protection, and code-intelligence setup to owner modules.
  - Worktree setup tests cover sibling-write protection, hook policy,
    provenance, Serena, and CGC behavior.

- Plan-agent transports:
  - Shared launch vocabulary exists and is used by transport option mapping and
    result rendering.
  - The common option matrix covers all named transport flags and direct
    prompt/skipped/resumed paths.
  - Plan-agent launch tests pass without feature matrix drift unless the
    generator output is intentionally updated.

- Requirements:
  - Supabase behavior is preserved behind smaller lifecycle/config/health/user
    and database components.
  - Requirements adapter contract tests pass.

- Dashboard/UI:
  - Dashboard orchestration delegates rendering, PR flow, and terminal-specific
    behavior to owner modules.
  - UI/dashboard tests pass and user-facing status text remains stable.

- Tests/docs/contracts:
  - Oversized tests are split only after corresponding production seams exist.
  - Architecture docs and module-layout docs reflect final ownership.
  - Ruff, release shipability gate, generated contract checks, and the full
    Python test suite pass before final PR handoff.

## Required implementation scope (frontend/backend/data/integration)

- Backend/Python engine:
  - `python/envctl_engine/actions/*`
  - `python/envctl_engine/runtime/*`
  - `python/envctl_engine/startup/*`
  - `python/envctl_engine/planning/*`
  - `python/envctl_engine/planning/plan_agent/*`
  - `python/envctl_engine/requirements/*`
  - `python/envctl_engine/ui/dashboard/*`
  - `python/envctl_engine/state/*` only if compatibility-preserving state
    helpers are required by extracted modules.

- Tests:
  - Add or split tests under `tests/python/actions`, `tests/python/runtime`,
    `tests/python/startup`, `tests/python/planning`,
    `tests/python/requirements`, `tests/python/ui`, and
    `tests/python/shared` according to the production seam being extracted.

- Docs/contracts:
  - Update `docs/reference/python-engine-architecture.md`.
  - Update developer docs and `AGENTS.md` only when module ownership or tooling
    guidance changes.
  - Regenerate checked-in contract JSON only for intentional contract changes.

- Frontend:
  - None expected.

- Data/migrations:
  - No migrations expected. Preserve runtime state and `.envctl-state` schemas.

- Runtime services:
  - Use `--no-infra` for plan-agent refactor validation unless a specific
    change crosses runtime service boundaries.

## Required tests and quality gates

Run targeted tests after each ownership-area extraction:

- Actions:
  `uv run --extra dev python -m pytest -q tests/python/actions`
- Runtime:
  `uv run --extra dev python -m pytest -q tests/python/runtime tests/python/test_runtime_feature_inventory.py`
- Startup:
  `uv run --extra dev python -m pytest -q tests/python/startup tests/python/runtime/test_engine_runtime_real_startup.py`
- Planning and plan-agent:
  `uv run --extra dev python -m pytest -q tests/python/planning`
- Requirements:
  `uv run --extra dev python -m pytest -q tests/python/requirements`
- UI/dashboard:
  `uv run --extra dev python -m pytest -q tests/python/ui`
- Shared structure/import checks:
  `uv run --extra dev python -m pytest -q tests/python/shared/test_structure_layout.py tests/python/shared/test_utility_consolidation_contract.py`
- Ruff for touched files after each commit:
  `uv run --extra dev ruff check <touched production and test files>`

Run final validation before final handoff:

- `uv run --extra dev ruff check python tests scripts`
- `uv run --extra dev python -m pytest -q tests`
- Runtime feature matrix generator and diff check.
- Python runtime gap report generator and diff check.
- Python engine parity manifest generator and diff check.
- `uv run --extra dev python scripts/release_shipability_gate.py` if that is
  the current repo-supported invocation; otherwise inspect the script/tests and
  use the repo-supported release gate command.
- Create or update the PR, inspect unresolved review threads, address all
  actionable comments, push follow-up commits, and wait for GitHub status checks
  to complete. If GitHub reports no checks for the branch, record that exact
  evidence instead of claiming green checks.

## Edge cases and failure handling

- Preserve compatibility wrappers while moving code so dynamic callers and old
  tests do not break during the refactor.
- Preserve user-facing output that tests or users rely on, especially prompt
  install output, launch diagnostics, failure summaries, migration hints,
  dashboard status text, and release-gate messages.
- Do not mutate sibling worktrees or paths outside the current checked-out repo
  while implementing this task.
- Do not retrofit existing generated worktrees unless a requirement explicitly
  says to do so.
- Treat CGC and Serena results as potentially stale after structural moves; let
  Serena refresh automatically and run `serena project health-check` or
  `cgc index . --context Envctl` only when broad graph evidence is needed and
  stale.
- Keep `uv.lock` out of commits unless the repo intentionally starts tracking a
  lockfile; current `envctl commit` invocations may regenerate it.
- If a generated contract changes unexpectedly, stop and identify whether the
  change is an intentional behavior update or a refactor regression before
  committing.

## Definition of done

- All remaining requirements above are implemented end-to-end.
- The largest orchestrators are thin coordination layers or explicitly justified
  compatibility facades.
- Each major runtime area has an obvious owner module and focused tests.
- Plan-agent transport flags and readiness behavior are covered by a shared
  option matrix.
- Supabase requirements behavior is preserved behind smaller lifecycle
  components.
- Oversized tests are split by behavior owner without losing assertions.
- Architecture and developer documentation reflect the final ownership
  boundaries.
- Generated runtime feature matrix, Python runtime gap report, parity manifest,
  release shipability gate, Ruff, and the full Python test suite pass.
- The final branch is pushed, the PR is open or updated, unresolved review
  threads are audited and addressed, and GitHub status checks are complete or
  explicitly reported as absent if GitHub reports no checks.
