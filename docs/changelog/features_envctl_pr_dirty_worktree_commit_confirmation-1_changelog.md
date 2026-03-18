## 2026-03-17 - Dashboard PR dirty-worktree commit confirmation

### Scope
Added a dashboard-side PR preflight that detects dirty selected worktrees, asks whether to run the normal interactive commit flow first, and only proceeds to PR dispatch after that preflight is handled.

### Key behavior changes
- `python/envctl_engine/actions/project_action_domain.py`
  - added `DirtyWorktreeReport` plus `probe_dirty_worktree(...)` to classify staged, unstaged, and untracked changes from `git status --porcelain`
- `python/envctl_engine/ui/dashboard/orchestrator.py`
  - PR dashboard flow now probes selected targets for dirty state after PR target/base selection
  - PR routes are deduplicated by resolved git root before commit/PR dispatch so shared-root multi-selects only run one branch-level action per root
  - when dirty targets exist, the dashboard now shows a selector-style `Commit` / `Do nothing` menu using the prompt `UNSTAGED CODE IN WORKTREE ... - DO YOU WANT TO STAGE IT?`
  - `Commit` routes the dirty subset through the existing interactive commit flow, preserving the normal commit message prompt and `ENVCTL_ACTION_INTERACTIVE=1` semantics
  - `Do nothing` skips commit and continues to PR dispatch
  - cancel still aborts PR creation through the menu's normal `Esc` / `Ctrl+C` path instead of a dedicated visible menu row
  - this specific menu now uses custom action items rather than project-picker rows, so it renders bare `Commit` / `Do nothing` labels without the usual `(project)` suffix
  - failed commit preflight now blocks PR dispatch and reuses existing interactive failure detail rendering
- `python/envctl_engine/ui/selector_model.py`
  - removed the synthetic `All projects` / `All services` shortcut rows from shared selector menus so those labels no longer appear in the interactive UI
- `python/envctl_engine/ui/textual/screens/selector/textual_app_chrome.py`
  - dropped the now-dead synthetic-all row styling after removing the synthetic selector items
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
  - added coverage for accept / decline / cancel / clean / typed-command / commit-failure / dirty-subset PR dashboard paths
- `tests/python/ui/test_selector_model.py`
  - added regression coverage confirming shared selector builders do not emit synthetic all rows even when `allow_all=True`
- `tests/python/ui/test_textual_selector_flow.py`
  - updated selector flow coverage to assert the project selector still maps untested shortcuts without a visible all row
- `tests/python/ui/test_prompt_toolkit_selector_shared_behavior.py`
  - added a backend-level regression test proving `a` still toggles all visible rows in multi-select menus
- `tests/python/ui/test_textual_selector_interaction.py`
  - added a selector binding regression test confirming textual menus still bind `a` to `toggle_visible`
- `tests/python/actions/test_actions_cli.py`
  - added classification coverage for staged, unstaged, untracked, and mixed porcelain status parsing
- `tests/python/actions/test_actions_parity.py`
  - added parity coverage confirming interactive PR routes still export `ENVCTL_ACTION_INTERACTIVE=1`

### File paths / modules touched
- `python/envctl_engine/actions/project_action_domain.py`
- `python/envctl_engine/ui/dashboard/orchestrator.py`
- `python/envctl_engine/ui/selector_model.py`
- `python/envctl_engine/ui/textual/screens/selector/textual_app_chrome.py`
- `tests/python/actions/test_actions_cli.py`
- `tests/python/actions/test_actions_parity.py`
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
- `tests/python/ui/test_selector_model.py`
- `tests/python/ui/test_textual_selector_flow.py`
- `tests/python/ui/test_prompt_toolkit_selector_shared_behavior.py`
- `tests/python/ui/test_textual_selector_interaction.py`
- `docs/changelog/features_envctl_pr_dirty_worktree_commit_confirmation-1_changelog.md`

### Tests run + results
- `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_cli tests.python.ui.test_dashboard_orchestrator_restart_selector tests.python.actions.test_actions_parity`
  - result: `Ran 169 tests`, `OK`
- `./.venv/bin/python -m pytest tests/python/ui/test_dashboard_orchestrator_restart_selector.py -q`
  - result: `48 passed, 8 subtests passed`
- `./.venv/bin/python -m pytest tests/python/actions/test_actions_cli.py tests/python/ui/test_dashboard_orchestrator_restart_selector.py tests/python/actions/test_actions_parity.py -q`
  - result: `172 passed, 17 subtests passed`
- `./.venv/bin/python -m pytest tests/python/ui/test_dashboard_orchestrator_restart_selector.py -q`
  - result: `48 passed, 8 subtests passed`
- `./.venv/bin/python -m pytest tests/python/ui/test_selector_model.py tests/python/ui/test_textual_selector_flow.py tests/python/ui/test_prompt_toolkit_selector_shared_behavior.py tests/python/ui/test_textual_selector_interaction.py -q`
  - result: `40 passed`

### Config / env / migrations
- No config schema changes.
- No migrations.
- Reused existing action env propagation, including `ENVCTL_ACTION_INTERACTIVE`, `ENVCTL_COMMIT_MESSAGE`, and existing PR env flags.

### Risks / notes
- Dirty detection is repo-root based per selected target git root, so multiple selected projects sharing the same git root are intentionally deduplicated for the preflight commit prompt.
- Shared-root multi-select PR dispatch is also deduplicated at the route layer, because PR/commit actions operate at git-root scope rather than per logical project within the same branch.
- The existing dashboard PR message prompt still occurs before the dirty-worktree commit confirmation, because the PR target/base selection flow owns that prompt today.
- Hardening pass: `_prompt_yes_no_dialog(...)` now supports both the dashboard test stub signature (`title=..., prompt=...`) and the real runtime `_prompt_yes_no(prompt)` shape, and blank raw-input fallback is treated as decline rather than implicit commit acceptance.
- UX polish: dirty-worktree confirmation now uses the same selector/menu pattern as other dashboard flows, and the clean-path PR tests explicitly stub dirty probing so they remain deterministic even when the developer worktree itself is dirty.
- Shared selectors still support full-menu selection via `a` / `Ctrl+A`; the explicit synthetic `All ...` rows were removed so that shortcut is now the only all-selection affordance in selector UIs.
