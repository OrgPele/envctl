## 2026-03-18 - Honor `CYCLES` as a plan-agent Codex cycle alias

Scope:
- Fixed the `CYCLES=<n> envctl --plan` repro so the shorthand alias resolves to the same effective Codex cycle count as `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`.
- Kept `ENVCTL_PLAN_AGENT_CODEX_CYCLES` as the canonical config key and preserved the existing enablement rules for plan-agent terminal launch.

Key behavior changes:
- `load_config(...)` now normalizes `CYCLES` into `ENVCTL_PLAN_AGENT_CODEX_CYCLES` when the canonical key is not explicitly set.
- Canonical-over-alias precedence now applies to cycle count resolution just like the existing plan-agent aliases.
- `resolve_plan_agent_launch_config(...)` also normalizes shorthand aliases on its env overlay so direct runtime inspection and launch resolution stay aligned with config-load behavior.
- `envctl show-config --json`, `envctl explain-startup --plan --json`, and the plan-agent launch summary now agree on the shorthand-derived cycle count.
- Invalid shorthand values still surface as `invalid_codex_cycles`, and very large shorthand values still cap at the existing cycle safety bound.
- `CYCLES` alone still does not enable plan-agent launch or pull in cmux / AI CLI prereqs.

Files / modules touched:
- `python/envctl_engine/config/__init__.py`
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`
- `tests/python/runtime/test_prereq_policy.py`
- `docs/reference/configuration.md`
- `docs/reference/commands.md`
- `docs/user/planning-and-worktrees.md`
- `docs/user/ai-playbooks.md`
- `docs/changelog/broken_envctl_plan_agent_cycles_alias_falls_back_to_default-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed (`Ran 44 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed (`Ran 60 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prereq_policy` -> passed (`Ran 8 tests`, `OK`)

Config / env / migrations:
- No new persisted config keys or migrations.
- Added documented shorthand support for `CYCLES=<n>` as an alias to `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`.
- Canonical `ENVCTL_PLAN_AGENT_*` values remain the durable contract and win on conflicts with shorthand env vars.

Risks / notes:
- `CYCLES` is intentionally narrow but still a generic env var name, so users with broader shell usage should prefer `ENVCTL_PLAN_AGENT_CODEX_CYCLES` when they need an unambiguous long-lived config contract.
- The automated coverage now locks alias resolution, canonical precedence, invalid/bounded shorthand handling, inspection parity, and the “no enablement from `CYCLES` alone” behavior.

## 2026-03-19 - Close live verification for the `CYCLES` alias command surface

Scope:
- Completed the remaining live command-surface verification that was still missing after the code/test/doc implementation landed.
- Verified the shorthand alias through the real `./bin/envctl` entrypoint for `show-config`, `explain-startup`, canonical precedence, invalid shorthand handling, and the actual `--plan` launch summary.

Key behavior changes:
- No additional runtime code changes were required after live verification; the implemented alias behavior matched the intended contract on the real command surface.
- Added repo evidence that `CYCLES=3` resolves to `plan_agent.codex_cycles=3` in `show-config --json`.
- Added repo evidence that `CYCLES=3` resolves to `plan_agent_launch.codex_cycles=3` and `workflow_mode=codex_cycles` in `explain-startup --plan --json`.
- Added repo evidence that the real `--plan` path prints `Plan agent launch queued Codex cycle workflow (cycles=3)` rather than silently falling back to `1`.
- Added repo evidence that canonical precedence still wins (`CYCLES=2 ENVCTL_PLAN_AGENT_CODEX_CYCLES=4` resolves to `4`) and that invalid shorthand values remain non-crashing with `workflow_warning=invalid_codex_cycles`.

Files / modules touched:
- `docs/changelog/broken_envctl_plan_agent_cycles_alias_falls_back_to_default-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed (`Ran 44 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed (`Ran 60 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prereq_policy` -> passed (`Ran 8 tests`, `OK`)

Live verification commands + results:
- `show-config --json` via the real wrapper:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH ENVCTL_USE_REPO_WRAPPER=1 RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-alias-live-show-config-venv CYCLES=3 ./bin/envctl --show-config --json`
  - Result: `plan_agent.codex_cycles` was `3`.
- `explain-startup --plan --json` via the real wrapper:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH ENVCTL_USE_REPO_WRAPPER=1 RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-alias-live-explain-venv CYCLES=3 ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true ./bin/envctl --explain-startup --plan refactoring/envctl-bash-deletion-ledger-and-prune-plan --json`
  - Result: `plan_agent_launch.codex_cycles` was `3` and `workflow_mode` was `codex_cycles`.
- Canonical precedence:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH ENVCTL_USE_REPO_WRAPPER=1 RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-alias-live-precedence-venv CYCLES=2 ENVCTL_PLAN_AGENT_CODEX_CYCLES=4 ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true ./bin/envctl --explain-startup --plan refactoring/envctl-bash-deletion-ledger-and-prune-plan --json`
  - Result: `plan_agent_launch.codex_cycles` was `4`.
- Invalid shorthand:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH ENVCTL_USE_REPO_WRAPPER=1 RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-alias-live-invalid-venv CYCLES=bad ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true ./bin/envctl --explain-startup --plan refactoring/envctl-bash-deletion-ledger-and-prune-plan --json`
  - Result: command exited successfully, `codex_cycles` resolved to `0`, `workflow_mode` resolved to `single_prompt`, and `workflow_warning` was `invalid_codex_cycles`.
- Actual `--plan` launch summary:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH ENVCTL_USE_REPO_WRAPPER=1 RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-alias-live-plan TREES_STARTUP_ENABLE=false ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl-cycles-alias-live-20260319 CYCLES=3 ./bin/envctl --headless --plan refactoring/envctl-bash-deletion-ledger-and-prune-plan`
  - Result: stdout included `Plan agent launch queued Codex cycle workflow (cycles=3) for 1 surface(s).` and `Plan agent launch opened 1 cmux surface(s).`
- Operational evidence captured after the live `--plan` run:
  - `find trees -maxdepth 3 -type d` showed the created worktree root `trees/refactoring_envctl_bash_deletion_ledger_and_prune_plan/1`.
  - `cmux list-workspaces` showed the created target workspace `workspace:5  envctl-cycles-alias-live-20260319`.
  - `cmux list-pane-surfaces --workspace workspace:5` showed exactly one surface: `surface:21`.
  - Runtime event logs under `/tmp/envctl-cycles-alias-live-plan/.../events.jsonl` recorded `planning.agent_launch.workflow_selected` with `codex_cycles=3` and `planning.agent_launch.surface_created` for `workspace:5`.

Config / env / migrations:
- No new config keys or migrations.
- Repo-local bootstrap was required to complete live `--plan` verification:
  - `python3.12 -m venv .venv`
  - `.venv/bin/python -m pip install -e '.[dev]'`
- The live wrapper verification also required prepending `.venv/bin` to `PATH` because `./bin/envctl` only re-execs into the repo venv when the current interpreter is unsupported; on this machine the system `python3` version was already supported but did not have `rich` installed.

Risks / notes:
- The alias-specific contract is now verified on the real command surface, but the non-interactive `--plan` verification only proved the summary line, workspace creation, single-surface reuse, and runtime events. A later `cmux read-screen` of `surface:21` still showed the shell prompt in the repo root, so this verification does not by itself prove full background bootstrap completion after the headless process exits.
- The live verification created repo-local artifacts that are expected for this task: `.venv/`, `trees/refactoring_envctl_bash_deletion_ledger_and_prune_plan/1`, and runtime artifacts under `/tmp/envctl-cycles-alias-live-*`.

## 2026-03-19 - Fix real Codex multi-cycle queueing and background event persistence

Scope:
- Fixed the follow-up live bug where `envctl --plan` correctly reported `cycles=N` but the Codex plan-agent workflow still behaved like a single cycle in practice.
- Closed the observability gap that hid the real queue outcome from persisted runtime artifacts after the initial artifact write.
- Verified the corrected behavior end to end through the real `bin/envctl` entrypoint and live cmux surfaces from this worktree.

Key behavior changes:
- Plan-agent bootstrap threads now run as non-daemon threads so headless `--plan` runs do not drop the background Codex bootstrap on process exit.
- Background plan-agent bootstrap now persists refreshed runtime `events.jsonl` snapshots after late queue/bootstrap events, including the active run directory under `.../runs/<run_id>/events.jsonl`.
- Codex queued follow-ups no longer wait for a generic “ready prompt” before typing.
- Freeform queued follow-up messages now type first, wait for the live `tab to queue message` draft state, and only then send `tab`.
- Queued saved-prompt follow-ups such as `/prompts:continue_task` now resolve the picker with `enter`, wait for the `tab to queue message` state, and then queue the prompt.
- Persisted runtime evidence now distinguishes real queue success (`planning.agent_launch.workflow_queued`) from fallback (`planning.agent_launch.workflow_queue_failed` / `workflow_fallback`) instead of silently freezing at `surface_created`.

Files / modules touched:
- `python/envctl_engine/planning/plan_agent_launch_support.py`
- `python/envctl_engine/runtime/engine_runtime_event_support.py`
- `tests/python/planning/test_plan_agent_launch_support.py`
- `tests/python/runtime/test_engine_runtime_artifacts.py`
- `docs/changelog/broken_envctl_plan_agent_cycles_alias_falls_back_to_default-1_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support` -> passed (`Ran 47 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity` -> passed (`Ran 60 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_prereq_policy` -> passed (`Ran 8 tests`, `OK`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_artifacts` -> passed (`Ran 8 tests`, `OK`)

Live verification commands + results:
- First reproduction with persisted-event visibility fix in place:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH ENVCTL_USE_REPO_WRAPPER=1 RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-live-20260319 TREES_STARTUP_ENABLE=false ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl-cycles-live-20260319 CYCLES=5 /Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/bin/envctl --headless --plan features/envctl-codex-plan-agent-iteration-commit-pr-workflow`
  - Result: stdout still reported `cycles=5`, but persisted run events now captured the real failure: `planning.agent_launch.workflow_queue_failed` and `planning.agent_launch.workflow_fallback` with `reason=queue_not_ready`.
- Second reproduction after switching to “type first, then wait for queue state”:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH ENVCTL_USE_REPO_WRAPPER=1 RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-live-20260319b TREES_STARTUP_ENABLE=false ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl-cycles-live-20260319b CYCLES=5 /Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/bin/envctl --headless --plan features/envctl-pr-dirty-worktree-commit-confirmation`
  - Result: the first freeform follow-up queued, but persisted events still ended in `workflow_queue_failed` because queued `/prompts:continue_task` required picker resolution before `tab`.
- Final successful verification after queued saved-prompt handling was added:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH ENVCTL_USE_REPO_WRAPPER=1 RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-live-20260319c TREES_STARTUP_ENABLE=false ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl-cycles-live-20260319c CYCLES=5 /Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/bin/envctl --headless --plan broken/envctl-plan-agent-duplicate-starter-surface-on-workspace-create`
  - Result: persisted run events recorded `planning.agent_launch.workflow_queued` with `queued_steps=13` followed by `planning.agent_launch.command_sent`; no `workflow_queue_failed` or `workflow_fallback` event was emitted.
- Live cmux inspection for the final successful run:
  - `cmux list-workspaces` showed `workspace:8  envctl-cycles-live-20260319c`
  - `cmux list-pane-surfaces --workspace workspace:8` showed `surface:29`
  - `cmux read-screen --workspace workspace:8 --surface surface:29 --lines 160 | tail -n 60` showed the active Codex session with a populated `Queued follow-up messages` list, including the repeated finalization instruction and queued iteration prompts.

Config / env / migrations:
- No migrations or new public config keys.
- The live verification continued to rely on the repo-local virtualenv wrapper path:
  - `PATH=/Users/kfiramar/projects/current/envctl/trees/broken_envctl_plan_agent_cycles_alias_falls_back_to_default/1/.venv/bin:$PATH`
- Reproducible live verification also required explicit isolation inputs:
  - `RUN_SH_RUNTIME_DIR=/tmp/envctl-cycles-live-*`
  - `TREES_STARTUP_ENABLE=false`
  - `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true`
  - `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl-cycles-live-*`
  - `CYCLES=5`

Risks / notes:
- The queue transport is now based on observed Codex terminal states from the real UI: freeform drafts require `tab to queue message`, while saved prompts require picker resolution with `enter` before the same queue hint appears.
- The successful live verification used `CYCLES=5`, which produced `queued_steps=13`; larger cycle counts remain bounded by the existing cap.
- The live verification created additional nested worktrees in this worktree under `trees/` and additional runtime artifacts under `/tmp/envctl-cycles-live-*`; these are expected side effects of this task.
