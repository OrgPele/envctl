# Envctl Codex Plan-Agent Iteration / Commit / PR Workflow

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Extend the current post-`--plan` `cmux` launch flow beyond a single `/implement_task` submission so newly created Codex worktrees can continue through follow-up iterations without reopening tabs or manually retargeting the session.
  - Keep the new automation Codex-only, because the requested queueing model depends on Codex accepting appended follow-up input through `Tab` after the current message finishes.
  - Reuse the existing envctl-owned task prompts (`implement_task`, `continue_task`) while keeping the launcher contract purely message-based: envctl appends Codex messages, and Codex performs any commit/push/PR work itself.
  - Make the workflow count-driven via a configurable cycle parameter, so operators can choose exactly how many implement/finalize message rounds envctl should queue for each launched Codex session.
  - Preserve the current one-preset launch behavior for OpenCode and for Codex users who do not opt into the iterative workflow.
- Non-goals:
  - Changing planning/worktree reconciliation, `MAIN_TASK.md` seeding, or `--planning-prs` semantics.
  - Replacing the existing dashboard commit/PR flows in `python/envctl_engine/ui/dashboard/orchestrator.py`.
  - Building a generic multi-command queue system for every AI CLI or for arbitrary user-specified scripts in the first change.
  - Parsing Codex transcript text or chat history as a new source of truth for task completion.
- Assumptions:
  - The requested “iterations and commit push and PR” flow is intended to run inside the launched Codex session, not as a separate origin-side dashboard flow.
  - The requested cycle semantics are deterministic:
    - cycle `1` = `/prompts:implement_task` -> queued Codex follow-up message instructing commit/push/PR
    - cycles `2..N` = `/prompts:continue_task` -> `/prompts:implement_task` -> queued Codex follow-up message instructing commit/push/PR
  - Because the cycle count is explicit, envctl should not infer “work remaining” by parsing `MAIN_TASK.md` or Codex transcript text in the first implementation.

## Goal (user experience)
When the operator runs `envctl --plan` with the current `cmux` launch feature enabled, the selected AI CLI is Codex, and a Codex cycle count is configured, each newly created worktree should open a Codex surface as it does today and then receive a deterministic series of queued Codex messages in that same session. If the configured cycle count is `1`, envctl should queue `/prompts:implement_task` and then a plain Codex message instructing it to commit, push, and open a PR when that implementation pass completes. If the cycle count is greater than `1`, envctl should queue that first round and then append additional rounds of `/prompts:continue_task`, `/prompts:implement_task`, and another plain Codex finalization message until the configured count is exhausted. OpenCode and the default single-preset Codex path should keep their current behavior unless the new Codex cycle mode is explicitly enabled.

## Business logic and data model mapping
- Planning/worktree selection and created-worktree metadata:
  - `python/envctl_engine/planning/worktree_domain.py:_select_plan_projects`
  - `python/envctl_engine/planning/worktree_domain.py:_sync_plan_worktrees_from_plan_counts`
  - `python/envctl_engine/planning/worktree_domain.py:_create_feature_worktrees_result`
  - `python/envctl_engine/planning/worktree_domain.py:_seed_main_task_from_plan`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:CreatedPlanWorktree`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:PlanSelectionResult`
- Startup hook that invokes plan-agent launch after planning sync:
  - `python/envctl_engine/startup/startup_orchestrator.py:_select_contexts`
  - `tests/python/runtime/test_engine_runtime_real_startup.py:test_plan_feature_launches_only_new_worktrees`
  - `tests/python/runtime/test_engine_runtime_real_startup.py:test_plan_planning_prs_does_not_invoke_plan_agent_launch`
- Current plan-agent launch transport and prompt submission:
  - `python/envctl_engine/planning/plan_agent_launch_support.py:resolve_plan_agent_launch_config`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:launch_plan_agent_terminals`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_run_surface_bootstrap`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_launch_cli_bootstrap_commands`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_send_prompt_text`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_send_surface_key`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_wait_for_cli_ready`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_wait_for_prompt_picker_ready`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_wait_for_prompt_submit_ready`
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_slash_command`
- Config / inspection / prereq ownership for plan-agent behavior:
  - `python/envctl_engine/config/__init__.py:EngineConfig`
  - `python/envctl_engine/config/__init__.py:load_config`
  - `python/envctl_engine/runtime/inspection_support.py:_print_config`
  - `python/envctl_engine/runtime/inspection_support.py:_print_startup_explanation`
  - `python/envctl_engine/runtime/cli.py:check_prereqs`
  - `tests/python/runtime/test_prereq_policy.py`
  - `tests/python/runtime/test_engine_runtime_command_parity.py:test_explain_startup_json_reports_plan_agent_launch_state`
- Prompt contracts the launcher currently depends on:
  - `python/envctl_engine/runtime/prompt_templates/implement_task.md`
  - `python/envctl_engine/runtime/prompt_templates/continue_task.md`
  - `python/envctl_engine/runtime/prompt_install_support.py:_available_presets`
  - `docs/user/ai-playbooks.md`
  - `docs/user/planning-and-worktrees.md`
- Existing commit / push / PR behavior to preserve as separate, already-shipped envctl surfaces:
  - `python/envctl_engine/actions/project_action_domain.py:run_commit_action`
  - `python/envctl_engine/actions/project_action_domain.py:_resolve_commit_message`
  - `python/envctl_engine/actions/project_action_domain.py:_advance_commit_ledger_pointer`
  - `python/envctl_engine/actions/project_action_domain.py:run_pr_action`
  - `python/envctl_engine/actions/project_action_domain.py:existing_pr_url`
  - `python/envctl_engine/actions/project_action_domain.py:_pr_title`
  - `python/envctl_engine/actions/project_action_domain.py:_pr_body`
  - `tests/python/actions/test_actions_cli.py`

## Current behavior (verified in code)
- `--plan` currently launches plan-agent terminals only for worktrees created during the current reconciliation:
  - `StartupOrchestrator._select_contexts(...)` calls `rt._select_plan_projects(...)`, pulls `selection_result.created_worktrees`, and passes only the selected created worktrees to `launch_plan_agent_terminals(...)`.
  - `tests/python/runtime/test_engine_runtime_real_startup.py:test_plan_feature_launches_only_new_worktrees` locks in the “first run launches new worktrees, rerun launches none” behavior.
- The current launcher owns exactly one preset slot per launched surface:
  - `PlanAgentLaunchConfig` contains a single `preset` field.
  - `_run_surface_bootstrap(...)` computes one `prompt_text = _slash_command(launch_config.cli, launch_config.preset)` and submits exactly that command after bootstrapping the shell and AI CLI.
  - `todo/plans/features/envctl-prompt-overwrite-confirmation-and-origin-review-preset.md` already calls out that the current plan-agent launch model only supports one preset submission.
- Codex and OpenCode currently share the same high-level launch contract, with only prompt formatting/readiness heuristics differing:
  - `_slash_command(...)` formats Codex presets as `/prompts:<preset>` and OpenCode presets as `/<preset>`.
  - `_screen_looks_ready(...)`, `_prompt_picker_screen_looks_ready(...)`, and `_prompt_submit_screen_looks_ready(...)` contain CLI-specific read-screen heuristics, but there is no second-stage workflow after the initial preset submit.
  - `tests/python/planning/test_plan_agent_launch_support.py:test_launch_sequence_uses_cmux_commands_for_codex` and `...:test_launch_sequence_supports_opencode_and_default_implementation_workspace` verify one-shot launch for each CLI.
- The current iterative task prompt exists, but the launcher never uses it automatically:
  - `python/envctl_engine/runtime/prompt_templates/continue_task.md` is installable and documented.
  - `docs/user/ai-playbooks.md` and `docs/reference/commands.md` list `continue_task` as a built-in preset.
  - No code in `plan_agent_launch_support.py` or `startup_orchestrator.py` queues or submits `/continue_task`.
- Finalization logic already exists outside the launcher:
  - `run_commit_action(...)` stages, commits, advances `.envctl-commit-message.md`, and pushes with `git push -u`.
  - `run_pr_action(...)` skips when an open PR already exists and otherwise creates a PR using either `utils/create-pr.sh` or `gh pr create`.
  - The launcher does not invoke either action today, and the requested new behavior is to keep that boundary: append messages only, without launcher-owned command execution.
- `--planning-prs` is intentionally separate from plan-agent launch:
  - `StartupOrchestrator._resolve_run_reuse(...)` branches early for `route.command == "plan"` with `planning_prs=true`, runs `_run_pr_action(...)`, prints `Planning PR mode complete; skipping service startup.`, and never calls `launch_plan_agent_terminals(...)`.
  - Real-startup tests lock that separation in.

## Root cause(s) / gaps
1. The plan-agent launch model is one-shot.
   - `PlanAgentLaunchConfig` has one preset field, and `_run_surface_bootstrap(...)` ends after one prompt submission.
   - There is no structured representation for “submit prompt A, then queue follow-up message B, then maybe queue more work.”
2. There is no Codex-specific queue transport abstraction.
   - Current launch support knows how to submit a prompt through the Codex picker, but it does not model Tab-based queued follow-up input at all.
   - Any attempt to bolt queueing directly into `_run_surface_bootstrap(...)` would mix shell bootstrap, prompt submission, and workflow choreography into one fragile code path.
3. There is no launcher-owned plain-message finalization contract.
   - Current launch support can submit prompt commands, but it does not append a plain Codex message such as “when finished, commit, push, and open a PR.”
   - There is also no representation for mixed workflows where some queued items are prompt commands and some are plain follow-up instructions.
4. The repo has no count-driven workflow contract yet.
   - There is no existing config/env key for “run exactly N Codex implement/finalize message cycles.”
   - There is also no structured workflow builder that can expand cycle `1` and cycles `2..N` differently.
5. Config, explain-startup, and prereq surfaces only understand “single-preset launch.”
   - There is no explicit feature gate or inspection payload for a Codex-only cycle-count workflow.
6. The current tests and docs reinforce the single-preset contract.
   - Existing plan-agent tests stop at `/prompts:implement_task` or `/implement_task`.
   - User and reference docs only describe one preset sent at launch time.

## Plan
### 1) Define a narrow Codex-only cycle workflow contract
- Add a new explicit plan-agent workflow mode instead of widening the existing default behavior implicitly.
- Recommended config shape:
  - keep `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` as the top-level launch gate
  - add a Codex-specific cycle-count setting such as `ENVCTL_PLAN_AGENT_CODEX_CYCLES`
  - default the cycle count to `0` or unset so current behavior remains unchanged unless the operator opts in
- Activation rules should be strict:
  - route must be `plan`
  - `planning_prs` must be false
  - plan-agent terminal launch must already be enabled
  - selected AI CLI must be `codex`
  - the configured cycle count must be a positive integer
- Contract semantics should be explicit:
  - `cycles = 0` or unset -> keep today’s single-preset launch behavior
  - `cycles = 1` -> queue `/prompts:implement_task` -> plain Codex finalization message
  - `cycles > 1` -> queue cycle `1`, then for each remaining cycle queue `/prompts:continue_task` -> `/prompts:implement_task` -> plain Codex finalization message
- Validate and document edge cases:
  - non-integer values fail config validation or are ignored with a clear startup/inspection warning
  - values less than `0` are invalid
  - very large values should be bounded by a hard safety cap even if the configured count is accepted
- Preserve current behavior when any of those conditions fail:
  - Codex stays on the current single-preset launch when the cycle count is unset or `0`
  - OpenCode stays on the current single-preset launch even if terminal launch is enabled
  - `--planning-prs` stays PR-only and never launches Codex tabs

### 2) Introduce a structured plan-agent workflow model instead of hard-coding a second send
- Extract the launch choreography in `python/envctl_engine/planning/plan_agent_launch_support.py` into a small script/executor model, for example:
  - `PlanAgentWorkflow`
  - `PlanAgentWorkflowStep`
  - step kinds such as `submit_prompt`, `queue_message`, `send_key`, `wait_ready`
- Keep shell bootstrap unchanged:
  - rename tab
  - respawn shell
  - `cd <worktree>`
  - launch Codex
- Move the post-Codex interaction into a workflow builder:
  - default builder returns the current single-preset flow
  - Codex cycle builder expands the configured cycle count into an ordered queue script
- Recommended workflow expansion:
  - cycle `1` starts with `/prompts:implement_task`
  - cycles `2..N` start with `/prompts:continue_task`, then `/prompts:implement_task`
  - every cycle ends with a plain queued Codex message that instructs Codex to commit, push, and open a PR when that cycle’s implementation pass is done
- This refactor should leave the low-level `cmux` transport helpers in one module while making the workflow choice testable without spinning through the whole startup stack.

### 3) Add a Codex-specific queued-message transport layer
- Add dedicated helpers for Codex queue injection, rather than overloading the current prompt-picker helpers:
  - a helper to type plain text into the active Codex input buffer
  - a helper to send `Tab` for “append/queue this message”
  - a helper to wait for the Codex input surface to be ready for queueing
- Keep prompt-picker submission and queue submission separate:
  - `/prompts:implement_task` should continue to use the current Codex prompt-picker sequence because that logic is already implemented and tested
  - queued follow-up cycle steps, including plain finalization instructions, should use the new Codex queue path instead of pretending they are prompt-picker entries
- Add readiness heuristics for the queue path using `cmux read-screen` the same way current launch support already waits on Codex startup and prompt submission.
  - The implementation should first capture real Codex queue-acceptance screens and encode those markers in one place.
  - If queue-readiness cannot be confirmed or Tab injection fails, envctl should emit a bounded fallback event and keep the initial `/implement_task` launch rather than sending half-formed follow-up input.

### 4) Make the queued workflow count-driven, not completion-inferred
- Do not make envctl parse `MAIN_TASK.md` or Codex transcript text to decide whether another iteration is needed.
- Instead, expand the configured cycle count into a deterministic queued script:
  - cycle `1`:
    - `/prompts:implement_task`
    - plain queued Codex message instructing commit, push, and PR creation
  - cycle `2..N`:
    - `/prompts:continue_task`
    - `/prompts:implement_task`
    - plain queued Codex message instructing commit, push, and PR creation
- Keep the cycle-script builder launcher-private in the first implementation.
  - Recommended ownership: a message builder/helper under `plan_agent_launch_support.py` or a nearby planning-only helper module
  - Do not add the cycle controller text to the general `install-prompts` preset inventory unless a later product requirement says it should be manually invokable as a standalone preset
- Explicitly document that envctl is queueing a fixed number of rounds, not watching task completion dynamically.

### 5) Keep the launcher contract message-only and avoid launcher-owned command execution
- The queued Codex cycle script should contain:
  - prompt commands submitted through the Codex prompt picker
  - plain queued Codex follow-up messages that tell Codex what to do next
- Do not make the launcher type shell commands such as `envctl commit`, `envctl pr`, `git commit`, `git push`, or `gh pr create`.
- The finalization instruction should be encoded as launcher-owned message text, for example:
  - “When the current implementation pass finishes, commit the work, push the branch, and open/update the PR.”
- Keep any exact wording centralized in one helper so the product contract is explicit and testable.
- Existing envctl commit/PR actions remain relevant repo evidence for how users finalize work today, but they should not be part of the new launcher-owned transport contract.

### 6) Extend config, inspection, and docs for the Codex workflow mode
- Update `python/envctl_engine/config/__init__.py` and `EngineConfig` with the new Codex cycle-count setting.
- Extend:
  - `python/envctl_engine/runtime/inspection_support.py:_print_config`
  - `python/envctl_engine/runtime/inspection_support.py:_print_startup_explanation`
  so operators can see whether Codex cycle mode is enabled, which CLI it applies to, and what cycle count will be queued.
- Update prereq logic in `python/envctl_engine/runtime/cli.py:check_prereqs` only if the new workflow introduces additional required executables.
  - If the workflow still relies only on `cmux` + `codex`, keep prereqs unchanged beyond surfacing the workflow state in inspection output.
- Update docs to describe:
  - that the cycle workflow is Codex-only
  - that it is opt-in on top of the current plan-agent launch feature
  - that `ENVCTL_PLAN_AGENT_CODEX_CYCLES=1` means `implement_task` plus one queued Codex finalization instruction
  - that `ENVCTL_PLAN_AGENT_CODEX_CYCLES>1` prepends `continue_task` before each later implementation round and appends a finalization instruction after each round
  - that OpenCode remains one-shot
  - that envctl itself is only appending messages, not executing commit/PR shell commands
- Primary doc targets:
  - `docs/user/planning-and-worktrees.md`
  - `docs/user/ai-playbooks.md`
  - `docs/reference/configuration.md`
  - `docs/reference/commands.md`

### 7) Add bounded observability and explicit fallback behavior
- Emit new plan-agent events at the workflow level, for example:
  - `planning.agent_launch.workflow_selected`
  - `planning.agent_launch.workflow_queued`
  - `planning.agent_launch.workflow_fallback`
  - `planning.agent_launch.workflow_queue_failed`
- Payloads should include only bounded metadata:
  - CLI
  - workflow mode (`single_prompt` vs `codex_cycles`)
  - created worktree count / worktree name
  - configured cycle count
  - fallback/failure reason
- Do not persist live Codex queue contents or transcript text into runtime state.
- Fallback policy should be explicit:
  - if initial Codex launch works but queued cycle-script injection fails, leave the surface running with the initial `/implement_task` submission and report that cycle mode was skipped for that worktree
  - do not close the tab or delete the created worktree on queue failure

## Tests (add these)
### Backend tests
- Extend `tests/python/planning/test_plan_agent_launch_support.py`:
  - config resolution for the new Codex cycle-count setting
  - Codex with no configured cycles still sends only `/prompts:implement_task`
  - `cycles=1` queues `/prompts:implement_task`, then one plain finalization message
  - `cycles=2` queues cycle `1`, then `/prompts:continue_task`, `/prompts:implement_task`, and the second-cycle finalization message
  - queued workflow path sends `Tab` only for Codex and never for OpenCode
  - queue failure / readiness failure falls back to the single-prompt launch result without cancelling the initial surface
  - cycle-script builder includes explicit references to `continue_task`, `implement_task`, and the finalization instruction text
- Add a focused unit test module if the controller-message or workflow-script builder is split out, for example `tests/python/planning/test_plan_agent_workflow_support.py`:
  - single-prompt workflow script
  - `cycles=1` script
  - `cycles>1` script
  - invalid / bounded cycle-count rendering
  - CLI gating and fallback reasons
- Extend `tests/python/runtime/test_prereq_policy.py` only if new config/env keys alter prereq evaluation or explain-startup reasons.

### Frontend tests
- Extend `tests/python/runtime/test_engine_runtime_command_parity.py`:
  - `explain-startup --json` reports the new Codex cycle-count state consistently
  - OpenCode explain-startup output remains on the single-prompt workflow
- If `show-config --json` or plain-text config output is expanded, extend the matching inspection/config tests under `tests/python/runtime/` so the new fields are visible and stable.

### Integration/E2E tests
- Extend `tests/python/runtime/test_engine_runtime_real_startup.py`:
  - plan launch with Codex cycle mode still triggers only for newly created worktrees
  - `--planning-prs` still does not invoke the launcher even when a Codex cycle count is configured
  - OpenCode remains on the existing one-shot launch path when the Codex cycle-count setting is set
- Prefer one live/manual verification checklist over a large synthetic E2E suite for the queue semantics, because the new behavior depends on real Codex UI handling in `cmux`.
- Manual verification should explicitly cover:
  - Codex launch with no configured cycles
  - Codex launch with `cycles=1`
  - Codex launch with `cycles=2`
  - OpenCode launch with the same base plan-agent settings
  - queue-failure fallback path
  - a real task that reaches repeated queued finalization messages through the cycle flow

## Observability / logging (if relevant)
- Keep all new observability in the existing `planning.agent_launch.*` namespace so plan-agent diagnostics stay grouped.
- Add one compact summary line to stdout only when the workflow mode differs from the current default, for example:
  - `Plan agent launch queued Codex cycle workflow (cycles=2) for 1 surface(s).`
- Avoid printing the full queued finalization message body to stdout or structured events.
- If implementation needs to store a debug artifact for live queue troubleshooting, keep it under the runtime debug root rather than in repo-tracked files.

## Rollout / verification
- Implement in this order:
  1. refactor one-shot launch into a workflow-script model without changing current behavior
  2. add Codex cycle-count config, inspection output, and tests
  3. add the Codex queue transport helpers and fallback handling
  4. add the queued cycle-script builder and real-startup coverage
  5. update docs
- Automated verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity tests.python.runtime.test_prereq_policy`
- Manual verification:
  - enable the current `cmux` plan-agent launch feature with Codex only, run `envctl --plan <plan> --batch`, and confirm the launched Codex tab still reaches the current `/prompts:implement_task` state
  - set `ENVCTL_PLAN_AGENT_CODEX_CYCLES=1`, rerun `envctl --plan <plan> --batch`, and confirm the same Codex tab receives queued `implement_task` plus one finalization message
  - set `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`, rerun `envctl --plan <plan> --batch`, and confirm the same Codex tab receives the second-cycle `continue_task` + `implement_task` + finalization-message sequence
  - verify that OpenCode launch remains unchanged under the same repository config
  - validate that a queue failure leaves the initial Codex session usable and prints/emits the fallback reason
  - run a real completion pass and confirm envctl itself only queued messages and did not type shell commands into the worktree terminal

## Definition of done
- Envctl has an explicit Codex-only cycle-count workflow mode on top of the existing post-`--plan` `cmux` launcher.
- The existing default behavior remains unchanged for OpenCode and for Codex when the new mode is disabled.
- The launcher can submit the initial Codex prompt and queue the cycle-script steps through a dedicated, tested Codex queue path.
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=1` queues `implement_task` plus one finalization instruction message.
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES>1` queues later rounds as `continue_task`, `implement_task`, and a finalization instruction message.
- The queued Codex workflow uses only prompt commands and plain queued messages; the launcher does not execute commit/PR shell commands itself.
- Explain-startup/config/docs describe the new cycle-count mode accurately.
- Focused planning/runtime tests and real `cmux` + Codex verification cover the new queueing and fallback paths.

## Risk register (trade-offs or missing tests)
- Risk: Codex `Tab` queue semantics and on-screen markers may change across Codex CLI versions.
  - Mitigation: isolate queue heuristics in one helper, add a clean fallback to the current single-prompt launch, and require live Codex verification before treating the feature as complete.
- Risk: fixed cycle counts can over-run the real remaining scope, causing Codex to queue extra `continue_task` / finalization messages after the work is already effectively done.
  - Mitigation: make the feature opt-in, keep `cycles` small by default, and require live validation of the exact queued wording for `cycles=1` and `cycles=2` before broader use.
- Risk: adding the workflow model could unintentionally regress the already-shipped one-shot launch path.
  - Mitigation: land the workflow-script refactor first with no behavior change and keep the current Codex/OpenCode launch tests as baseline regressions.

## Open questions (only if unavoidable)
- None. The repo evidence is sufficient to plan the Codex-only extension with the assumptions above.
