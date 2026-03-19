## 2026-03-19 - Shell runtime retirement follow-up cleanup

Scope:
- Completed the post-retirement cleanup pass for the remaining shell-era governance surface after the repo had already removed the Bash runtime tree and BATS harness.
- Removed the last Python package boundary that still modeled release gating as a `shell` domain, deleted stale shell-retirement blocker payload generation, and regenerated the runtime inventory artifacts to match the current Python-only product contract.

Key behavior changes:
- Release/shipability logic now lives under `python/envctl_engine/runtime/release_gate.py`, and all runtime, CLI, script, and test call paths import it from the runtime domain instead of the deleted `python/envctl_engine/shell` package.
- The dead `python/envctl_engine/shell` package and empty `tests/python/shell` test package were deleted, and structure/import-audit cleanup now treats the runtime domain layout as Python-only.
- `runtime_feature_inventory` now includes the supported `codex-tmux` command in the generated feature matrix, so matrix/gap-report validation no longer breaks on an untracked supported command.
- `contracts/python_runtime_gap_report.json` no longer emits `shell_retirement_blockers`; the gap report now reflects the retired state instead of continuing to model shell-retirement readiness as an active contract.
- Generated inventory notes and developer guidance were updated to stop referring to BATS lanes as active validation infrastructure.
- Added the missing planning documents `todo/plans/refactoring/python-runtime-gap-closure.md` and `todo/plans/refactoring/shell-runtime-retirement.md` so the repository contract tests can validate the generated/reflection docs that this tree expects.

Files/modules touched:
- `python/envctl_engine/runtime/release_gate.py`
- `python/envctl_engine/runtime/cli.py`
- `python/envctl_engine/runtime/engine_runtime.py`
- `python/envctl_engine/runtime_feature_inventory.py`
- `scripts/release_shipability_gate.py`
- `scripts/python_cleanup.py`
- `tests/python/runtime/test_release_shipability_gate.py`
- `tests/python/runtime/test_runtime_feature_inventory.py`
- `tests/python/shared/test_import_audit.py`
- `tests/python/shared/test_structure_layout.py`
- `tests/python/shared/test_validation_workflow_contract.py`
- `docs/developer/python-runtime-guide.md`
- `contracts/runtime_feature_matrix.json`
- `contracts/python_runtime_gap_report.json`
- `todo/plans/refactoring/python-runtime-gap-closure.md`
- `todo/plans/refactoring/shell-runtime-retirement.md`
- deleted `python/envctl_engine/shell/__init__.py`
- deleted `python/envctl_engine/shell/release_gate.py`
- deleted `tests/python/shell/__init__.py`

Tests run + results:
- `python3 -m unittest tests.python.runtime.test_runtime_feature_inventory tests.python.shared.test_structure_layout tests.python.shared.test_validation_workflow_contract tests.python.runtime.test_release_shipability_gate tests.python.runtime.test_release_shipability_gate_cli` -> passed (`37` tests).
- `python3 -m unittest tests.python.shared.test_import_audit` -> passed (`2` tests).
- `PYTHONPATH=python python3 -m unittest discover -s tests/python -p 'test_*.py'` -> passed (`1562` tests, `59` skipped).
- `rg -n "lib/engine/lib/|lib/engine/main\\.sh|ENVCTL_ENGINE_SHELL_FALLBACK|shell_prune|envctl-shell-ownership-ledger" .` -> only historical `todo/done` references remained; no active product code/docs/tests matches in the cleaned surfaces.

Config/env/migrations:
- No schema or migration changes.
- No new config keys were added.
- Regenerated `contracts/runtime_feature_matrix.json` and `contracts/python_runtime_gap_report.json` from the updated runtime inventory generator.
- Regenerated `todo/plans/refactoring/python-runtime-gap-closure.md` from the updated gap-plan generator.
- Full unittest discovery required `PYTHONPATH=python` in this worktree because the raw `python3 -m unittest discover -s tests/python -p 'test_*.py'` form does not place the `python/` package root on `sys.path`.

Risks/notes:
- The raw discovery command from `MAIN_TASK.md` still fails in this repo without `PYTHONPATH=python`; that is an existing test-environment constraint rather than a regression introduced by this cleanup.
- The reference sweep still finds shell-era names in archived/historical `todo/done` documents, which matches the retirement plan’s expected boundary for historical records.

## 2026-03-19 - Iteration audit and remaining-scope task rewrite

Scope:
- Audited the incomplete shell-runtime-retirement delivery against the current task, working-tree changes, tests, active docs, and recent git history.
- Archived the prior task file and rewrote `MAIN_TASK.md` so the next implementation iteration targets only the unresolved closure work.

Key behavior changes:
- Archived the prior task as `OLD_TASK_2.md` to preserve the completed/obsolete scope and evidence baseline.
- Replaced `MAIN_TASK.md` with an implementation-ready task focused on the two remaining closure gaps:
  - raw repo-root unittest discovery must pass without `PYTHONPATH=python`
  - active planning/developer docs must stop advertising retired shell-runtime and BATS-era work as current scope
- The new task explicitly excludes obsolete prior-task expectations that no longer reflect repo reality, including `shell_retirement_blockers` in the gap report and a live BATS-suite deliverable.

Files/modules touched:
- `OLD_TASK_2.md`
- `MAIN_TASK.md`
- `docs/changelog/refactoring_shell_runtime_retirement-1_changelog.md`

Tests run + results:
- `git status --short` -> audited current working-tree implementation surface.
- `git diff --name-status` -> audited unstaged changed files.
- `git diff --cached --name-status` -> confirmed no staged baseline/content.
- `git log --oneline --decorate -n 30` -> reviewed recent history around the incomplete delivery.
- `git show --stat --summary 036eeff` -> reviewed recent runtime/planning history relevant to active-plan carry-forward behavior.
- `git show --stat --summary a9733e5` -> reviewed recent planning/runtime test history.
- `python3 -m unittest discover -s tests/python -p 'test_*.py'` -> failed with `ModuleNotFoundError: No module named 'envctl_engine'` under raw repo-root discovery.
- `rg -n "lib/engine/lib/|lib/engine/main\\.sh|ENVCTL_ENGINE_SHELL_FALLBACK|shell_prune|envctl-shell-ownership-ledger|tests/bats|BATS" ...` -> confirmed stale active planning/doc references remain, alongside intentional BATS-environment checks in runtime/test code.

Config/env/migrations:
- No schema, migration, or runtime-config changes.
- No generated contracts were modified in this audit/task-rewrite iteration.

Risks/notes:
- The rewritten task assumes the BATS-environment checks in `python/envctl_engine/ui/terminal_session.py` and `tests/python/runtime/test_engine_runtime_real_startup.py` remain intentional test-harness behavior unless the next implementation pass finds repo evidence that they are obsolete.
- The working tree already contains unrelated incomplete implementation changes from the prior iteration; this audit preserved them and only updated task/changelog artifacts.

## 2026-03-19 - Raw unittest bootstrap and active-plan/doc closure

Scope:
- Closed the remaining shell-retirement follow-up gaps by making raw repo-root unittest discovery work without `PYTHONPATH=python`.
- Removed the last active planning/developer references that still treated retired shell-runtime or BATS-era validation surfaces as live scope.

Key behavior changes:
- Raw `python3 -m unittest discover -s tests/python -p 'test_*.py'` now bootstraps the repo-local `python/` package tree through the first-level `tests/python/*` package initializers, so discovery works from the repo root without caller-managed import-path setup.
- Added subprocess regression coverage that proves raw discovery succeeds both with an empty `PYTHONPATH` and when a foreign `envctl_engine` package is injected through `PYTHONPATH`, preserving the “this checkout wins” import behavior.
- Archived the stale active refactoring plan duplicates by removing them from `todo/plans/refactoring/` and relying on the existing `todo/done/refactoring/` copies as the historical record.
- Updated active developer docs to reference `runtime/release_gate.py` and the Python-only package layout instead of the deleted `shell/` domain.
- Updated active planning standards/docs so they no longer mention BATS lanes or `python/envctl_engine/shell/release_gate.py` as current shipability guidance.

Files/modules touched:
- `tests/python/actions/__init__.py`
- `tests/python/config/__init__.py`
- `tests/python/debug/__init__.py`
- `tests/python/planning/__init__.py`
- `tests/python/requirements/__init__.py`
- `tests/python/runtime/__init__.py`
- `tests/python/shared/__init__.py`
- `tests/python/startup/__init__.py`
- `tests/python/state/__init__.py`
- `tests/python/test_output/__init__.py`
- `tests/python/ui/__init__.py`
- `tests/python/shared/test_repo_root_bootstrap.py`
- `tests/python/shared/test_repo_root_bootstrap_probe.py`
- `tests/python/shared/test_validation_workflow_contract.py`
- `tests/python/runtime/test_runtime_feature_inventory.py`
- `docs/developer/python-runtime-guide.md`
- `docs/developer/module-layout.md`
- `docs/developer/debug-and-diagnostics.md`
- `todo/plans/README.md`
- `todo/plans/implementations/envctl-global-ignore-for-local-artifacts.md`
- deleted `todo/plans/refactoring/envctl-bash-deletion-ledger-and-prune-plan.md`
- deleted `todo/plans/refactoring/envctl-python-engine-final-100-percent-cutover-plan.md`
- deleted `todo/plans/refactoring/envctl-python-engine-ideal-state-finalization-plan.md`
- deleted `todo/plans/refactoring/shell-runtime-retirement.md`

Tests run + results:
- `python3 -m unittest tests.python.shared.test_repo_root_bootstrap tests.python.shared.test_validation_workflow_contract tests.python.runtime.test_runtime_feature_inventory` -> passed (`17` tests).
- `python3 -m unittest discover -s tests/python -p 'test_*.py'` -> passed (`1567` tests, `59` skipped).
- `rg -n "lib/engine/lib/|lib/engine/main\\.sh|lib/envctl\\.sh|ENVCTL_ENGINE_SHELL_FALLBACK|shell_prune|envctl-shell-ownership-ledger" . --glob '!docs/changelog/**' --glob '!todo/done/**' --glob '!OLD_TASK_*.md'` -> no matches.
- `rg -n "tests/bats|BATS" todo/plans docs/developer python/envctl_engine tests/python --glob '!docs/changelog/**' --glob '!todo/done/**'` -> only intentional `BATS_TEST_FILENAME` / `BATS_RUN_TMPDIR` runtime-test-harness checks remain.
- `rg -n "shell/|python/envctl_engine/shell/release_gate\\.py|shell/release_gate\\.py" docs/developer todo/plans --glob '!docs/changelog/**' --glob '!todo/done/**'` -> no matches.

Config/env/migrations:
- No schema, migration, or runtime-config changes.
- No generated contracts or manifests changed in this closure pass.

Risks/notes:
- The raw discovery command still emits noisy stdout/stderr from some existing integration-style tests, but the suite is green and the import-path failure is resolved.
- Intentional BATS-environment guards remain in `python/envctl_engine/ui/terminal_session.py` and `tests/python/runtime/test_engine_runtime_real_startup.py`; those are retained because they still enforce non-interactive test-harness behavior rather than shell-runtime governance.
