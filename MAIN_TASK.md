# Superset Plan-Agent Final Completion Audit

## Context and objective
The prior task, archived as `OLD_TASK_4.md`, was itself a completion audit for the Superset plan-agent launch work. This follow-up audit reviewed the current task, local working-tree state, committed divergence from the originating base `origin/main`, the implemented Superset config/launch/prereq/inspection code paths, focused tests, documentation evidence, and PR status.

The audit found that the Superset plan-agent launch scope is fully complete in the current branch. There is no remaining implementation work to carry forward.

## Remaining requirements (complete and exhaustive)
- No implementation changes remain.
- Preserve the completed Superset commits and PR state:
  - `9224080 Add Superset plan-agent launch transport`
  - `14a111c Harden Superset plan-agent completion`
  - `4037eb5 Archive completed Superset plan-agent task`
  - PR: `https://github.com/OrgPele/envctl/pull/231`
- Preserve the completed Superset behavior:
  - `SUPERSET_PROJECT=<value>` maps to `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>`.
  - `SUPERSET_PROJECT=<value>` and `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>` select Superset transport by default unless `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT` is explicitly set.
  - Explicit `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT=cmux`, `--tmux`, `--omx`, and `--opencode` route flags override Superset workspace-backed transport selection.
  - Project-only Superset opt-in requires `superset` and `codex`, not `cmux`.
  - Superset launches use public `superset workspaces create`, `superset agents run`, and optional `superset workspaces open` commands.
  - Superset summaries report launched worktrees, parsed workspace ids, manual open commands when auto-open is disabled, missing workspace ids, launch failures, and open failures.
  - Failed `superset workspaces open` emits `planning.agent_launch.superset_open_failed` and does not turn a successful create/run launch into a failed launch.
  - Superset JSON parsing handles nested `workspace.id`, top-level `id`, `workspace_id`, and `agents[].workspace_id` payloads.
  - Successful non-JSON Superset output remains a launched outcome without a workspace id and emits a debug-output event.
  - `ENVCTL_PLAN_AGENT_SUPERSET_HOST=<host>` uses `--host <host>` instead of `--local`.
  - Git branch lookup failure or empty output falls back to the worktree name and emits a branch-fallback event.
  - Superset transport remains isolated from cmux-only commands such as `new-surface`, `send`, `send-key`, `set-buffer`, `paste-buffer`, `read-screen`, and `respawn-pane`.
  - Superset documentation/help text continues to describe project/workspace shortcuts, public CLI limits, one-shot prompt behavior, unsupported review tabs, and no explicit worktree-path adoption.

## Gaps from prior iteration (mapped to evidence)
- None.
- Working-tree evidence:
  - `git status --short` reported only `.envctl-state/worktree-provenance.json` as an unstaged envctl-local artifact before this archive update.
  - `git diff --name-status` reported only `.envctl-state/worktree-provenance.json` before this archive update.
  - `git diff --cached --name-status` reported no staged changes before this archive update.
- Originating-base evidence:
  - `.envctl-state/worktree-provenance.json` identifies `source_ref` as `origin/main` and `source_branch` as `main`.
  - `git merge-base HEAD origin/main` resolved to `ea7bfd4e4e26646b7c3b3283b32a8061448b25ba`.
  - `git log --oneline --decorate ea7bfd4e4e26646b7c3b3283b32a8061448b25ba..HEAD` showed only the three intended branch commits listed above.
  - `git diff --name-status ea7bfd4e4e26646b7c3b3283b32a8061448b25ba..HEAD` showed the Superset implementation/docs/tests plus task archive files.
- Code evidence:
  - `python/envctl_engine/config/__init__.py` contains Superset alias/default transport inference for `SUPERSET_PROJECT`, `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT`, workspace aliases, and canonical transport precedence.
  - `python/envctl_engine/planning/plan_agent/config.py` resolves Superset launch config and prereq command selection.
  - `python/envctl_engine/planning/plan_agent/launch.py` dispatches Superset transport without cmux workspace resolution.
  - `python/envctl_engine/planning/plan_agent/superset_transport.py` implements public Superset CLI launch/run/open behavior, diagnostics, workspace-id parsing, branch fallback, host targeting, and open-failure handling.
- Test evidence:
  - `tests/python/config/test_config_loader.py` covers Superset alias/canonical config behavior.
  - `tests/python/planning/test_plan_agent_launch_support.py` covers Superset create/run/open behavior, public CLI isolation, workspace id parsing, non-JSON success, host targeting, branch fallback, launch failure, open failure, and unsupported review tabs.
  - `tests/python/runtime/test_prereq_policy.py` covers project-only Superset prereqs and route override behavior.
  - `tests/python/runtime/test_engine_runtime_command_parity.py` covers `explain-startup --json` Superset inspection behavior.
- Documentation evidence:
  - `docs/reference/configuration.md`, `docs/reference/commands.md`, `docs/user/ai-playbooks.md`, `docs/user/planning-and-worktrees.md`, and `python/envctl_engine/runtime/help_text.py` document Superset project/workspace shortcuts and limitations.
- PR evidence:
  - `gh pr view 231 --json url,state,isDraft,headRefName,statusCheckRollup,reviewDecision` showed PR #231 open, not draft, and checks `pytest`, `ruff`, and `build & shipability` passing on the latest pushed commit.

## Acceptance criteria (requirement-by-requirement)
- `OLD_TASK_4.md` contains the archived prior completion-audit task.
- This `MAIN_TASK.md` clearly states that no implementation work remains for the Superset plan-agent launch scope.
- The completed Superset behavior listed in this task remains preserved.
- PR #231 remains open, updated, and green.
- No new runtime code, tests, docs, config, or migrations are required unless future evidence identifies a new gap.

## Required implementation scope (frontend/backend/data/integration)
- Frontend: none.
- Backend/Python engine: none.
- Data model/migrations: none.
- Integration/E2E: none.
- Runtime services: none.

## Required tests and quality gates
- For this no-op completion task, preserve evidence from the latest validation and PR checks:
  - Focused pytest previously passed: `496 passed, 73 subtests passed`.
  - Ruff previously passed: `All checks passed!`.
  - GitHub checks on PR #231 passed: `pytest`, `ruff`, and `build & shipability`.
- If any future implementation changes are made after this audit, rerun:
  - `uv run --extra dev python -m pytest tests/python/config/test_config_loader.py tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_plan_agent_module_layout.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py -q`
  - `uv run --extra dev ruff check python/envctl_engine/planning/plan_agent python/envctl_engine/config/__init__.py python/envctl_engine/runtime/inspection_support.py python/envctl_engine/runtime/help_text.py tests/python/config/test_config_loader.py tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_plan_agent_module_layout.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py`

## Edge cases and failure handling
- If future work changes Superset config aliasing, revalidate canonical transport precedence and route-flag override behavior.
- If future work changes Superset output parsing, preserve nested `workspace.id`, top-level `id`, `workspace_id`, `agents[].workspace_id`, and non-JSON success behavior.
- If future work changes launch summaries or event payloads, preserve sanitized error reporting and avoid printing environment variables or secrets.
- If future work changes transport dispatch, preserve the guarantee that Superset does not call cmux-only commands.

## Definition of done
- `OLD_TASK_4.md` exists and contains the archived prior task.
- `MAIN_TASK.md` contains only this final completion audit and explicitly states that no implementation work remains.
- Git evidence, code evidence, test evidence, documentation evidence, and PR evidence all support the completed status.
- The final handoff reports the archive file name, implemented-vs-remaining scope, git evidence commands used, and residual risks.
