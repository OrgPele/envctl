# Resolve Startup Refactor PR Conflicts With Main

## Context and objective

The previous iteration task has been archived as `OLD_TASK_2.md`. The original startup orchestration decision-boundary task remains archived as `OLD_TASK_1.md`.

The startup orchestration implementation itself is complete: the branch contains the owner-module extraction, focused tests, docs updates, full local validation evidence, and PR #225 is open. A fresh audit found one remaining delivery blocker: PR #225 is now `CONFLICTING` / `DIRTY` against `origin/main` after upstream changes landed on `main`.

Objective: fully resolve the PR #225 merge conflicts against `origin/main` end-to-end, preserving the startup orchestration refactor from this branch and the upstream behavior now present on `main`, then validate, commit, push, update PR #225, and verify review/check status.

## Remaining requirements (complete and exhaustive)

1. Rebase or merge the branch onto the current `origin/main` in the current worktree only.
2. Resolve every Git conflict reported between `HEAD` and `origin/main`; do not use a blanket ours/theirs resolution.
3. Preserve this branch's startup orchestration decision-boundary work:
   - `python/envctl_engine/startup/execution_plan.py`
   - `python/envctl_engine/startup/run_reuse_application.py`
   - `python/envctl_engine/startup/project_execution.py`
   - thin `StartupOrchestrator` delegation to those owner modules
   - startup module-layout tests and focused reuse/project-execution tests
   - docs mapping the startup phases to the new owner modules
4. Preserve upstream `origin/main` behavior and tests, especially:
   - plan-agent modularization and public compatibility facade behavior
   - Supabase/dependency startup reliability and requirements parallelism behavior
   - macOS tmux/path/lifecycle validation behavior
   - upstream reuse-expand tree startup behavior from PR #223
5. Integrate overlapping reuse-expand tests so both branch coverage and upstream coverage remain meaningful without duplicate or contradictory assertions.
6. Update docs only where conflict resolution changes the accurate owner-module or runtime behavior descriptions.
7. Keep task archive files intact:
   - `OLD_TASK_1.md` remains the original archived implementation task.
   - `OLD_TASK_2.md` remains the archived no-remaining-work audit task.
8. When implementation is complete, run the required local validation, commit the resolved branch, push it, update PR #225 if needed, inspect unresolved PR review threads/comments, and verify GitHub checks or explicitly document that no checks are reported.

## Gaps from prior iteration (mapped to evidence)

| Gap | Status | Evidence |
| --- | --- | --- |
| Prior `MAIN_TASK.md` stated no remaining implementation work, but the PR is not mergeable against `main` | Not implemented | `gh pr view 225 --json mergeable,mergeStateStatus,baseRefName,headRefName` reported `mergeable=CONFLICTING`, `mergeStateStatus=DIRTY`, base `main`, head `refactoring_startup_orchestration_decision_boundaries-1` |
| Branch has content conflicts with current `origin/main` | Not implemented | `git merge-tree --name-only HEAD origin/main` reported conflicts in `python/envctl_engine/planning/plan_agent_launch_support.py`, `python/envctl_engine/requirements/supabase.py`, `python/envctl_engine/runtime/codex_tmux_support.py`, `python/envctl_engine/runtime/engine_runtime_lifecycle_support.py`, `python/envctl_engine/startup/startup_orchestrator.py`, `tests/python/requirements/test_requirements_adapters_real_contracts.py`, `tests/python/runtime/test_qa_user_command_support.py`, and `tests/python/startup/test_startup_orchestrator_flow.py` |
| Upstream reuse-expand tree coverage overlaps branch reuse-expand coverage | Partially implemented | `git merge-tree HEAD origin/main` shows conflict markers inside `tests/python/startup/test_startup_orchestrator_flow.py` around branch `test_reuse_expand_preserves_existing_project_state_and_starts_only_new_projects` / stale reuse tests and upstream `test_tree_start_reuse_expand_preserves_existing_services_and_starts_only_new_tree` |
| PR has no review-thread blockers, but review/check state must be rechecked after the conflict-resolution push | Partially implemented | `gh api graphql ... reviewThreads` returned no nodes before this iteration; `gh pr checks 225` reported no checks on the current head before this iteration |

Git evidence used during audit:

- `git status --short`
- `git diff --name-status`
- `git diff --cached --name-status`
- `git log --oneline --decorate -n 30`
- `git merge-base HEAD origin/fix/supabase-compose-timeout-120`
- `git diff --name-status <originating-merge-base>..HEAD`
- `git log --oneline --decorate <originating-merge-base>..HEAD`
- `git show --name-status --oneline --decorate 263101c 3869c37 97cec75`
- `git fetch origin fix/supabase-compose-timeout-120 main refactoring_startup_orchestration_decision_boundaries-1`
- `gh pr view 225 --json number,url,state,baseRefName,headRefName,headRefOid,baseRefOid,mergeable,mergeStateStatus,isCrossRepository,reviewDecision`
- `gh pr checks 225`
- `gh api graphql ... reviewThreads`
- `git merge-base HEAD origin/main`
- `git diff --name-status <main-merge-base>..HEAD`
- `git diff --name-status <main-merge-base>..origin/main`
- `git log --oneline --decorate --left-right --cherry-pick HEAD...origin/main`
- `git merge-tree --name-only HEAD origin/main`
- `git merge-tree --messages HEAD origin/main`

## Acceptance criteria (requirement-by-requirement)

1. The local branch is rebased onto or merged with current `origin/main`, and `git status --short` shows no unmerged paths.
2. `gh pr view 225 --json mergeable,mergeStateStatus` no longer reports `CONFLICTING` / `DIRTY` after push.
3. The startup owner modules remain wired and tested:
   - `StartupOrchestrator._resolve_run_reuse(...)` delegates to `resolve_run_reuse_for_session(...)`.
   - `StartupOrchestrator._start_selected_contexts(...)` delegates to `execute_project_startup_plan(...)`.
   - `_record_project_startup(...)` delegates to `apply_project_startup_result_to_session(...)`.
4. The upstream plan-agent facade/module split remains intact; internal code should import private helpers from owner modules under `planning/plan_agent/` when that is the upstream convention.
5. The upstream Supabase/dependency startup behavior remains intact, including requirements parallelism flags and macOS/default behavior.
6. Reuse-expand startup behavior covers both:
   - branch behavior: preserved services/requirements from a reused project are merged with newly started projects, stale reuse-expand starts all selected projects fresh, and failure writes a fresh run id.
   - upstream behavior: tree startup can reuse existing selected trees and starts only newly requested tree projects without terminating preserved services.
7. No conflict markers remain in tracked files.
8. `.envctl-commit-message.md` describes the final cumulative conflict-resolution commit.
9. PR #225 is pushed and review threads/comments are inspected. Any actionable unresolved comments are addressed before final handoff.

## Required implementation scope (frontend/backend/data/integration)

Frontend scope: none.

Backend/runtime scope: Python runtime and startup orchestration conflict resolution only.

Data or migration scope: none.

Integration scope: PR branch synchronization with `origin/main`; no sibling worktree edits are allowed.

Documentation scope: only update docs touched by the merge when needed to keep startup, plan-agent, and dependency behavior accurate.

## Required tests and quality gates

Run the narrow tests first after resolving conflicts:

- `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_execution_plan`
- `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_run_reuse_application`
- `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_project_execution`
- `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_module_layout`
- `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_orchestrator_flow`
- `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_spinner_integration`
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_qa_user_command_support`
- `PYTHONPATH=python python3 -m unittest tests.python.requirements.test_requirements_adapters_real_contracts`
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support`

Then run the full relevant suite:

- `.venv/bin/python -m pytest -q`

If a runtime smoke is needed because conflict resolution touches startup runtime behavior beyond tests, use the smallest envctl scope that proves it. Use `envctl --entire-system --headless` if the resolution affects startup/service/dependency integration in a way not covered by tests.

After pushing, run:

- `gh pr checks 225 --watch` when checks are reported.
- `gh pr checks 225` and record the no-checks output if no checks are configured.
- GraphQL review-thread inspection for unresolved actionable comments.

## Edge cases and failure handling

- If `origin/main` has advanced again before implementation starts, fetch and use the new `origin/main`.
- If an upstream implementation already supersedes a branch-side helper, prefer the upstream owner boundary and adapt this branch's tests and call sites to preserve behavior without duplicate internals.
- If a conflict is only in tests, still inspect the corresponding production code before resolving the test so assertions match real call paths.
- If full pytest reveals failures outside the conflict files, classify whether they are caused by the rebase/merge. Fix caused failures in this iteration; document unrelated pre-existing failures with evidence only if they cannot be fixed within this task.
- Do not delete branch-added task archives or tests to make the merge easier.

## Definition of done

- Current `MAIN_TASK.md` is fully implemented end-to-end.
- PR #225 is mergeable against current `origin/main`.
- All conflict files are resolved with both branch and upstream behavior preserved.
- Required focused tests and full pytest are green, or any unavoidable external/runtime limitation is documented with exact command output.
- The branch is committed and pushed.
- PR #225 is updated, unresolved review threads/comments are handled, and GitHub check status is verified.
