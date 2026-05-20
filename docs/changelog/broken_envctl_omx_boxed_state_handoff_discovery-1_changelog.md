## 2026-05-08 - Discover OMX-managed plan-agent sessions from deterministic state roots

Scope:
- Fixed `envctl --plan ... --omx --ralph --headless --new-session` handoff discovery when OMX starts the managed tmux/Codex session but writes runtime state outside the source worktree.
- Kept the OMX-managed launch contract intact: envctl still asks `omx --tmux` to create the session, then discovers and bootstraps the managed target.

Key behavior changes:
- Plan-agent OMX spawns now select an envctl-owned `OMX_ROOT` under `<worktree>/.envctl-state/omx/<worktree-name>/`, overriding inherited stale `OMX_ROOT` values so discovery is launch-scoped and deterministic.
- Session discovery now reads the deterministic OMX root first, falls back to legacy `<worktree>/.omx/state/session.json`, rejects state whose `cwd` points at a different worktree, and preserves stale-session avoidance for `--new-session`.
- Attach-target discovery still prefers `native_session_id`, then the derived OMX tmux session name, and now has a conservative tmux pane-path fallback for matching OMX-prefixed sessions under the target worktree.
- `omx_session_unavailable` events now include bounded diagnostics for selected roots, session-file presence, session-id presence, tmux candidates, and matching worktree panes.
- Stale OMX tmux lock cleanup now also checks the selected deterministic OMX root.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_engine_runtime_real_startup.py`
- `docs/reference/commands.md`
- `docs/reference/important-flags.md`
- `docs/changelog/broken_envctl_omx_boxed_state_handoff_discovery-1_changelog.md`

Tests run + results:
- `pytest tests/python/planning/test_plan_agent_launch_support.py -q` -> passed (`143 passed, 10 subtests passed`).
- `pytest tests/python/runtime/test_engine_runtime_real_startup.py tests/python/startup/test_startup_orchestrator_flow.py -q` -> passed (`173 passed, 6 subtests passed`).
- `pytest tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_prompt_install_support.py -q` -> passed (`121 passed, 60 subtests passed`).
- `rg -n "OMX_ROOT|OMX_STATE_ROOT|omx_session_unavailable|_wait_for_omx_attach_target|_spawn_omx_session_for_worktree" python/envctl_engine tests/python docs` -> inspected expected code, test, and docs references.
- `python -m py_compile python/envctl_engine/planning/plan_agent_launch_support.py tests/python/planning/test_plan_agent_launch_support.py tests/python/runtime/test_engine_runtime_real_startup.py` -> passed.
- `python -m ruff check ...` -> not run; ambient Python did not have `ruff` installed and no repo `.venv` was present.

Config / env / migrations:
- No new user-facing config keys.
- OMX plan-agent launches now set `OMX_ROOT` internally for the child `omx --tmux` process.
- No migrations.

Risks / notes:
- CI still uses deterministic subprocess/tmux mocks rather than live Codex/OMX E2E, matching the task's non-goal.
- Pane-path fallback is intentionally conservative: the session name must use an OMX worktree/name prefix and the pane path must resolve to the target worktree or a child path.
