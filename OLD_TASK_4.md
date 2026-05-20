# Superset Plan-Agent Completion Audit

## Context and objective
The prior task, archived as `OLD_TASK_3.md`, required completion hardening for the Superset plan-agent launch path after the initial transport implementation. The audit reviewed the current task, the Superset launch/config/prereq/inspection code, focused tests, docs/help text, recent git history, local validation, and PR status.

The implementation audit found that the Superset plan-agent launch scope is complete in the current branch. There is no remaining code implementation scope for this iteration.

## Remaining requirements (complete and exhaustive)
- No implementation changes remain.
- Preserve the completed Superset commits and PR state:
  - `9224080 Add Superset plan-agent launch transport`
  - `14a111c Harden Superset plan-agent completion`
  - PR: `https://github.com/OrgPele/envctl/pull/231`
- Preserve project-only Superset opt-in behavior:
  - `SUPERSET_PROJECT=<value>` maps to `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>`.
  - `SUPERSET_PROJECT=<value>` and `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>` select Superset transport by default unless `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT` is explicitly set.
  - Explicit `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT=cmux`, `--tmux`, `--omx`, and `--opencode` route flags continue to override Superset workspace-backed selection.
- Preserve Superset prereq behavior:
  - Project-only Superset opt-in requires `superset` and `codex`, not `cmux`.
  - Existing cmux, tmux, and OMX prereqs remain unchanged.
- Preserve Superset launch diagnostics:
  - Success summaries include launched worktrees and parsed workspace ids.
  - Auto-open-disabled summaries include `superset workspaces open <workspace-id>`.
  - No-workspace-id success summaries explain that no workspace id was returned.
  - Failed launch summaries include sanitized Superset stderr/stdout details.
  - Failed `superset workspaces open` emits `planning.agent_launch.superset_open_failed`, remains visible in user-facing output, and does not turn a successful create/run into a failed launch.
- Preserve defensive Superset command behavior:
  - Top-level `id`, nested `workspace.id`, and `agents[].workspace_id` payloads resolve workspace ids.
  - Non-JSON success output succeeds without a workspace id and emits a debug-output event.
  - `ENVCTL_PLAN_AGENT_SUPERSET_HOST=<host>` uses `--host <host>` instead of `--local`.
  - Git branch lookup failure or empty output falls back to the worktree name and emits a branch-fallback event.
  - Superset transport does not call cmux-only commands such as `new-surface`, `send`, `send-key`, `set-buffer`, `paste-buffer`, `read-screen`, or `respawn-pane`.
- Preserve documentation and help text describing Superset project/workspace shortcuts, public CLI limits, one-shot prompt behavior, unsupported review tabs, and no explicit worktree-path adoption.

## Gaps from prior iteration (mapped to evidence)
- None.
- Git divergence from `origin/main` contains the two intended Superset commits:
  - `git diff --name-status $(git merge-base HEAD origin/main)..HEAD`
  - `git log --oneline --decorate $(git merge-base HEAD origin/main)..HEAD`
- Code evidence shows project-only Superset aliases/config select the Superset transport by default:
  - `python/envctl_engine/config/__init__.py`
  - `python/envctl_engine/planning/plan_agent/config.py`
- Code evidence shows Superset launches use the public Superset CLI and emit visible success, failure, debug, branch-fallback, and open-failure diagnostics:
  - `python/envctl_engine/planning/plan_agent/superset_transport.py`
  - `python/envctl_engine/planning/plan_agent/launch.py`
- Test evidence covers the hardening scope:
  - `tests/python/config/test_config_loader.py`
  - `tests/python/planning/test_plan_agent_launch_support.py`
  - `tests/python/runtime/test_prereq_policy.py`
  - `tests/python/runtime/test_engine_runtime_command_parity.py`
- Documentation/help evidence reflects the final behavior:
  - `docs/reference/configuration.md`
  - `docs/reference/commands.md`
  - `docs/user/ai-playbooks.md`
  - `docs/user/planning-and-worktrees.md`
  - `python/envctl_engine/runtime/help_text.py`
- Local validation passed:
  - `uv run --extra dev python -m pytest tests/python/config/test_config_loader.py tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_plan_agent_module_layout.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py -q`
  - Result: `496 passed, 73 subtests passed in 23.04s`
  - `uv run --extra dev ruff check python/envctl_engine/planning/plan_agent python/envctl_engine/config/__init__.py python/envctl_engine/runtime/inspection_support.py python/envctl_engine/runtime/help_text.py tests/python/config/test_config_loader.py tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_plan_agent_module_layout.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py`
  - Result: `All checks passed!`
- GitHub PR evidence shows PR #231 is open, not draft, and checks passed:
  - `gh pr view 231 --json url,state,isDraft,headRefName,statusCheckRollup,reviewDecision`
  - Checks: `pytest`, `ruff`, and `build & shipability` succeeded.

## Acceptance criteria (requirement-by-requirement)
- `OLD_TASK_3.md` contains the archived prior hardening task.
- This `MAIN_TASK.md` clearly states that no implementation work remains for the Superset plan-agent launch scope.
- The Superset launch/config/prereq/inspection/docs behavior listed above remains preserved.
- The focused pytest suite passes.
- Ruff passes on touched code, docs-adjacent runtime help, and related tests.
- PR #231 remains updated with passing required checks.

## Required implementation scope (frontend/backend/data/integration)
- Frontend: none.
- Backend/Python engine: none.
- Data model/migrations: none.
- Integration/E2E: none.
- Runtime services: none.

## Required tests and quality gates
- For this no-op completion task, run or preserve evidence for:
  - `uv run --extra dev python -m pytest tests/python/config/test_config_loader.py tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_plan_agent_module_layout.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py -q`
  - `uv run --extra dev ruff check python/envctl_engine/planning/plan_agent python/envctl_engine/config/__init__.py python/envctl_engine/runtime/inspection_support.py python/envctl_engine/runtime/help_text.py tests/python/config/test_config_loader.py tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_plan_agent_module_layout.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py`
- If future implementation changes are made after this audit, rerun the focused suite and Ruff before committing.

## Edge cases and failure handling
- If future work changes Superset config aliasing, revalidate canonical transport precedence and route-flag override behavior.
- If future work changes Superset output parsing, preserve top-level `id`, `workspace.id`, `agents[].workspace_id`, and non-JSON success behavior.
- If future work changes launch summaries or event payloads, preserve sanitized error reporting and avoid printing environment variables or secrets.
- If future work changes transport dispatch, preserve the guarantee that Superset does not call cmux-only commands.

## Definition of done
- `OLD_TASK_3.md` exists and contains the archived hardening task.
- `MAIN_TASK.md` contains only the completion audit and explicitly states that no implementation work remains.
- Git evidence, code evidence, test evidence, and PR evidence all support the completed status.
- The final handoff reports the archive file name, implemented-vs-remaining scope, git evidence commands used, and any material residual risks.
