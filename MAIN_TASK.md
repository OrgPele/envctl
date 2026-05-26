# Envctl Runtime Orchestrator Decomposition Completion Audit

## Context and objective

The archived task in `OLD_TASK_7.md` described the remaining runtime orchestrator decomposition work. Current code,
tests, documentation, and git history show that the decomposition scope has been completed by the branch lineage now
present in this checkout. There is no remaining implementation work for that task.

This task is intentionally a completion record for the next iteration. Do not invent additional refactor scope under the
archived task. Any future runtime, startup, action, requirement, dashboard, or plan-agent work should start from a new
task with a fresh objective and code evidence.

## Remaining requirements (complete and exhaustive)

No runtime orchestrator decomposition requirements remain from `OLD_TASK_7.md`.

The previous requirements are complete:

1. Planning/worktree responsibility separation is complete.
2. `PythonEngineRuntime` has been thinned into explicit runtime delegates while remaining the public facade.
3. Startup orchestration has been decomposed by lifecycle phase while `StartupOrchestrator.execute` remains the sequence
   owner.
4. Action command orchestration has been split into action-owned helpers while `ActionCommandOrchestrator` remains the
   compatibility entry point.
5. Plan-agent transport concepts and option-matrix coverage have been normalized across focused transport and workflow
   modules.
6. Requirement adapters, including Supabase, have been split behind stable adapter APIs.
7. Dashboard orchestration and oversized UI tests have been split by behavior owner.
8. Oversized tests have been split by production owner where the corresponding seams exist.
9. Generated contracts, docs, and release checks have been tightened and the architecture inventory is aligned with the
   current ownership map.
10. Compatibility and persistent contracts remain guarded by facade modules, structure-layout tests, parity tests, and
    split owner suites.

## Gaps from prior iteration (mapped to evidence)

No gaps remain.

Evidence reviewed for the completion decision:

- `git status --short`, `git diff --name-status`, and `git diff --cached --name-status` showed no uncommitted
  implementation changes before this rollover.
- `.envctl-state/worktree-provenance.json` identifies the originating source as
  `origin/codex/reuse-cgc-worktree-context`.
- `git merge-base HEAD origin/codex/reuse-cgc-worktree-context` resolved to the current source-ref commit,
  confirming the committed divergence could be audited from the provenance base.
- `git diff --name-status <merge-base>..HEAD` and `git log --oneline --decorate <merge-base>..HEAD` show the completed
  decomposition lineage, including runtime facade thinning, startup lifecycle owners, action helper ownership,
  plan-agent transport/workflow ownership, requirements/Supabase lifecycle owners, dashboard mixins, split tests, and
  generated contract/docs updates.
- `python/envctl_engine/runtime/engine_runtime.py` is a public facade that delegates construction, dispatch, action,
  CLI, doctor, debug, lifecycle, planning, service, startup, truth, UI bridge, bookkeeping, state, event, and diagnostics
  behavior to owner modules.
- `python/envctl_engine/startup/startup_orchestrator.py` keeps `execute` as a readable sequence entry point and delegates
  lifecycle work to startup owner modules.
- `python/envctl_engine/actions/action_command_orchestrator.py` remains the action compatibility entry point and
  delegates command execution, target resolution, worktree actions, spinner status, test, migrate, project action, and
  report behavior to action owners and facade mixins.
- `python/envctl_engine/requirements/supabase.py` is a compatibility facade over `requirements/supabase_lifecycle/*`.
- `python/envctl_engine/ui/dashboard/orchestrator.py` is a dashboard coordination facade composed from behavior mixins.
- `docs/reference/python-engine-architecture.md` documents the current owner map and test ownership split.
- `tests/python/shared/test_structure_layout.py` contains structure guards for the extracted owner modules and split
  test suites.
- Split test suites exist under `tests/python/planning`, `tests/python/runtime`, `tests/python/startup`,
  `tests/python/actions`, `tests/python/requirements`, and `tests/python/ui` for the owner areas named in the archived
  task.

## Acceptance criteria (requirement-by-requirement)

This iteration is complete when:

1. `OLD_TASK_7.md` preserves the previous `MAIN_TASK.md` unchanged except for the file rename.
2. This `MAIN_TASK.md` states that no implementation scope remains from the archived decomposition task.
3. The rollover commit includes only task-rollover metadata and does not modify implementation code.
4. `.envctl-commit-message.md` describes this rollover accurately for the next commit.
5. `git diff --check` passes after the rollover edits.

## Required implementation scope (frontend/backend/data/integration)

No frontend, backend, data, integration, runtime, startup, action, planning, requirement, dashboard, contract, or
generated-artifact implementation changes are required for this iteration.

The only required repository changes are:

- Preserve the previous task as `OLD_TASK_7.md`.
- Replace `MAIN_TASK.md` with this completion audit.
- Update `.envctl-commit-message.md` with a focused task-rollover commit message.

## Required tests and quality gates

Required quality gate for this documentation/task rollover:

- `git diff --check`

No Python test suite is required because this iteration intentionally makes no code changes. If implementation files are
changed before commit, rerun the affected focused suites plus `uv run --extra dev ruff check python tests scripts`.

## Edge cases and failure handling

- If future audit finds a real behavior gap, do not amend this completion record with vague follow-up work. Create a new
  task that names the exact failing behavior, affected modules, test gaps, and acceptance criteria.
- If git provenance becomes unavailable in a later checkout, anchor the audit to the best available merge base and state
  the limitation in that new task.
- Keep all task-rollover edits inside the current worktree. Do not modify sibling worktrees or source checkout task
  files.

## Definition of done

- `MAIN_TASK.md` contains no remaining implementation requirements for the archived decomposition task.
- `OLD_TASK_7.md` exists and contains the prior task.
- `.envctl-commit-message.md` is updated for the task-rollover commit.
- `git diff --check` passes.
