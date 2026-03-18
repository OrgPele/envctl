## 2026-03-17 - Repo-local envctl commit-message pointer ledger

### Scope
Replaced the default `envctl commit` message source with a repo-local `.envctl-commit-message.md` ledger that uses a single `### Envctl pointer ###` marker, then aligned the dashboard copy, installed AI prompt presets, and user docs to the new contract.

### Key behavior changes
- `python/envctl_engine/actions/project_action_domain.py`
  - removed implicit `docs/changelog/...` and `MAIN_TASK.md` fallback for default commit messages
  - added `.envctl-commit-message.md` bootstrap, single-marker validation, post-pointer payload extraction, and atomic pointer advancement after successful local commit creation
  - preserves explicit `ENVCTL_COMMIT_MESSAGE` and `ENVCTL_COMMIT_MESSAGE_FILE` precedence over the ledger flow
- `tests/python/actions/test_actions_cli.py`
  - replaced changelog-based commit tests with ledger-based coverage for bootstrap, malformed marker states, explicit override precedence, successful pointer advancement, and push-failure behavior
- `python/envctl_engine/ui/dashboard/orchestrator.py`
  - updated commit prompt copy so blank dashboard input now means “use the envctl commit log”
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
  - updated dashboard selector assertions to the new default-button wording
- `tests/python/ui/test_text_input_dialog.py`
  - updated textual dialog copy fixtures to the new envctl commit log wording
- `python/envctl_engine/runtime/prompt_templates/implement_task.md`
- `python/envctl_engine/runtime/prompt_templates/continue_task.md`
- `python/envctl_engine/runtime/prompt_templates/review_task_imp.md`
- `python/envctl_engine/runtime/prompt_templates/merge_trees_into_dev.md`
  - replaced the old append-to-changelog instruction with a repo-local `.envctl-commit-message.md` append contract that preserves a single `### Envctl pointer ###` marker
- `python/envctl_engine/runtime/prompt_templates/create_plan.md`
  - removed the stale changelog self-check line from the plan-only preset
- `tests/python/runtime/test_prompt_install_support.py`
  - added assertions that built-in preset rendering now references `.envctl-commit-message.md`, preserves the pointer marker contract, and no longer ships changelog-backed commit-default language
- `docs/reference/commands.md`
- `docs/user/ai-playbooks.md`
  - documented the new ledger-backed default commit-message workflow and install-prompts behavior

### File paths / modules touched
- `python/envctl_engine/actions/project_action_domain.py`
- `tests/python/actions/test_actions_cli.py`
- `python/envctl_engine/ui/dashboard/orchestrator.py`
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
- `tests/python/ui/test_text_input_dialog.py`
- `python/envctl_engine/runtime/prompt_templates/implement_task.md`
- `python/envctl_engine/runtime/prompt_templates/continue_task.md`
- `python/envctl_engine/runtime/prompt_templates/review_task_imp.md`
- `python/envctl_engine/runtime/prompt_templates/merge_trees_into_dev.md`
- `python/envctl_engine/runtime/prompt_templates/create_plan.md`
- `tests/python/runtime/test_prompt_install_support.py`
- `docs/reference/commands.md`
- `docs/user/ai-playbooks.md`

### Tests run + results
- `./.venv/bin/python -m pytest tests/python/actions/test_actions_cli.py -q`
  - result: `31 passed`
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/ui/test_dashboard_orchestrator_restart_selector.py tests/python/ui/test_text_input_dialog.py -q`
  - result: `51 passed, 12 subtests passed`

### Config / env / migrations
- No migrations.
- No new environment variables.
- Adds a repo-local `.envctl-commit-message.md` file contract for queued default commit-message content.

### Risks / notes
- Existing automation that still appends summaries to `docs/changelog/...` instead of `.envctl-commit-message.md` will no longer influence default `envctl commit` messages until it is updated.
- The implementation intentionally advances the ledger pointer immediately after a successful local `git commit`; a later push failure does not roll back the ledger, by design.
