## 2026-03-18 - Verification closeout rerun in active worktree

Scope:
- Revalidated the prompt overwrite and origin-review preset behavior in the active checked-out worktree using the repo-local Python 3.12 environment.
- Confirmed the focused pytest lane and repo-local installed-CLI smoke path still pass without requiring any runtime, test, or doc fixes.

Key behavior changes:
- No production behavior changed in this rerun.
- Verified again that the CLI-visible `install-prompts` path reports `written` on first install, `overwritten` on approved repeat install, and leaves no `.bak-*` artifacts behind.
- Verified again that the installed `review_worktree_imp` prompt keeps the baseline-repo, `$ARGUMENTS` override, read-only, and findings-first review contract.

Files / modules touched:
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`

Tests run + results:
- Repo-local `.venv` validation environment:
  - `./.venv/bin/python --version`
    - result: `Python 3.12.12`
  - `./.venv/bin/python -m pip install -e '.[dev]'`
    - result: passed
- Focused pytest lane:
  - `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py tests/python/runtime/test_engine_runtime_dispatch.py -q`
    - result: `47 passed, 4 subtests passed in 0.17s`
- Repo-local smoke validation:
  - `mkdir -p tmp && mktemp -d "$PWD/tmp/prompt-smoke-home-seq.XXXXXX"`
    - result: created `tmp/prompt-smoke-home-seq.CdbTGZ`
  - `HOME="$PWD/tmp/prompt-smoke-home-seq.CdbTGZ" ./.venv/bin/envctl install-prompts --cli codex`
    - result: passed; all seven codex presets reported `written`
  - `HOME="$PWD/tmp/prompt-smoke-home-seq.CdbTGZ" ./.venv/bin/envctl install-prompts --cli codex --yes`
    - result: passed; all seven codex presets reported `overwritten`
  - `HOME="$PWD/tmp/prompt-smoke-home-seq.CdbTGZ" ./.venv/bin/envctl install-prompts --cli codex --preset review_worktree_imp --yes`
    - result: passed; `review_worktree_imp.md` was overwritten in place through the normal command path
  - `find "$PWD/tmp/prompt-smoke-home-seq.CdbTGZ" -name '*.bak-*' -print`
    - result: no output
  - `sed -n '1,80p' "$PWD/tmp/prompt-smoke-home-seq.CdbTGZ/.codex/prompts/review_worktree_imp.md"`
    - result: verified the written prompt states the current repo is the unedited baseline, the target worktree can come from `$ARGUMENTS`, the review is read-only by default, and the final response is findings-first

Config / env / migrations:
- Reused the existing repo-local `.venv` because it was already present in this worktree and already bound to Python `3.12.12`.
- Smoke validation kept `HOME` under `tmp/prompt-smoke-home-seq.CdbTGZ` inside the current repo root.
- No config changes or migrations.

Risks / notes:
- No additional defects were exposed by this rerun, so no production or test changes were necessary in this iteration.

## 2026-03-18 - Verification rerun in current worktree

Scope:
- Re-ran the prompt overwrite verification closeout in the current checked-out worktree using the repo-local `.venv`.
- Confirmed the focused pytest lane and repo-local CLI smoke path still pass without requiring additional runtime or test changes.

Key behavior changes:
- No production behavior changed in this rerun.
- Verified the existing CLI-path coverage still proves `install-prompts` reports `written` on first install, `overwritten` on approved repeat install, and leaves no `.bak-*` files behind.
- Verified the installed `review_worktree_imp` preset still preserves the origin-review contract in the written prompt body.

Files / modules touched:
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`

Tests run + results:
- `./.venv/bin/python -m pip install -e '.[dev]'` -> passed (refreshed the existing repo-local editable/dev install)
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py tests/python/runtime/test_engine_runtime_dispatch.py -q` -> passed (`47 passed, 4 subtests passed in 0.16s`)
- `HOME="$PWD/tmp/prompt-smoke-home.eWUt53" ./.venv/bin/envctl install-prompts --cli codex` -> passed
- `HOME="$PWD/tmp/prompt-smoke-home.eWUt53" ./.venv/bin/envctl install-prompts --cli codex --yes` -> passed
- `HOME="$PWD/tmp/prompt-smoke-home.eWUt53" ./.venv/bin/envctl install-prompts --cli codex --preset review_worktree_imp --yes` -> passed
- `find "$PWD/tmp/prompt-smoke-home.eWUt53" -name '*.bak-*' -print` -> passed (no output)

Config / env / migrations:
- Reused the existing repo-local `.venv` in this worktree; no `.venv` recreation was needed because `./.venv/bin/python` was already present.
- Smoke validation kept `HOME` under `tmp/prompt-smoke-home.eWUt53` inside the current repo root.
- No config changes or migrations.

Risks / notes:
- No additional defects were exposed by this verification rerun, so no runtime/test/doc fixes beyond this evidence update were necessary.
- The worktree already contained unrelated staged changes before this task started; this entry records only the prompt-overwrite verification slice.

## 2026-03-18 - Verification evidence refresh for prompt overwrite flow

Scope:
- Rebuilt the repo-local validation environment with the documented Python 3.12 bootstrap path.
- Re-ran the authoritative focused pytest lane for the prompt installer command path.
- Re-ran repo-local installed-CLI smoke validation for first-write, approved overwrite, and no-backup behavior.

Key behavior changes:
- No production runtime behavior changed in this verification refresh.
- Verified again that `install-prompts` writes on first install, overwrites in place on the approved second install, and does not create `.bak-*` prompt siblings.
- Verified the installed `review_worktree_imp` prompt body still preserves the origin-review contract in the written file.

Files / modules touched:
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`

Tests run + results:
- `.venv` bootstrap / repair:
  - `python3.12 -m venv .venv`
    - result: preserved the pre-existing Python `3.14.3` interpreter in `.venv`, so the env was rebuilt again with `--clear`
  - `python3.12 -m venv --clear .venv`
    - result: `.venv/bin/python --version` -> `Python 3.12.12`
  - `./.venv/bin/python -m pip install -e '.[dev]'`
    - result: passed
- Focused pytest lane:
  - `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py tests/python/runtime/test_engine_runtime_dispatch.py -q`
    - result: `47 passed, 4 subtests passed in 0.16s`
- Repo-local smoke validation:
  - `HOME="$PWD/tmp/prompt-smoke-home-seq-20260318-1" ./.venv/bin/envctl install-prompts --cli codex`
    - result: passed; all seven codex presets reported `written`
  - `HOME="$PWD/tmp/prompt-smoke-home-seq-20260318-1" ./.venv/bin/envctl install-prompts --cli codex --yes`
    - result: passed; all seven codex presets reported `overwritten`
  - `find tmp/prompt-smoke-home-seq-20260318-1 -name '*.bak-*' -print`
    - result: no output
  - `sed -n '1,120p' tmp/prompt-smoke-home-seq-20260318-1/.codex/prompts/review_worktree_imp.md`
    - result: verified the written prompt still states baseline repo, `$ARGUMENTS` override target, read-only default, and findings-first output

Config / env / migrations:
- Rebuilt the repo-local `.venv` with Python `3.12.12`.
- No runtime config changes or migrations.

Risks / notes:
- No new product defects surfaced during this refresh run.
- Smoke validation stayed within repo-local `tmp/` paths to respect the worktree boundary.

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

## 2026-03-18 - Verification closeout for prompt overwrite review preset

Scope:
- Completed the remaining verification-focused iteration for the prompt overwrite confirmation and origin-review preset work.
- Added CLI-path integration coverage through `envctl_engine.runtime.cli.run(...)`.
- Bootstrapped the repo-local `.venv`, ran the authoritative focused pytest lane, and completed repo-local smoke validation against the installed CLI entrypoint.

Key behavior changes:
- Added CLI integration coverage proving the first `install-prompts` run reports `written`, a second approved run reports `overwritten`, and no `.bak-*` prompt files are created through the real command path.
- Added CLI integration coverage proving `review_worktree_imp` installs through the normal command path and preserves the origin-review contract in the written prompt body.
- No production runtime/doc behavior changed during this closeout step; the work here completed the missing verification surface and environment setup.

Files / modules touched:
- `tests/python/runtime/test_command_exit_codes.py`
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`

Tests run + results:
- `python3 -m unittest tests.python.runtime.test_command_exit_codes` -> passed
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py tests/python/runtime/test_engine_runtime_dispatch.py -q` -> passed (`46 passed, 4 subtests passed`)
- Repo-local smoke validation passed:
  - `HOME="$PWD/.tmp/prompt-smoke-home" ./.venv/bin/envctl install-prompts --cli codex`
  - `HOME="$PWD/.tmp/prompt-smoke-home" ./.venv/bin/envctl install-prompts --cli codex --yes`
  - `find .tmp/prompt-smoke-home -name '*.bak-*' -print` -> no output
  - `HOME="$PWD/.tmp/prompt-smoke-home" ./.venv/bin/envctl install-prompts --cli codex --preset review_worktree_imp --yes`

Config / env / migrations:
- Bootstrapped the repo-local validation environment:
  - `python3.12 -m venv .venv`
  - `./.venv/bin/python -m pip install -e '.[dev]'`
- No runtime config changes or migrations.

Risks / notes:
- Smoke validation used a repo-local HOME under the current worktree and validated the non-interactive approved overwrite path; the interactive second-run prompt behavior remains covered by automated tests rather than manual smoke interaction.

## 2026-03-18 - Review prompt default target wording

Scope:
- Adjusted the `review_worktree_imp` prompt contract so it defaults to the worktree created from the current plan file and only uses `$ARGUMENTS` when the caller wants to override that target explicitly.

Key behavior changes:
- The prompt now describes the default review target as the worktree created from the current plan file.
- `$ARGUMENTS` is now documented as an optional worktree override plus optional reviewer notes, instead of the only target source.

Files / modules touched:
- `python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md`
- `tests/python/runtime/test_prompt_install_support.py`
- `tests/python/runtime/test_command_exit_codes.py`
- `docs/user/ai-playbooks.md`
- `docs/reference/commands.md`
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`

Tests run + results:
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py -q` -> passed

Config / env / migrations:
- No config changes or migrations.

Risks / notes:
- This change updates prompt/docs wording only; no runtime plan/worktree resolution code changed in this step.

## 2026-03-18 - Install-prompts defaults to all presets

Scope:
- Changed `envctl install-prompts` so omitting `--preset` installs the full built-in preset set instead of only `implement_task`.
- Updated runtime/unit coverage and user-facing docs to match the new default behavior.

Key behavior changes:
- The installer now resolves an omitted preset the same way as explicit `--preset all`.
- Dry-run and JSON output now report `preset: "all"` when the caller does not specify a preset.
- Default install and overwrite flows now operate across every built-in preset for each selected CLI target.

Files / modules touched:
- `python/envctl_engine/runtime/prompt_install_support.py`
- `tests/python/runtime/test_prompt_install_support.py`
- `tests/python/runtime/test_command_exit_codes.py`
- `docs/reference/commands.md`
- `docs/user/ai-playbooks.md`
- `docs/user/python-engine-guide.md`
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`

Tests run + results:
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py -q` -> passed (`42 passed, 4 subtests passed`)
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py tests/python/runtime/test_engine_runtime_dispatch.py -q` -> passed (`47 passed, 4 subtests passed`)

Config / env / migrations:
- No config changes or migrations.

Risks / notes:
- This changes the default file fan-out for callers who previously relied on omitted preset meaning only `implement_task`; explicit `--preset implement_task` remains available for the narrower install path.
