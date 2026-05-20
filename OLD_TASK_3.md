# Superset Plan-Agent Launch Completion Hardening

## Context and objective
The previous implementation added a Superset plan-agent transport in commit `9224080` and opened PR
https://github.com/OrgPele/envctl/pull/231. The core public-CLI path is present and the PR checks passed, but the
audit found several gaps against the original `Envctl Plan Agent Superset Lean Launch` requirements. This iteration must
finish those remaining requirements end-to-end without changing the established cmux, tmux, or OMX behavior.

The objective is to make Superset opt-in behavior, diagnostics, and edge-case coverage match the original contract:
Superset-specific project/workspace configuration should select the Superset public-CLI path when no canonical transport
override is present; successful and failed Superset launches should report actionable workspace/open/error details; and
tests must cover the defensive parsing and host/branch/failure cases already required by the original task.

## Remaining requirements (complete and exhaustive)
1. Superset project-only opt-in must select Superset transport.
   - `SUPERSET_PROJECT=<value>` must map to `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>`.
   - `SUPERSET_PROJECT=<value>` must select `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT=superset` when the canonical transport
     key is not set, matching `SUPERSET_WORKSPACE=<value>` behavior.
   - `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>` must enable plan-agent launch and resolve to Superset transport when
     no explicit `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT` is set.
   - Canonical `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT=cmux` must continue to win over Superset aliases and project keys.
   - `--tmux`, `--omx`, and `--opencode` route flags must continue to override workspace-backed transport selection.

2. Superset prereq policy must match project-only opt-in.
   - `SUPERSET_PROJECT=<value>` and `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>` must require `superset` and `codex`,
     not `cmux`, when no route flag overrides the transport.
   - Existing workspace override prereqs and tmux override prereqs must remain unchanged.

3. Superset launch summaries must report actionable launch details.
   - Successful Superset launches must print which worktree(s) launched and the parsed workspace id when available.
   - If `ENVCTL_PLAN_AGENT_SUPERSET_OPEN=false` and a workspace id is available, the summary must include the exact
     `superset workspaces open <workspace-id>` command users can run manually.
   - If Superset returns no parseable workspace id, the summary must say that the command succeeded but no workspace id
     was returned.
   - Failed Superset launch summaries must include the summarized Superset stderr/stdout that is already stored on the
     failed outcome, without dumping environment variables or secrets.

4. Superset open-command failures must be visible.
   - `_open_superset_workspace(...)` must inspect the command return code.
   - A failed open command must emit a structured event with `reason="superset_open_failed"`, `transport="superset"`,
     `worktree`, `project`, `workspace_id`, and a sanitized stdout/stderr summary.
   - A failed open command must not turn an otherwise successful agent/workspace launch into a failed launch, but the
     user-facing summary must mention that opening the workspace failed and include the Superset error summary.

5. Superset JSON parsing and command construction must have complete edge-case coverage.
   - Add tests for top-level `id` workspace parsing.
   - Add tests for `agents` result parsing with a `workspace_id`.
   - Add tests for successful non-JSON stdout: launch succeeds with no parsed workspace id and emits the debug-output
     event.
   - Add tests for `ENVCTL_PLAN_AGENT_SUPERSET_HOST=<host>` using `--host <host>` and not `--local`.
   - Add tests for git branch fallback when `git branch --show-current` fails or returns an empty branch.
   - Add tests for failed `superset workspaces open <workspace-id>` producing a visible event and user-facing summary.

6. Inspection output must reflect project-only Superset opt-in.
   - `envctl explain-startup --plan ... --json` with only `SUPERSET_PROJECT=<value>` must report
     `transport="superset"`, `superset_project=<value>`, `workflow_mode="single_prompt"`, and
     `reason="awaiting_new_worktrees"`.
   - `envctl explain-startup --plan ... --json` with canonical `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>` and no
     explicit surface transport must report the same Superset transport state.
   - Existing invalid `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT` inspection behavior must remain deterministic.

7. Documentation and help text must describe project-only opt-in accurately.
   - `docs/reference/configuration.md`, `docs/reference/commands.md`, `docs/user/ai-playbooks.md`, and
     `docs/user/planning-and-worktrees.md` must state that `SUPERSET_PROJECT` and canonical
     `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT` select the Superset transport unless canonical surface transport says otherwise.
   - `python/envctl_engine/runtime/help_text.py` must mention both project and workspace Superset shortcuts without
     implying Superset supports cmux surfaces.
   - Existing documentation about Superset's public CLI limitation, one-shot prompt behavior, unsupported review tabs,
     and lack of explicit worktree-path adoption must remain accurate.

8. Preserve existing transport behavior.
   - No cmux, tmux, or OMX command sequences, prereqs, inspection reasons, or tests should regress.
   - Superset transport must not call cmux-only commands such as `new-surface`, `send`, `send-key`, `set-buffer`,
     `paste-buffer`, `read-screen`, or `respawn-pane`.

## Gaps from prior iteration (mapped to evidence)
- Project-only alias/config gap:
  - Evidence command:
    `uv run --extra dev python - <<'PY' ... SUPERSET_PROJECT='proj-1' ...`
  - Observed result: `enabled=True`, `transport='cmux'`, prereqs `('cmux', 'codex')`.
  - Expected result: `enabled=True`, `transport='superset'`, prereqs `('superset', 'codex')` when no canonical transport
    override exists.

- Missing project-only prereq tests:
  - Evidence command:
    `rg -n "SUPERSET_PROJECT|superset_project" tests/python/runtime/test_prereq_policy.py`
  - Existing coverage checks `SUPERSET=true SUPERSET_PROJECT=...`, `SUPERSET_WORKSPACE=...`, and `--tmux` override, but
    does not cover `SUPERSET_PROJECT=...` or canonical `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=...` alone.

- Incomplete user-facing diagnostics:
  - Evidence files:
    `python/envctl_engine/planning/plan_agent/superset_transport.py`
  - Current success summaries only print counts, for example
    `Superset plan agent launch started <n> workspace/agent run(s).`
  - Current failure summaries only print counts, for example
    `Superset plan agent launch failed for <n> worktree(s).`
  - The original task required envctl to report which Superset workspace/session was launched, how to open it, and to
    surface Superset stderr/stdout summaries because auth and host errors are likely setup issues.

- Open-command failure is ignored:
  - Evidence file:
    `python/envctl_engine/planning/plan_agent/superset_transport.py`
  - `_open_superset_workspace(...)` calls `runtime.process_runner.run(...)` but does not inspect `returncode` or emit a
    failure event.

- Edge-case test gaps:
  - Evidence command:
    `rg -n "superset|SUPERSET" tests/python/planning/test_plan_agent_launch_support.py`
  - Current tests cover create/run/open success, non-zero launch exit, missing project, no cmux command usage, and review
    unsupported.
  - Missing tests cover host targeting, branch fallback, non-JSON success, top-level id parsing, agents payload parsing,
    and open-command failure visibility.

- Inspection coverage gap:
  - Evidence command:
    `rg -n "superset_transport|missing_project|invalid_surface" tests/python/runtime/test_engine_runtime_command_parity.py`
  - Current coverage checks `SUPERSET=true SUPERSET_PROJECT=...`, missing project, and invalid transport, but not
    project-only alias/canonical project config.

## Acceptance criteria (requirement-by-requirement)
1. Project-only opt-in:
   - `resolve_plan_agent_launch_config(load_config({"SUPERSET_PROJECT": "proj-1"}), {}, route=plan_route)` returns
     `transport == "superset"`, `enabled is True`, and `superset_project == "proj-1"`.
   - `resolve_plan_agent_launch_config(load_config({"ENVCTL_PLAN_AGENT_SUPERSET_PROJECT": "proj-1"}), {}, route=plan_route)`
     returns the same Superset transport state.
   - If `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT=cmux` is set, Superset project aliases do not override it.

2. Prereqs:
   - `check_prereqs` reports missing `superset` and `codex`, not `cmux`, for project-only Superset opt-in.
   - `--tmux` with Superset project config still reports tmux prereqs when tmux is missing.

3. Summaries:
   - Successful Superset create/run output includes worktree name and workspace id when parsed.
   - With `ENVCTL_PLAN_AGENT_SUPERSET_OPEN=false`, output includes `superset workspaces open <workspace-id>`.
   - Non-JSON success output states that no workspace id was returned.
   - Failed launch output includes Superset stderr/stdout summary.

4. Open failures:
   - A failed `superset workspaces open` emits `planning.agent_launch.superset_open_failed`.
   - The launch result remains `status="launched"` when create/run succeeded and only open failed.
   - The printed summary includes the open failure summary.

5. Edge tests:
   - Tests cover top-level `id`, `agents[].workspace_id`, non-JSON stdout, host targeting, branch fallback, and open
     failure.

6. Inspection:
   - `explain-startup --json` reports Superset transport for project-only alias and canonical project config.
   - Existing invalid transport inspection test remains green.

7. Docs/help:
   - Docs describe project-only selection accurately and preserve all Superset limitations.

8. Regression safety:
   - Existing cmux/tmux/OMX focused tests pass unchanged.

## Required implementation scope (frontend/backend/data/integration)
- Backend/runtime:
  - `python/envctl_engine/config/__init__.py`
  - `python/envctl_engine/planning/plan_agent/config.py`
  - `python/envctl_engine/planning/plan_agent/launch.py`
  - `python/envctl_engine/planning/plan_agent/superset_transport.py`
  - Any shared model changes only if needed for clean structured reporting.
- Tests:
  - `tests/python/config/test_config_loader.py`
  - `tests/python/planning/test_plan_agent_launch_support.py`
  - `tests/python/runtime/test_prereq_policy.py`
  - `tests/python/runtime/test_engine_runtime_command_parity.py`
- Docs/help:
  - `docs/reference/configuration.md`
  - `docs/reference/commands.md`
  - `docs/user/ai-playbooks.md`
  - `docs/user/planning-and-worktrees.md`
  - `python/envctl_engine/runtime/help_text.py`
- Frontend:
  - None expected.
- Data/migrations:
  - None expected.
- Integration:
  - Mock Superset CLI in automated tests. Do not require a live authenticated Superset account in CI.

## Required tests and quality gates
- Write or update failing tests before implementation for the project-only opt-in, prereq, inspection, summary, JSON
  parsing, host, branch fallback, and open-failure cases.
- Run the focused Python suite:
  - `uv run --extra dev python -m pytest tests/python/config/test_config_loader.py tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_plan_agent_module_layout.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py -q`
- Run Ruff on touched paths:
  - `uv run --extra dev ruff check python/envctl_engine/planning/plan_agent python/envctl_engine/config/__init__.py python/envctl_engine/runtime/inspection_support.py python/envctl_engine/runtime/help_text.py tests/python/config/test_config_loader.py tests/python/planning/test_plan_agent_launch_support.py tests/python/planning/test_plan_agent_module_layout.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py`
- If implementation touches broader startup/finalization behavior, also run the relevant expanded runtime test file(s).
- PR checks must pass after pushing.

## Edge cases and failure handling
- Empty or failing `git branch --show-current` falls back to `worktree.name`, emits a branch-fallback event, and still
  launches Superset.
- Superset create/run exits non-zero: return a failed outcome and print the stderr/stdout summary.
- Superset create/run exits zero with non-JSON stdout: return launched with `surface_id=None`, emit debug-output event,
  and print that no workspace id was returned.
- Superset create/run exits zero with top-level `id`: use that id as the workspace id.
- Superset create/run exits zero with `agents[].workspace_id`: use that id as the workspace id.
- Superset open exits non-zero: emit open-failed event, print the error, and keep the launch successful.
- `SUPERSET_API_KEY` and environment dumps must never be logged or printed.
- Cmux/tmux/OMX route flags and existing workspace behavior must remain unchanged.

## Definition of done
- Project-only Superset config and aliases route to Superset transport by default and use Superset prereqs.
- Superset launch summaries identify launched worktrees/workspace ids, manual open commands, missing workspace ids, and
  Superset error summaries clearly.
- Superset open-command failure is observable but does not invalidate a successful create/run launch.
- Defensive Superset JSON parsing and host/branch fallback behavior are covered by tests.
- Docs and help text accurately describe the final Superset opt-in behavior and limitations.
- Focused pytest and Ruff validation pass locally.
- Work is committed, pushed, PR updated, review comments inspected, and GitHub required checks pass.
