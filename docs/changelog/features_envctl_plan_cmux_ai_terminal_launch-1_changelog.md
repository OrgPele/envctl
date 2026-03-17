## 2026-03-17 - Plan cmux AI terminal launch

Scope:
- Added an optional `--plan`-only post-sync workflow that launches `cmux` AI terminals for newly created planning worktrees.
- Kept default-off behavior unchanged for ordinary `plan` runs and isolated launch orchestration from low-level worktree creation.

Key behavior changes:
- Planning sync now preserves structured metadata about newly created worktrees so startup can launch once per new worktree after reconciliation completes.
- When `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true`, envctl validates feature-specific prereqs, resolves caller/current cmux workspace context, creates a new surface per new worktree, renames the tab, starts the configured shell, types `cd <worktree>`, launches the selected AI CLI, and sends the configured slash preset.
- Added `implement_plan` as an envctl-owned prompt alias while preserving `implement_task`.
- `show-config --json` and `explain-startup --json` now surface plan-agent launch state/config.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `python/envctl_engine/planning/worktree_domain.py`
- `python/envctl_engine/planning/worktree_orchestrator.py`
- `python/envctl_engine/startup/startup_orchestrator.py`
- `python/envctl_engine/runtime/cli.py`
- `python/envctl_engine/runtime/inspection_support.py`
- `python/envctl_engine/config/__init__.py`
- `python/envctl_engine/runtime/prompt_templates/implement_plan.md`
- `tests/python/planning/test_planning_worktree_setup.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_prereq_policy.py`
- `tests/python/runtime/test_prompt_install_support.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`
- `tests/python/startup/test_startup_orchestrator_flow.py`
- `tests/python/runtime/test_engine_runtime_real_startup.py`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`
- `docs/reference/commands.md`
- `docs/reference/configuration.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support`
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prompt_install_support`
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_planning_worktree_setup`
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prereq_policy`
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity`
- `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_orchestrator_flow`
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
- Combined verification run passed: `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support tests.python.runtime.test_prompt_install_support tests.python.planning.test_planning_worktree_setup tests.python.runtime.test_prereq_policy tests.python.runtime.test_engine_runtime_command_parity tests.python.startup.test_startup_orchestrator_flow tests.python.runtime.test_engine_runtime_real_startup`

Config / env / migrations:
- Added feature env/config keys: `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE`, `ENVCTL_PLAN_AGENT_CLI`, `ENVCTL_PLAN_AGENT_PRESET`, `ENVCTL_PLAN_AGENT_SHELL`, `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT`, `ENVCTL_PLAN_AGENT_CLI_CMD`.
- No database migrations.

Risks / notes:
- The launch flow uses bounded sleeps between shell startup, AI CLI launch, and slash-command injection; timing may still need adjustment on slower or heavily customized cmux setups.
- `implement_plan` is added as an alias, not a replacement. Existing `implement_task` workflows remain valid.

## 2026-03-17 - PTY selector test hermeticity follow-up

Scope:
- Hardened the PTY selector throughput tests so they no longer inherit selector-mode overrides from the parent unittest process.
- Added a regression that proves `default_textual` PTY expectations remain stable even when the parent process exports `ENVCTL_UI_SIMPLE_MENUS=1`.

Key behavior changes:
- The PTY child test environment now normalizes terminal state for subprocess-based selector tests by forcing `PYTHONUNBUFFERED=1`, ensuring `TERM` is present, and clearing selector-affecting env such as `ENVCTL_UI_SIMPLE_MENUS`, selector backend overrides, `TERM_PROGRAM`, and escape-delay overrides.
- Default-textual PTY tests now remain on the textual path regardless of parent-process selector config leakage.

Files / modules touched:
- `tests/python/ui/test_interactive_selector_key_throughput_pty.py`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.ui.test_interactive_selector_key_throughput_pty.SelectorKeyThroughputPtyTests.test_project_selector_default_textual_ignores_parent_simple_menus_env_in_pty` -> passed after fix
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.ui.test_interactive_selector_key_throughput_pty` -> passed
- `ENVCTL_UI_SIMPLE_MENUS=1 PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.ui.test_interactive_selector_key_throughput_pty` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_planning_worktree_setup tests.python.planning.test_plan_agent_launch_support tests.python.runtime.test_prereq_policy tests.python.runtime.test_prompt_install_support tests.python.runtime.test_engine_runtime_command_parity tests.python.startup.test_startup_orchestrator_flow tests.python.runtime.test_engine_runtime_real_startup tests.python.ui.test_interactive_selector_key_throughput_pty` -> passed

Config / env / migrations:
- No runtime config changes.
- Test-only environment normalization for PTY subprocess coverage.

Risks / notes:
- This follow-up addresses a concrete source of test nondeterminism caused by inherited parent env. It does not eliminate every possible PTY timing issue, but the previously identified selector-backend leak is now covered by a regression test.
