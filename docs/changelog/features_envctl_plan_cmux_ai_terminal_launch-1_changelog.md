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

## 2026-03-17 - Explicit cmux workspace override

Scope:
- Added a plan-agent workspace override so operators can target a specific cmux workspace instead of relying only on caller context.

Key behavior changes:
- New `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` config/env key explicitly selects the workspace used for `cmux new-surface`, `rename-tab`, `respawn-pane`, and typed command injection.
- Setting `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` now implicitly enables plan-agent terminal launch, even when `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` is unset.
- Inspection/explain-startup surfaces now report the effective workspace selection when the override is configured.

Files / modules touched:
- `python/envctl_engine/config/__init__.py`
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `python/envctl_engine/runtime/inspection_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`
- `tests/python/runtime/test_prereq_policy.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_explicit_workspace_override_implies_enablement_and_is_used` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity.EngineRuntimeCommandParityTests.test_explain_startup_json_reports_plan_agent_workspace_override` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy.PrereqPolicyTests.test_plan_workspace_override_implies_plan_agent_prereqs` -> passed

Config / env / migrations:
- Added `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`.
- No migrations.

Risks / notes:
- The override expects a valid cmux workspace id string. Envctl passes it through directly rather than attempting to resolve/fix invalid ids.

## 2026-03-17 - Workspace title resolution

Scope:
- Extended explicit plan-agent workspace overrides so operators can use human workspace titles instead of only raw cmux refs.

Key behavior changes:
- `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` now accepts cmux workspace titles such as `envctl`.
- When the override does not already look like a workspace ref, UUID, or index, envctl resolves it through `cmux list-workspaces` and uses the matching `workspace:<n>` ref for subsequent commands.
- Raw refs, UUIDs, and indexes continue to work unchanged.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_explicit_workspace_override_resolves_workspace_name` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_explicit_workspace_override_implies_enablement_and_is_used` -> passed

Config / env / migrations:
- No new config keys.
- Existing `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` now accepts workspace titles.

Risks / notes:
- Title resolution depends on `cmux list-workspaces` returning titles in the current CLI format. If cmux changes that output shape, title lookup may need adjustment.

## 2026-03-17 - CMUX alias env support

Scope:
- Added shorthand env aliases for common plan-agent cmux launch workflows.

Key behavior changes:
- `CMUX=true` now enables plan-agent launch against the current cmux workspace context.
- `CMUX_WORKSPACE=<value>` now aliases `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=<value>` and therefore also enables the feature.
- Canonical `ENVCTL_PLAN_AGENT_*` keys continue to take precedence when both canonical and alias forms are present.

Files / modules touched:
- `python/envctl_engine/config/__init__.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_prereq_policy.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_cmux_alias_enables_current_workspace_launch` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_cmux_workspace_alias_resolves_workspace_name` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy.PrereqPolicyTests.test_cmux_alias_implies_plan_agent_prereqs` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity.EngineRuntimeCommandParityTests.test_explain_startup_json_reports_cmux_alias_enablement` -> passed

Config / env / migrations:
- Added shorthand env alias support for `CMUX` and `CMUX_WORKSPACE`.
- No migrations.

Risks / notes:
- Alias handling is intentionally one-way into the canonical config keys. Existing `CMUX_WORKSPACE_ID` from cmux itself remains separate and continues to represent the caller workspace context.

## 2026-03-17 - Default preset switched to implement_task

Scope:
- Changed the plan-agent launch default slash command from `implement_plan` to `implement_task`.

Key behavior changes:
- Newly launched Codex/OpenCode plan-agent sessions now type `/implement_task` by default.
- `implement_plan` remains installed and available as an explicit alias preset when users choose it via `ENVCTL_PLAN_AGENT_PRESET`.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `python/envctl_engine/config/__init__.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support`

Config / env / migrations:
- Default `ENVCTL_PLAN_AGENT_PRESET` changed from `implement_plan` to `implement_task`.
- No migrations.

Risks / notes:
- Users who explicitly configured `ENVCTL_PLAN_AGENT_PRESET=implement_plan` keep the old behavior. Only the default changed.

## 2026-03-17 - Create missing named workspaces

Scope:
- Extended explicit workspace targeting so named cmux workspaces are created automatically when missing.

Key behavior changes:
- When `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` or `CMUX_WORKSPACE` specifies a workspace title that is not present in `cmux list-workspaces`, envctl now creates a new workspace, renames it to the requested title, and launches the plan-agent surfaces there.
- Existing named workspaces still resolve to their current `workspace:<n>` refs without creation.
- Raw workspace refs / UUIDs / indexes continue to pass through unchanged.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed

Config / env / migrations:
- No new config keys.
- Existing explicit workspace overrides now create missing named workspaces automatically.

Risks / notes:
- Workspace creation uses `cmux new-workspace --cwd <repo-root>` followed by `cmux rename-workspace`. If cmux changes those command semantics, the creation flow may need adjustment.

## 2026-03-17 - Codex launches use /prompts preset routing

Scope:
- Adjusted the Codex plan-agent launch command so envctl sends Codex prompt presets through the `/prompts:` namespace.

Key behavior changes:
- Codex plan-agent launches now type `/prompts:implement_task` by default instead of `/implement_task`.
- OpenCode launch behavior stays unchanged and continues to send `/<preset>`.
- Stored preset values remain plain preset names such as `implement_task`; only the typed launch command changed.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/ai-playbooks.md`
- `docs/user/planning-and-worktrees.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- This assumes current Codex prompt invocation is routed through `/prompts:<preset>`. If the Codex CLI changes that command namespace again, only the launch formatter should need adjustment.
