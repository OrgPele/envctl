## 2026-03-18 - Prompt overwrite confirmation and origin-side review preset

Scope:
- Replaced `install-prompts` backup-on-overwrite behavior with a single aggregated confirmation flow that overwrites prompt files in place.
- Added a new built-in `review_worktree_imp` prompt preset for read-only review of an implementation worktree from the local/origin repo CLI.
- Updated prompt-install docs to reflect the new overwrite contract and the expanded preset inventory.

Key behavior changes:
- `install-prompts` now precomputes its install plan, detects overwrite targets before writing, and prompts once for the whole command when interactive approval is required.
- `--yes` and `--force` now approve overwrite operations for automation and other non-interactive runs.
- `--json` mode and non-TTY runs now fail cleanly when overwrite approval is required but not pre-approved, instead of prompting or creating `.bak-*` prompt files.
- Existing prompt installs still report `written` vs `overwritten`, but new installs no longer emit backup paths.
- Added `review_worktree_imp`, which treats the current repo as the unedited baseline, takes the target worktree via `$ARGUMENTS`, and keeps the review read-only by default.
- Preserved the existing plan-agent default preset and workspace-targeting behavior; no cmux launch wiring changed.

Files / modules touched:
- `python/envctl_engine/runtime/prompt_install_support.py`
- `python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md`
- `tests/python/runtime/test_prompt_install_support.py`
- `tests/python/runtime/test_command_exit_codes.py`
- `docs/user/ai-playbooks.md`
- `docs/reference/commands.md`
- `docs/user/python-engine-guide.md`
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`

Tests run + results:
- `python3 -m unittest tests.python.runtime.test_prompt_install_support tests.python.runtime.test_command_exit_codes` -> passed
- `python3 -m unittest tests.python.runtime.test_prompt_install_support tests.python.runtime.test_command_exit_codes tests.python.runtime.test_engine_runtime_dispatch` -> passed

Config / env / migrations:
- No new config keys or migrations.
- `install-prompts` now consumes the already-parsed `--yes` and `--force` flags for overwrite approval.

Risks / notes:
- The targeted regression slice passed under `unittest`; the repo-local `.venv` / `pytest` environment was not present in this worktree, so the equivalent pytest command from `MAIN_TASK.md` could not be run here.
- The new `review_worktree_imp` prompt is intentionally manual and read-only; automatic post-`--plan` origin-side review launch remains out of scope.

## 2026-03-18 - Iteration rollover audit and remaining-scope rewrite

Scope:
- Audited the incomplete prompt-overwrite/origin-review delivery against the archived task, current diffs, tests, docs, and recent git history.
- Archived the prior task spec and replaced `MAIN_TASK.md` with a verification-closeout-only task focused on the remaining uncompleted work.

Key behavior changes:
- No production runtime behavior changed in this rollover step.
- Archived `MAIN_TASK.md` to `OLD_TASK_1.md`.
- Rewrote `MAIN_TASK.md` so it now contains only the remaining scope: repo-standard `.venv`/pytest validation, CLI-visible integration coverage, repo-local smoke verification, and any fixes uncovered by that stronger verification pass.

Files / modules touched:
- `OLD_TASK_1.md`
- `MAIN_TASK.md`
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`

Tests run + results:
- No additional product-behavior tests were run in this rollover step.
- Audit evidence gathered from:
  - `git status --short`
  - `git diff --name-status`
  - `git diff --cached --name-status`
  - `git log --oneline --decorate -n 30`
  - `python3 -m pytest --version` -> failed (`No module named pytest`)

Config / env / migrations:
- No config changes or migrations.
- Confirmed `.venv` is currently missing in this worktree; the replacement `MAIN_TASK.md` now makes repo-local `.venv` bootstrap an explicit remaining requirement.

Risks / notes:
- The carry-forward scope is verification-oriented, not core feature implementation: repo evidence shows the main runtime/docs/test changes landed, but the authoritative pytest lane and CLI-visible smoke/integration validation were not completed.
