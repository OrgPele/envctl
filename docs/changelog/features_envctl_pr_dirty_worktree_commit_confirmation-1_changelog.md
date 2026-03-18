## 2026-03-17 - Dashboard PR dirty-worktree commit confirmation

### Scope
Added a dashboard-side PR preflight that detects dirty selected worktrees, asks whether to run the normal interactive commit flow first, and only proceeds to PR dispatch after that preflight is handled.

### Key behavior changes
- `python/envctl_engine/actions/project_action_domain.py`
  - added `DirtyWorktreeReport` plus `probe_dirty_worktree(...)` to classify staged, unstaged, and untracked changes from `git status --porcelain`
- `python/envctl_engine/ui/dashboard/orchestrator.py`
  - PR dashboard flow now probes selected targets for dirty state after PR target/base selection
  - PR routes are deduplicated by resolved git root before commit/PR dispatch so shared-root multi-selects only run one branch-level action per root
  - when dirty targets exist, the dashboard prompts `yes / no / cancel` before PR dispatch
  - `yes` routes the dirty subset through the existing interactive commit flow, preserving the normal commit message prompt and `ENVCTL_ACTION_INTERACTIVE=1` semantics
  - `no` skips commit and continues to PR dispatch
  - `cancel` aborts PR creation without dispatching either command
  - failed commit preflight now blocks PR dispatch and reuses existing interactive failure detail rendering
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
  - added coverage for accept / decline / cancel / clean / typed-command / commit-failure / dirty-subset PR dashboard paths
- `tests/python/actions/test_actions_cli.py`
  - added classification coverage for staged, unstaged, untracked, and mixed porcelain status parsing
- `tests/python/actions/test_actions_parity.py`
  - added parity coverage confirming interactive PR routes still export `ENVCTL_ACTION_INTERACTIVE=1`

### File paths / modules touched
- `python/envctl_engine/actions/project_action_domain.py`
- `python/envctl_engine/ui/dashboard/orchestrator.py`
- `tests/python/actions/test_actions_cli.py`
- `tests/python/actions/test_actions_parity.py`
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
- `docs/changelog/features_envctl_pr_dirty_worktree_commit_confirmation-1_changelog.md`

### Tests run + results
- `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_cli tests.python.ui.test_dashboard_orchestrator_restart_selector tests.python.actions.test_actions_parity`
  - result: `Ran 169 tests`, `OK`
- `./.venv/bin/python -m pytest tests/python/ui/test_dashboard_orchestrator_restart_selector.py -q`
  - result: `48 passed, 8 subtests passed`
- `./.venv/bin/python -m pytest tests/python/actions/test_actions_cli.py tests/python/ui/test_dashboard_orchestrator_restart_selector.py tests/python/actions/test_actions_parity.py -q`
  - result: `172 passed, 17 subtests passed`

### Config / env / migrations
- No config schema changes.
- No migrations.
- Reused existing action env propagation, including `ENVCTL_ACTION_INTERACTIVE`, `ENVCTL_COMMIT_MESSAGE`, and existing PR env flags.

### Risks / notes
- Dirty detection is repo-root based per selected target git root, so multiple selected projects sharing the same git root are intentionally deduplicated for the preflight commit prompt.
- Shared-root multi-select PR dispatch is also deduplicated at the route layer, because PR/commit actions operate at git-root scope rather than per logical project within the same branch.
- The existing dashboard PR message prompt still occurs before the dirty-worktree commit confirmation, because the PR target/base selection flow owns that prompt today.
- Hardening pass: `_prompt_yes_no_dialog(...)` now supports both the dashboard test stub signature (`title=..., prompt=...`) and the real runtime `_prompt_yes_no(prompt)` shape, and blank raw-input fallback is treated as decline rather than implicit commit acceptance.
