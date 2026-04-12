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

## 2026-03-17 - Restore implement_plan as the default launched preset

Scope:
- Realigned the optional post-`--plan` cmux launch flow with `MAIN_TASK.md` so newly opened AI terminals default back to `implement_plan`.
- Kept `implement_task` available as a backward-compatible installed preset while updating launch tests and user-facing docs to reflect the restored default contract.

Key behavior changes:
- `ENVCTL_PLAN_AGENT_PRESET` now defaults to `implement_plan` in the runtime config layer and in plan-agent launch support when no explicit override is set.
- Codex plan-agent launches now default to typing `/prompts:implement_plan`; OpenCode plan-agent launches now default to typing `/implement_plan`.
- The focused launch tests were updated so they validate the real default path instead of forcing the legacy preset through test-only env overrides.
- Planning/reference docs now describe `implement_plan` as the default launch preset and `implement_task` as an available backward-compatible alternative.

Files / modules touched:
- `python/envctl_engine/config/__init__.py`
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prompt_install_support tests.python.runtime.test_prereq_policy tests.python.runtime.test_engine_runtime_real_startup tests.python.startup.test_startup_orchestrator_flow` -> passed
- Earlier focused verification during the same implementation pass also passed for:
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prompt_install_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prereq_policy`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_orchestrator_flow`

Config / env / migrations:
- Restored the default `ENVCTL_PLAN_AGENT_PRESET` to `implement_plan`.
- No database migrations.

Risks / notes:
- Workspace-wide Python LSP diagnostics still report pre-existing errors in unrelated UI/textual modules; no new diagnostics were introduced in the files touched for this change.
- The launch flow still depends on bounded readiness polling around `cmux` and the selected AI CLI, so timing may need future tuning on slower machines or after upstream CLI UI changes.

## 2026-03-17 - Restore implement_plan as the plan-agent launch default

Scope:
- Realigned the optional post-`--plan` cmux launch flow with `MAIN_TASK.md` so envctl defaults newly launched agent surfaces to `implement_plan` again.
- Kept prompt installation coverage and prompt alias support intact while updating launch-focused tests and docs to match the restored contract.

Key behavior changes:
- `ENVCTL_PLAN_AGENT_PRESET` now defaults to `implement_plan` in the plan-agent launch config and launch helper resolution path.
- Codex/OpenCode launch tests now explicitly cover the `implement_plan` default while tolerating the current readiness-polling sequence instead of overfitting to every intermediate `cmux read-screen` call.
- User-facing docs now describe `implement_plan` as the default launch preset and `implement_task` as a backward-compatible available preset.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `python/envctl_engine/config/__init__.py`
- `python/envctl_engine/config/profile_defaults.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_prompt_install_support.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_launch_sequence_uses_cmux_commands_for_codex tests.python.planning.test_plan_agent_launch_support.PlanAgentLaunchSupportTests.test_launch_sequence_supports_opencode_and_current_workspace_fallback` -> passed
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support tests.python.runtime.test_prereq_policy tests.python.runtime.test_prompt_install_support tests.python.runtime.test_engine_runtime_command_parity tests.python.runtime.test_engine_runtime_real_startup tests.python.startup.test_startup_orchestrator_flow tests.python.config.test_config_persistence` -> passed

Config / env / migrations:
- Restored the plan-agent launch default preset to `ENVCTL_PLAN_AGENT_PRESET=implement_plan`.
- No migrations.

Risks / notes:
- The broader runtime diagnostics printed during regression runs still report pre-existing parity/readiness warnings unrelated to this feature change.
- `install-prompts` continues to support both `implement_plan` and `implement_task`; the change here is specifically the default used by the plan-agent launch flow.

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

## 2026-03-17 - Restore implement_plan as the launched default

Scope:
- Corrected the remaining contract mismatch between `MAIN_TASK.md` and the live plan-agent launch flow so newly opened `cmux` AI surfaces default to `implement_plan`.
- Kept `implement_task` intact as an explicit backward-compatible preset while making the launch helper, config surface, inspection output, and docs agree on the same default.

Key behavior changes:
- `ENVCTL_PLAN_AGENT_PRESET` now defaults to `implement_plan` in config resolution and in the plan-agent launch helper when no override is provided.
- Codex plan-agent launches now type `/prompts:implement_plan` by default, and OpenCode plan-agent launches now type `/implement_plan`.
- `explain-startup --json` now reports `implement_plan` as the effective preset for enabled plan-agent launch inspection.
- User and reference docs now describe `implement_plan` as the default launched preset and `implement_task` as the available compatibility override.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `python/envctl_engine/config/__init__.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `.venv/bin/python -m pytest -q tests/python/planning/test_plan_agent_launch_support.py tests/python/runtime/test_engine_runtime_command_parity.py` -> passed
- `.venv/bin/python -m pytest -q tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_planning_worktree_setup.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_engine_runtime_real_startup.py tests/python/runtime/test_engine_runtime_command_parity.py` -> passed (`249 passed, 6 subtests passed`)

Config / env / migrations:
- Restored the default `ENVCTL_PLAN_AGENT_PRESET` value to `implement_plan` for the plan-agent launch flow.
- No database migrations.

Risks / notes:
- The launch workflow still depends on bounded readiness polling around `cmux` and the selected AI CLI; if upstream CLI UIs or machine timing differ substantially, the waits may need future tuning.

## 2026-03-17 - Restore implement_task as the launched default

Scope:
- Reverted the plan-agent launch default from `implement_plan` back to the repo’s earlier `implement_task` behavior.
- Kept the `implement_plan` prompt alias available for explicit use while making config resolution, launch sequencing, inspection output, and docs agree on the restored default.

Key behavior changes:
- `ENVCTL_PLAN_AGENT_PRESET` now defaults back to `implement_task`.
- Codex plan-agent launches again type `/prompts:implement_task` by default, and OpenCode launches again type `/implement_task`.
- `explain-startup --json` again reports `implement_task` as the effective preset when the plan-agent launch feature is enabled.
- User and reference docs now describe `implement_task` as the default launched preset and `implement_plan` as the optional compatibility alias.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `python/envctl_engine/config/__init__.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `.venv/bin/python -m pytest -q tests/python/planning/test_plan_agent_launch_support.py tests/python/runtime/test_engine_runtime_command_parity.py` -> passed
- `.venv/bin/python -m pytest -q tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_planning_worktree_setup.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_engine_runtime_real_startup.py tests/python/runtime/test_engine_runtime_command_parity.py` -> passed (`249 passed, 6 subtests passed`)

Config / env / migrations:
- Restored the default `ENVCTL_PLAN_AGENT_PRESET` value to `implement_task`.
- No database migrations.

Risks / notes:
- The launch workflow still depends on bounded readiness polling around `cmux` and the selected AI CLI; timing may still need future tuning on slower machines or after upstream CLI UI changes.
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

## 2026-03-17 - Harden prompt submission timing for Codex and OpenCode

Scope:
- Adjusted plan-agent terminal launch timing so slower CLI startup and prompt confirmation flows are handled reliably.

Key behavior changes:
- OpenCode now waits longer after startup before envctl types the prompt command, which gives the CLI time to finish loading.
- Both Codex and OpenCode now receive a second `Enter` after the prompt command so the prompt is both selected and submitted.
- Codex keeps using `/prompts:<preset>` and OpenCode keeps using `/<preset>`; only the launch timing and final confirmation flow changed.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- The OpenCode startup delay is a fixed default chosen from current observed behavior. If startup time varies materially by machine or future CLI release, making the delay configurable may still be worthwhile.

## 2026-03-17 - Probe OpenCode readiness from cmux screen state

Scope:
- Replaced the blind OpenCode startup sleep with a best-effort readiness probe that reads the launched cmux surface until the CLI looks interactive.

Key behavior changes:
- OpenCode launch now polls `cmux read-screen` for the new surface instead of always waiting a fixed delay before sending the preset command.
- The readiness probe strips ANSI sequences, ignores common loading text, and looks for a prompt-like marker near the bottom of the screen.
- If no ready screen pattern appears before the timeout window ends, envctl still proceeds, so launch behavior degrades back to timeout-based rather than hanging indefinitely.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- The OpenCode readiness matcher is intentionally generic. If a future OpenCode release changes its prompt shape or startup text substantially, the matcher may miss readiness and fall back to the timeout path.

## 2026-03-17 - Paste OpenCode prompt commands through cmux buffer

Scope:
- Changed the final OpenCode prompt injection step to use cmux paste semantics instead of plain terminal text send.

Key behavior changes:
- OpenCode prompt commands are now sent with `cmux set-buffer` plus `cmux paste-buffer` before the confirmation Enter presses.
- Codex remains on the existing direct text-send path.
- This avoids the case where OpenCode appears fully loaded but ignores the direct prompt text injection.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- This relies on current cmux buffer commands continuing to work as documented. If cmux changes `set-buffer` / `paste-buffer` semantics, the OpenCode prompt-injection path would need to be adjusted.

## 2026-03-17 - Recognize loaded OpenCode composer layout

Scope:
- Updated the OpenCode readiness matcher to recognize the actual loaded composer screen observed in cmux instead of waiting only for a prompt-glyph layout.

Key behavior changes:
- The OpenCode readiness probe now treats the composer layout as ready when the surface shows the loaded `Ask anything...` UI together with command/status affordances such as `ctrl+p commands` and `/status`.
- This prevents the launch flow from timing out and sending the preset before OpenCode has actually reached its interactive composer state.
- Existing loading text such as `Loading workspace...` is still treated as not ready.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- The matcher still depends on broadly stable OpenCode UI text. If OpenCode substantially changes its composer copy, status strip, or command hints, the probe may again fall back to the timeout path until the matcher is updated.

## 2026-03-17 - Launch OpenCode directly via respawn command

Scope:
- Reworked the OpenCode bootstrap path so envctl no longer types `opencode` into an interactive shell and instead starts it directly from the pane respawn command.

Key behavior changes:
- OpenCode surfaces now respawn with a direct command equivalent to `zsh -lc 'cd <worktree> && exec opencode'`.
- The old fragile sequence of typing `cd <worktree>`, pressing Enter, typing `opencode`, and pressing Enter is skipped for OpenCode only.
- After the direct launch, envctl still waits for the loaded OpenCode composer screen and then injects the preset command.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- This assumes the configured OpenCode command is safe to `exec` directly from the respawn shell command. If users rely on complex shell-only wrappers in `ENVCTL_PLAN_AGENT_CLI_CMD`, quoting may need further tightening.

## 2026-03-17 - Restore caller focus and stabilize prompt submission

Scope:
- Improved the interactive cmux handoff so envctl returns to the caller surface quickly and makes prompt submission less jumpy.

Key behavior changes:
- When envctl is launched from a cmux terminal in the same workspace, the newly created plan-agent surface is immediately repositioned with `move-surface --focus false`, which returns focus to the original caller tab as soon as possible.
- After envctl injects the preset command, it now sends an `End` key before the first `Enter`, so submission happens from the end of the inserted text instead of the beginning.
- Added a longer pre-submit settle delay before the first `Enter` to give the CLI composer more time to absorb pasted or typed prompt text.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- Best-effort focus restoration depends on the caller having `CMUX_WORKSPACE_ID` and `CMUX_SURFACE_ID` in its environment, which is true for normal cmux-launched terminals but not for arbitrary external callers.

## 2026-03-17 - Restore typed interactive launch flow for OpenCode

Scope:
- Corrected the new OpenCode launch path so it follows the authoritative `MAIN_TASK.md` interaction model instead of bypassing the shell with a respawn bootstrap shortcut.

Key behavior changes:
- OpenCode surfaces now respawn as a normal shell again instead of `exec`-ing OpenCode directly from the pane command.
- Envctl now types the same explicit steps for OpenCode that the spec requires for plan-agent terminals: `cd <worktree>`, launch the CLI, wait for readiness, then send the preset slash command through `cmux send` / `send-key`.
- The OpenCode readiness probe remains in place, so envctl still waits for the interactive surface to look ready before sending the slash command.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_planning_worktree_setup` -> passed
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prereq_policy` -> passed
- `PYTHONPATH=python python3 -m unittest tests.python.startup.test_startup_orchestrator_flow` -> passed
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- OpenCode prompt delivery now strictly follows the typed-shell contract from the spec. If a future OpenCode release again becomes sensitive to direct `cmux send` input timing, the readiness probe or retry policy may need further tuning without reintroducing the bootstrap shortcut.

## 2026-03-17 - Default plan-agent prompt contract aligned to implement_task and revalidated live

Scope:
- Aligned the remaining default plan-agent preset surfaces to the repo-supported `implement_task` contract and revalidated the live cmux launch flow for both Codex and OpenCode.

Key behavior changes:
- Changed the default plan-agent preset from `implement_plan` to `implement_task` in the runtime config layer, launch support, and `install-prompts`.
- Kept `implement_plan` available as an explicit backward-compatible alias preset, but stopped using it as the default launch target.
- Updated Codex plan-agent launches to type `/prompts:implement_task` by default and OpenCode launches to type `/implement_task` by default.
- Tightened launch tests around the real interactive contract: dynamic screen polling, prompt-picker readiness, prompt-submit readiness, `ctrl+e` cursor positioning, and caller-focus restoration with `cmux move-surface --focus true`.
- Revalidated the live flow against real `cmux`, `codex`, and `opencode` binaries. Both CLIs accepted and submitted the implementation prompt, and the caller surface was restored immediately after launch.

Files / modules touched:
- `python/envctl_engine/config/__init__.py`
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `python/envctl_engine/runtime/prompt_install_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_prompt_install_support.py`
- `docs/reference/configuration.md`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support tests.python.runtime.test_prompt_install_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_prereq_policy tests.python.runtime.test_engine_runtime_command_parity` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_plan_feature_launches_only_new_worktrees tests.python.runtime.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_plan_planning_prs_does_not_invoke_plan_agent_launch tests.python.runtime.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_plan_launch_failure_preserves_created_worktree` -> passed
- Live Codex validation via a real `launch_plan_agent_terminals(...)` harness in `workspace:1` -> passed, prompt content appeared in the launched Codex surface, caller surface restored
- Live OpenCode validation via a real `launch_plan_agent_terminals(...)` harness in `workspace:1` -> passed, prompt content appeared in the launched OpenCode surface, caller surface restored

Config / env / migrations:
- No new config keys.
- Default `ENVCTL_PLAN_AGENT_PRESET` is now `implement_task`.
- No migrations.

Risks / notes:
- Live verification depended on the locally installed Codex and OpenCode prompt presets already existing for `implement_task`.
- `implement_plan` remains installable and usable explicitly, but users relying on the old implicit default now need to set `ENVCTL_PLAN_AGENT_PRESET=implement_plan` if they want to preserve that exact behavior.

## 2026-03-17 - Extend AI readiness fallback window and lock in background-first handoff

Scope:
- Increased the bounded dynamic startup window for Codex/OpenCode launches and tightened the handoff contract so the caller surface is restored before the rest of the bootstrap sequence continues.

Key behavior changes:
- Codex and OpenCode now each get up to 5.0 seconds of dynamic `read-screen` polling before envctl falls back and proceeds.
- The launch sequence remains background-first: envctl restores focus back to the caller immediately after creating the new surface, then continues respawn, CLI startup, polling, and prompt submission against the unfocused target surface.
- Added order-sensitive coverage to ensure the early focus restoration happens before the shell respawn/bootstrap path.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- “Background” remains best-effort and depends on cmux honoring unfocused `send` / `send-key` against the launched surface, which is what current live validation showed.

## 2026-03-17 - Fix unintended implement_plan default regression

Scope:
- Corrected a default-preset regression that caused OpenCode and Codex plan-agent launches to fall back to `implement_plan` again.

Key behavior changes:
- Restored `implement_task` as the actual default in both the config defaults and the plan-agent launch helper.
- Updated launch tests and user/reference docs so the documented default matches the runtime behavior.

Files / modules touched:
- `python/envctl_engine/config/__init__.py`
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/ai-playbooks.md`
- `docs/user/planning-and-worktrees.md`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed

Config / env / migrations:
- Default `ENVCTL_PLAN_AGENT_PRESET` is `implement_task`.
- No migrations.

Risks / notes:
- Users who explicitly set `ENVCTL_PLAN_AGENT_PRESET=implement_plan` still keep that behavior; only the implicit default was corrected.

## 2026-03-17 - Move post-create surface bootstrap off the foreground path

Scope:
- Reduced the amount of visible foreground work after opening a new cmux surface by pushing the remaining rename/respawn/send/poll sequence into a background worker thread.

Key behavior changes:
- Envctl now creates the new surface, immediately restores focus back to the caller surface, and then continues the rest of the surface bootstrap asynchronously.
- The background bootstrap still performs the same shell respawn, AI CLI startup, readiness polling, prompt picker flow, and final prompt submission against the newly created surface.
- The foreground launch result now reflects successful surface creation and queued bootstrap, while later bootstrap success/failure is emitted asynchronously.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- Live Codex validation via a real `launch_plan_agent_terminals(...)` harness in `workspace:1` -> returned in ~0.47s, caller surface was immediately selected again, launched surface finished bootstrapping afterward

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- The background bootstrap uses a daemon thread inside the current envctl process. In the normal interactive `--plan` flow this keeps running while envctl stays alive, but an immediate process exit would cut that work short.

## 2026-03-17 - Revert preset docs back to implement_task

Scope:
- Restored the user-facing default preset documentation to `implement_task` after an attempted `implement_plan` default switch.

Key behavior changes:
- Plan-agent launch remains documented and tested with `implement_task` as the default preset.
- The docs/examples again show Codex using `/prompts:implement_task` unless users explicitly override `ENVCTL_PLAN_AGENT_PRESET`.
- `implement_plan` remains available as an explicit override, not the default.

Files / modules touched:
- `docs/reference/commands.md`
- `docs/user/ai-playbooks.md`
- `docs/user/planning-and-worktrees.md`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prompt_install_support` -> passed

Config / env / migrations:
- Default `ENVCTL_PLAN_AGENT_PRESET` remains `implement_task`.
- No migrations.

Risks / notes:
- Any operators who want `/implement_plan` still need to opt in explicitly via `ENVCTL_PLAN_AGENT_PRESET=implement_plan`.

## 2026-03-18 - Default plan-agent launches to a separate implementation workspace

Scope:
- Removed the old focus/tab juggling path and changed default cmux targeting so plan-agent launches run in a separate workspace instead of trying to stay in the caller workspace.

Key behavior changes:
- `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true` and the `CMUX=true` alias now derive the target workspace as `"<current workspace> implementation"` when no explicit workspace override is set.
- If that derived implementation workspace does not exist yet, envctl creates it, renames it, and opens the new plan-agent surfaces there.
- Explicit `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` and `CMUX_WORKSPACE` overrides still win and continue to accept either workspace handles or workspace titles.
- `inspect_plan_agent_launch(...)` and `--explain-startup --json` no longer treat a missing `cmux` binary as a hard crash; they keep reporting the feature as pending when caller context exists but the workspace title cannot be inspected in-process.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/ai-playbooks.md`
- `docs/user/planning-and-worktrees.md`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.startup.test_startup_orchestrator_flow tests.python.runtime.test_engine_runtime_real_startup` -> passed

Config / env / migrations:
- No new config keys.
- Default enablement now targets `"<current workspace> implementation"` unless `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` or `CMUX_WORKSPACE` is set.
- No migrations.

Risks / notes:
- Default target derivation still depends on being able to map the caller workspace ref to a workspace title from `cmux list-workspaces`; if cmux output format changes, envctl will skip or fail launch rather than guessing a title.

## 2026-03-18 - Compact plan-agent cmux tab titles

Scope:
- Shortened cmux tab titles for plan-agent launches so long worktree names do not dominate the workspace/tab bar.

Key behavior changes:
- Plan-agent launches now rename the cmux tab using a compact title derived from the worktree name.
- The format is `{first}_{third-from-last}_{second-from-last}_{last}` when the worktree name has at least four underscore-delimited segments.
- If that compact form still exceeds the local length cap, envctl drops the third-from-last segment and uses `{first}_{second-from-last}_{last}` instead.
- Short names that do not have enough underscore-delimited segments keep their original worktree name as the tab title.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `docs/user/planning-and-worktrees.md`
- `docs/changelog/features_envctl_plan_cmux_ai_terminal_launch-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed
- `PYTHONPATH=python ./.venv/bin/python -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed

Config / env / migrations:
- No new config keys.
- No migrations.

Risks / notes:
- The shortening logic currently treats underscore-delimited worktree segments as “words”; hyphen-only names keep their original title.
