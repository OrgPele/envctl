# Worktree Changelog

## 2026-03-17 - Global Git excludes for envctl local artifacts

### Scope
Implemented the `MAIN_TASK.md` change to stop mutating repo-local ignore files during config save/bootstrap and moved envctl's local-artifact ignore contract to Git global excludes with centralized artifact inventory, updated config UX/reporting, release-gate regression coverage, and repository/docs cleanup.

### Key behavior changes
- `save_local_config(...)` still writes the repo-local `.envctl`, but it no longer edits repo `.gitignore` or `.git/info/exclude`.
- Envctl local-only artifact patterns are now centralized and currently cover:
  - `.envctl*`
  - `MAIN_TASK.md`
  - `OLD_TASK_*.md`
  - `trees/`
  - `trees-*`
- Config save now checks for an explicitly configured Git global excludes target (`core.excludesFile`) and updates only an envctl-managed block inside that user-scoped file.
- If Git global excludes is not configured, config save still succeeds but returns an actionable warning instead of silently mutating repo-local ignore files.
- Headless `envctl config --json` output now includes structured ignore-status details alongside the existing compatibility fields:
  - `ignore_updated`
  - `ignore_warning`
  - `ignore_status.code`
  - `ignore_status.scope`
  - `ignore_status.target_path`
  - `ignore_status.managed_patterns`
- Wizard/domain review text and user docs now describe the Git global excludes contract instead of promising repo `.gitignore` mutation.
- Release-gate coverage now proves envctl-owned untracked artifacts are ignored correctly through standard Git global excludes semantics while unrelated untracked files still fail shipability checks.
- This repository's tracked `.gitignore` no longer carries envctl-owned local artifact entries.

### Files and Modules Touched
- `python/envctl_engine/config/local_artifacts.py`
- `python/envctl_engine/config/git_global_ignore.py`
- `python/envctl_engine/config/persistence.py`
- `python/envctl_engine/config/command_support.py`
- `python/envctl_engine/ui/textual/screens/config_wizard.py`
- `tests/python/config/test_config_persistence.py`
- `tests/python/config/test_config_command_support.py`
- `tests/python/config/test_config_wizard_domain.py`
- `tests/python/config/test_config_wizard_textual.py`
- `tests/python/runtime/test_release_shipability_gate.py`
- `tests/python/runtime/test_release_shipability_gate_cli.py`
- `README.md`
- `docs/reference/configuration.md`
- `docs/user/first-run-wizard.md`
- `docs/user/getting-started.md`
- `docs/user/python-engine-guide.md`
- `docs/developer/config-and-bootstrap.md`
- `.gitignore`

### Tests Run
- `PYTHONPATH=python python3 -m unittest tests.python.config.test_config_persistence`
  - Result: passed (`21` tests)
- `PYTHONPATH=python python3 -m unittest tests.python.config.test_config_command_support`
  - Result: passed (`4` tests)
- `PYTHONPATH=python python3 -m unittest tests.python.config.test_config_wizard_domain tests.python.config.test_config_wizard_textual`
  - Result: passed (`13` tests, `2` skipped because Textual is not installed in this environment)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_release_shipability_gate tests.python.runtime.test_release_shipability_gate_cli`
  - Result: passed (`18` tests)

### Config, Env, and Migrations
- New internal module: `python/envctl_engine/config/local_artifacts.py`
- New internal module: `python/envctl_engine/config/git_global_ignore.py`
- New JSON save-result field: `ignore_status`
- No schema migrations
- No external service config changes
- User-visible prerequisite: Git `core.excludesFile` must be configured if operators want envctl-owned local artifacts hidden through global excludes

### Risks and Notes
- The current implementation intentionally requires an explicitly configured `core.excludesFile`; it does not silently create or auto-configure a new global excludes target.
- Existing downstream repos may still contain historical envctl ignore lines in tracked `.gitignore`; envctl now leaves those alone and only cleans up this repository's tracked ignore policy.
- Tracked files are unaffected by Git ignore semantics, so global excludes only helps with untracked envctl-owned local artifacts.

## 2026-03-18 - Wizard-only global excludes bootstrap

### Scope
Refined the global-ignore behavior so only the interactive config wizard may bootstrap Git global excludes when `core.excludesFile` is missing, while headless/plain config saves remain warning-only and never mutate user-global Git config.

### Key behavior changes
- `python/envctl_engine/config/persistence.py`
  - added a save path that keeps default persistence read-only for global ignore mutation unless the caller explicitly opts in
  - generic/headless `save_local_config(...)` now writes `.envctl` and reports ignore status without auto-configuring `core.excludesFile`
- `python/envctl_engine/config/git_global_ignore.py`
  - added explicit bootstrap support for configuring a default global excludes target and writing the envctl-managed block
- `python/envctl_engine/ui/textual/screens/config_wizard.py`
  - wizard save now opts into the bootstrap-capable path
- `python/envctl_engine/config/wizard_domain.py`
  - save messaging now distinguishes successful wizard bootstrap with a concrete “Configured Git global excludes ...” message

### Files and Modules Touched
- `python/envctl_engine/config/git_global_ignore.py`
- `python/envctl_engine/config/persistence.py`
- `python/envctl_engine/config/wizard_domain.py`
- `python/envctl_engine/ui/textual/screens/config_wizard.py`
- `tests/python/config/test_config_persistence.py`
- `tests/python/config/test_config_command_support.py`
- `tests/python/config/test_config_wizard_domain.py`

### Tests Run
- `PYTHONPATH=python python3 -m unittest tests.python.config.test_config_persistence tests.python.config.test_config_wizard_domain tests.python.config.test_config_command_support tests.python.config.test_config_wizard_textual`
  - Result: passed (`44` tests, `2` skipped because Textual is not installed in this environment)

### Risks and Notes
- The wizard path now bootstraps `~/.gitignore_global` when no `core.excludesFile` is configured; non-wizard config commands still only warn.
- This follow-up keeps the side effect scoped to explicit configuration UX, but it does not yet add an in-wizard decline/learn-more choice — bootstrap happens through the wizard save path itself.
