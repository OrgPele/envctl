# Envctl Dead Code Cleanup Completion Audit

## Context and objective
The prior task, archived as `OLD_TASK_1.md`, requested removal of seven stale internal Python engine leaf modules, preservation of string-invoked entry points and selector compatibility facades, addition of a narrow structural guard, targeted validation, codegraph refresh, commit, push, and PR creation.

The implementation audit found that the prior task is fully complete. There is no remaining code implementation scope for the envctl dead-code cleanup task in this worktree.

## Remaining requirements (complete and exhaustive)
- No implementation changes remain.
- Preserve the completed cleanup commit and PR state:
  - Commit: `5e8a306 Remove stale envctl engine leaf modules`
  - PR: `https://github.com/OrgPele/envctl/pull/227`
- Do not reintroduce any of the deleted stale modules:
  - `python/envctl_engine/test_output/coverage.py`
  - `python/envctl_engine/test_output/error_extractor.py`
  - `python/envctl_engine/test_output/mode_handler.py`
  - `python/envctl_engine/test_output/multi_project_runner.py`
  - `python/envctl_engine/ui/input_adapter.py`
  - `python/envctl_engine/ui/textual/screens/dashboard.py`
  - `python/envctl_engine/ui/textual/widgets/service_table.py`
- Preserve the retained low-inbound entry points and compatibility facade:
  - `python/envctl_engine/test_output/pytest_progress_plugin.py`
  - `python/envctl_engine/test_output/unittest_runner.py`
  - `python/envctl_engine/ui/textual/selector_subprocess_entry.py`
  - `python/envctl_engine/ui/textual/screens/selector/implementation.py`

## Gaps from prior iteration (mapped to evidence)
- None.
- Git divergence from `origin/main` contains only the intended cleanup commit:
  - `git diff --name-status $(git merge-base HEAD origin/main)..HEAD`
  - `git log --oneline --decorate $(git merge-base HEAD origin/main)..HEAD`
- Deleted stale files are absent from `HEAD`:
  - `git ls-tree -r --name-only HEAD` with the stale-path filter returned no rows.
- Raw source references for deleted symbols are absent from active source/test/script files:
  - `CoverageReportHandler`
  - `ErrorDetailExtractor`
  - `OutputModeHandler`
  - `MultiProjectTestRunner`
  - `action_for_key`
  - `DashboardScreenContext`
  - `dashboard_snapshot_text`
- The structural guard exists in `tests/python/shared/test_structure_layout.py` and passed locally.
- GitHub PR checks for PR #227 passed:
  - `ruff`
  - `build & shipability`
  - `pytest`
- GitHub review evidence showed no unresolved review threads and Kody reported no issues.

## Acceptance criteria (requirement-by-requirement)
- The archived prior task exists as `OLD_TASK_1.md`.
- `MAIN_TASK.md` clearly states that no implementation work remains for this cleanup.
- The stale modules remain absent from `HEAD`.
- The retained low-inbound entry points and selector facade remain present.
- `PYTHONPATH=python python -m unittest tests.python.shared.test_structure_layout` passes.
- No new implementation commit is required unless future changes are made after this audit.

## Required implementation scope (frontend/backend/data/integration)
- Frontend: none.
- Backend/Python engine: none.
- Data model/migrations: none.
- Integration/E2E: none.
- Runtime services: none.

## Required tests and quality gates
- For this no-op completion task, run:
  - `PYTHONPATH=python python -m unittest tests.python.shared.test_structure_layout`
- If any future implementation changes are made, rerun the targeted suites from `OLD_TASK_1.md` and update this task before proceeding:
  - `PYTHONPATH=python python -m unittest tests.python.test_output.test_test_runner_streaming_fallback`
  - `PYTHONPATH=python python -m unittest tests.python.ui.test_selector_package_exports`
  - `PYTHONPATH=python python -m unittest tests.python.shared.test_import_audit`
  - `PYTHONPATH=python python -m unittest tests.python.runtime.test_cli_packaging`
  - `PYTHONPATH=python python scripts/release_shipability_gate.py --repo . --skip-build`

## Edge cases and failure handling
- If any stale module reappears, treat it as a regression and remove it again unless new code evidence proves it is actively imported and intentionally part of the runtime surface.
- If a retained low-inbound entry point is reported as orphaned by codegraph, cross-check raw references and string-invocation paths before making any deletion decision.
- Codegraph Python import resolution is incomplete for this repo; raw source references and targeted tests remain the authority for this cleanup.

## Definition of done
- `OLD_TASK_1.md` contains the archived prior task.
- This `MAIN_TASK.md` contains only the completion audit and explicitly states that no implementation work remains.
- `PYTHONPATH=python python -m unittest tests.python.shared.test_structure_layout` passes.
- The final handoff reports the archive file name, implemented-vs-remaining scope, git evidence commands used, and any material residual risks.
