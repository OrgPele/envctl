# Envctl Plan-Agent Launch Truthful Output And Codex Queue Readiness

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make `envctl --plan` report plan-agent launch status in a way that distinguishes worktree creation, skipped tree service startup, surface creation, Codex bootstrap, initial prompt submission, and queued-workflow fallback/failure.
  - Fix the actual Codex queued-workflow path so envctl can reliably queue the configured follow-up cycle script instead of degrading with `queue_not_ready` while still claiming a successful launch.
  - Preserve the useful parts of the current flow:
    - newly created worktrees only
    - repo-scoped `cmux` launch
    - Codex/OpenCode CLI selection
    - review-tab launcher reuse
  - Keep launch diagnostics bounded and inspectable from runtime artifacts rather than forcing operators to infer state from ambiguous stdout.
- Non-goals:
  - Changing worktree selection/sync semantics in [`python/envctl_engine/planning/worktree_domain.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/worktree_domain.py).
  - Reworking startup-disabled tree mode itself. `TREES_STARTUP_ENABLE=false` should still skip service startup.
  - Replacing the current `cmux` transport or adding a different terminal multiplexer.
  - Changing the plan prompt templates themselves beyond any launcher-side message ordering that is required for reliable queue submission.
- Assumptions:
  - The user’s inference that “planning mode complete; skipping service startup...” meant “Codex did not launch” is reasonable given the current stdout ordering and wording, even though code sequencing shows the launcher ran before that line.
  - The observed runtime artifact from the actual run is valid evidence for this bug:
    - [`events.jsonl`](/tmp/envctl-runtime/python-engine/repo-0fcdb042dfb9/runs/run-20260320111549-e090c770/events.jsonl)
    - live surface snapshot from `cmux read-screen --workspace workspace:1 --surface surface:54`

## Goal (user experience)
When an operator runs `envctl --headless --plan <selector>` with plan-agent launch enabled, envctl should print a clear summary of what actually happened. If tree service startup is disabled, the output should say that service startup was skipped without implying that the plan-agent launch was skipped too. If Codex launches and the initial prompt is sent but queued follow-up steps fall back or fail, envctl should say so explicitly. If the full queued workflow succeeds, envctl should say that explicitly too. Operators should not need to inspect raw events or the cmux surface to know whether envctl only opened a surface, actually started Codex, successfully submitted the first prompt, or degraded before the queued cycle script was attached.

## Business logic and data model mapping
- Plan-agent launch configuration, workflow building, and transport:
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:resolve_plan_agent_launch_config`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L223)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_build_plan_agent_workflow`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L195)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:launch_plan_agent_terminals`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L421)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_launch_single_worktree`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L531)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_complete_surface_bootstrap`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L645)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_run_surface_bootstrap`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L730)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_submit_prompt_workflow_step`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L847)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_queue_codex_workflow_steps`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L963)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_wait_for_codex_queue_ready`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L995)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_queue_codex_message`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1012)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_read_surface_screen`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1700)
- Startup orchestration and the user-facing “planning mode complete” line:
  - [`python/envctl_engine/startup/startup_orchestrator.py:_select_contexts`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/startup/startup_orchestrator.py#L262)
  - [`python/envctl_engine/startup/startup_orchestrator.py:_resolve_disabled_startup_mode`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/startup/startup_orchestrator.py#L318)
- Config / inspection surfaces that currently describe intent rather than launch outcome:
  - [`python/envctl_engine/runtime/inspection_support.py:_print_config`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/inspection_support.py#L95)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:inspect_plan_agent_launch`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L292)
- Runtime artifact persistence:
  - [`python/envctl_engine/state/repository.py:RuntimeStateRepository.run_dir_path`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/state/repository.py#L62)
  - [`python/envctl_engine/runtime/engine_runtime_event_support.py:_persist_runtime_events_snapshot`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/engine_runtime_event_support.py)
- Existing tests and docs that define or reinforce current behavior:
  - [`tests/python/planning/test_plan_agent_launch_support.py`](/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py)
  - [`tests/python/runtime/test_lifecycle_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_lifecycle_parity.py)
  - [`tests/python/runtime/test_engine_runtime_command_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_command_parity.py)
  - [`docs/reference/commands.md`](/Users/kfiramar/projects/current/envctl/docs/reference/commands.md)
  - [`docs/reference/configuration.md`](/Users/kfiramar/projects/current/envctl/docs/reference/configuration.md)
  - [`docs/user/planning-and-worktrees.md`](/Users/kfiramar/projects/current/envctl/docs/user/planning-and-worktrees.md)

## Current behavior (verified in code)
- Plan-agent launch is started before the “trees startup disabled” short-circuit.
  - [`StartupOrchestrator._select_contexts(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/startup/startup_orchestrator.py#L262) calls [`launch_plan_agent_terminals(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L421) during `plan` handling.
  - Only afterward does [`_resolve_disabled_startup_mode(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/startup/startup_orchestrator.py#L318) print `Planning mode complete; skipping service startup because envctl runs are disabled for trees.`
  - So the current wording is misleading, not a faithful description of launch sequencing.
- The top-level launcher reports success too early.
  - [`launch_plan_agent_terminals(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L421) prints:
    - `Plan agent launch queued Codex cycle workflow ...`
    - `Plan agent launch opened N cmux surface(s).`
  - Those lines are emitted after `_launch_single_worktree(...)` returns, but `_launch_single_worktree(...)` only creates/reuses the surface and starts a background thread via [`_start_background_surface_bootstrap(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L604).
  - It does not wait for Codex readiness, first prompt submission, or queued-workflow completion.
- Late bootstrap failures or degradations are not surfaced to stdout.
  - [`_complete_surface_bootstrap(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L645) emits runtime events such as:
    - `planning.agent_launch.command_sent`
    - `planning.agent_launch.failed`
    - `planning.agent_launch.workflow_queue_failed`
    - `planning.agent_launch.workflow_fallback`
  - But those events do not feed back into a final human-readable launch summary.
- The queued-workflow failure path is intentionally swallowed as a successful overall bootstrap.
  - In [`_run_surface_bootstrap(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L730), when `_queue_codex_workflow_steps(...)` returns a reason, envctl emits `workflow_queue_failed` and `workflow_fallback` and then returns `None`.
  - That causes [`_complete_surface_bootstrap(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L645) to emit `planning.agent_launch.command_sent` anyway.
  - Result: the launcher treats “initial prompt sent, queued script degraded” as a generic success with no stdout distinction.
- The queue transport is brittle and can leave stray typed text in the Codex input.
  - [`_queue_codex_workflow_steps(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L963) calls [`_send_surface_text(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1596) before queue readiness is confirmed.
  - [`_queue_codex_message(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1012) only returns success once it sees both:
    - the typed text on screen
    - `_CODEX_QUEUE_READY_HINT = "tab to queue message"`
  - If that hint never appears, the pre-typed message remains in the Codex input and the function times out with `queue_not_ready`.
- The observed run reproduced that exact path.
  - [`events.jsonl`](/tmp/envctl-runtime/python-engine/repo-0fcdb042dfb9/runs/run-20260320111549-e090c770/events.jsonl) contains:
    - `planning.agent_launch.surface_created`
    - `planning.agent_launch.workflow_queue_failed` with `reason="queue_not_ready"`
    - `planning.agent_launch.workflow_fallback`
    - `planning.agent_launch.command_sent`
  - The live `cmux read-screen` snapshot for `workspace:1 / surface:54` showed Codex running with a plain follow-up message sitting in the input buffer:
    - `› When the current implementation pass finishes, commit the work, push the branch, and open or update the PR.`
  - That means the launcher did start Codex, but the queued cycle workflow did not actually complete as promised.
- Docs and config surfaces are already drifted on default cycle semantics.
  - [`resolve_plan_agent_launch_config(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L223) parses unset cycles as `0`.
  - But [`docs/reference/commands.md`](/Users/kfiramar/projects/current/envctl/docs/reference/commands.md), [`docs/reference/configuration.md`](/Users/kfiramar/projects/current/envctl/docs/reference/configuration.md), and [`docs/user/planning-and-worktrees.md`](/Users/kfiramar/projects/current/envctl/docs/user/planning-and-worktrees.md) currently describe the default/unset value as `1`.
  - That mismatch makes the already-ambiguous launch messaging harder to trust.
- Existing tests mostly validate event emission and optimistic return status, not human-readable truthfulness.
  - [`tests/python/planning/test_plan_agent_launch_support.py`](/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py) covers `workflow_queue_failed` and `workflow_fallback` events, but it does not assert a user-facing degraded summary.
  - [`tests/python/runtime/test_lifecycle_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_lifecycle_parity.py) locks in the current “Planning mode complete; skipping service startup...” line without any plan-agent context.

## Root cause(s) / gaps
- The launcher contract conflates three different states:
  - surface created
  - initial bootstrap/prompt succeeded
  - queued workflow succeeded
- Human-readable output is emitted from the synchronous surface-creation path, while the meaningful readiness/fallback truth lives only in background-thread events.
- The queue algorithm is destructive before it is confident.
  - It types into the Codex input first and only later tries to prove that the `Tab` queue affordance is available.
- The fallback policy is operationally safe but semantically too quiet.
  - `queue_not_ready` falls back to initial prompt only, but stdout still sounds like the full configured cycle workflow was queued.
- Docs and inspection surfaces do not give operators a consistent contract for:
  - what “opened” means
  - what “queued” means
  - whether `codex_cycles` defaults to `0` or `1`

## Plan
### 1) Introduce an explicit per-worktree launch outcome model that separates surface creation from verified bootstrap
- Replace the current optimistic “launched” meaning in [`PlanAgentLaunchOutcome`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L103) with a richer internal outcome contract that can distinguish:
  - `surface_opened`
  - `bootstrap_succeeded`
  - `initial_prompt_sent`
  - `workflow_queued`
  - `workflow_fallback`
  - `bootstrap_failed`
- Keep the public launcher result simple, but derive it from final bootstrap truth rather than from “thread started.”
- Preserve partial success semantics when multiple worktrees are launched and only some fully bootstrap.

### 2) Stop printing the final launch summary before the background bootstrap is known
- Refactor [`launch_plan_agent_terminals(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L421) so it can wait for or collect the final results of `_complete_surface_bootstrap(...)` before printing the closing user-facing summary.
- Because the bootstrap threads are already `daemon=False`, envctl is effectively waiting for them anyway before process exit; the fix should use that time to report truthful outcomes rather than optimistic ones.
- The human-facing summary should distinguish at least these cases:
  - surface(s) opened and initial prompt sent
  - queued Codex workflow attached successfully
  - queued workflow fell back to initial prompt only
  - bootstrap failed for one or more surfaces
- Preserve concise phrasing, but make “opened surface” weaker than “Codex ready and prompt sent.”

### 3) Reword the tree-startup-disabled message so it cannot be mistaken for plan-agent skip
- Update [`StartupOrchestrator._resolve_disabled_startup_mode(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/startup/startup_orchestrator.py#L318) to separate:
  - planning/worktree reconciliation completion
  - service-startup skip due to `TREES_STARTUP_ENABLE=false`
  - plan-agent launch result
- Recommended user-facing direction:
  - keep the service-startup skip message
  - stop using it as the only “planning complete” line when plan-agent launch is active
  - add one explicit plan-agent line or fold the launch result into a final summary block
- The final output should make it obvious that service startup and plan-agent launch are independent decisions.

### 4) Make Codex queue submission non-destructive until readiness is proven
- Rework [`_queue_codex_workflow_steps(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L963) and [`_queue_codex_message(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1012) so envctl does not type follow-up text into the Codex input before it has a high-confidence signal that the queue affordance is ready.
- Options to resolve in implementation, based on local Codex behavior:
  - wait for queue readiness before typing each queued step
  - or type only after a dedicated readiness helper confirms the input is in a queueable state
- If a step still times out after typing has begun, add cleanup behavior so the input buffer is not left with a stray partially queued instruction.
- Keep the fallback policy, but make the transport hygienic.

### 5) Harden the Codex queue-readiness heuristic against current screen variants
- Revisit the readiness signals in:
  - [`_wait_for_codex_queue_ready(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L995)
  - [`_codex_queue_screen_looks_ready(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1004)
  - [`_codex_queue_message_needs_tab(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1047)
- Ground the fix in actual Codex screen captures from this repo’s supported workflow, including:
  - startup banner/update banner
  - active working state
  - prompt picker state
  - post-submit idle state
  - queue affordance state
- The plan should preserve bounded polling, but the heuristic should not require an exact one-line hint if Codex’s UI has evolved while the queue behavior remains available.

### 6) Align success/fallback events, inspection, and docs with the real launch contract
- Rename or supplement `planning.agent_launch.command_sent` so it clearly means “initial prompt sent” rather than “full configured workflow succeeded.”
- Add one bounded outcome event per worktree, for example:
  - `planning.agent_launch.result`
  - with `status=queued|prompt_only|failed`
- Consider persisting a small launch-outcome summary into run metadata when `--plan` is used, so later inspection or dashboard surfaces can report what happened without scraping `events.jsonl`.
- Update `inspect_plan_agent_launch(...)` and, if warranted, `show-config`/`explain-startup` wording so operators can distinguish config intent from actual last-run launch outcome.

### 7) Reconcile docs and config defaults before further launch troubleshooting
- Fix the docs/code mismatch for `ENVCTL_PLAN_AGENT_CODEX_CYCLES`.
  - Code currently treats unset/default as `0`.
  - Docs currently describe unset/default as `1`.
- Update these docs together so the operator contract is consistent:
  - [`docs/reference/configuration.md`](/Users/kfiramar/projects/current/envctl/docs/reference/configuration.md)
  - [`docs/reference/commands.md`](/Users/kfiramar/projects/current/envctl/docs/reference/commands.md)
  - [`docs/user/planning-and-worktrees.md`](/Users/kfiramar/projects/current/envctl/docs/user/planning-and-worktrees.md)
- Document the new truthful launch-result wording and fallback semantics:
  - what counts as “surface opened”
  - what counts as “initial prompt sent”
  - what counts as “queued workflow attached”
  - what fallback means when queue injection is not ready

## Tests (add these)
### Backend tests
- Extend [`tests/python/planning/test_plan_agent_launch_support.py`](/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py):
  - top-level launch summary reflects final bootstrap truth, not just surface creation
  - `workflow_queue_failed` results in a human-visible degraded summary, not a generic “opened” success
  - `command_sent`/result events distinguish `initial_prompt_sent` from `workflow_queued`
  - queue submission waits for readiness before typing queued text
  - queue timeout cleanup avoids leaving a stray typed message in the modeled screen/input state
  - actual `queue_not_ready` fallback path produces `prompt_only` or equivalent result status
- Extend [`tests/python/runtime/test_lifecycle_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_lifecycle_parity.py):
  - planning-mode output with `TREES_STARTUP_ENABLE=false` no longer implies that plan-agent launch was skipped
  - service-startup skip wording remains accurate and separated from plan-agent launch wording
- Extend [`tests/python/runtime/test_engine_runtime_command_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_command_parity.py):
  - `show-config` / `explain-startup` reflect the corrected `codex_cycles` default contract
  - any new inspection payload for launch outcome or terminology is covered
- Extend [`tests/python/runtime/test_engine_runtime_real_startup.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_real_startup.py) if needed:
  - plan mode with disabled tree startup still launches plan-agent worktrees and prints the clarified final status

### Frontend tests
- None in the browser sense.
- No Textual/dashboard UI changes are required unless implementation chooses to surface the new launch outcome there too.

### Integration/E2E tests
- Manual verification using the current repo and cmux workspace:
  1. Run `envctl --headless --plan <selector>` with `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`, `ENVCTL_PLAN_AGENT_CLI=codex`, and `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`.
  2. Confirm stdout distinguishes service-startup skip from plan-agent launch outcome.
  3. Confirm a full success case reports initial prompt submission plus queued workflow success.
  4. Force or simulate queue fallback and confirm stdout reports prompt-only fallback explicitly.
  5. Inspect the launched cmux surface and confirm failed queue attempts do not leave stray follow-up text in the input buffer.
  6. Confirm runtime events and any persisted launch-outcome metadata match the human-readable summary.

## Observability / logging (if relevant)
- Keep existing launch events, but add a final bounded per-worktree result event with:
  - `workspace_id`
  - `surface_id`
  - `worktree`
  - `cli`
  - `workflow_mode`
  - `codex_cycles`
  - `result_status`
  - `reason`
- Preserve `workflow_queue_failed` and `workflow_fallback` because they are useful low-level diagnostics.
- Add one user-facing summary line or block derived from those final results rather than from early optimistic state.
- Avoid logging full screen contents in normal runtime events; keep that only for targeted debug flows if needed later.

## Rollout / verification
- Implementation order:
  1. fix the launch outcome model and truthful final summary contract
  2. reword the startup-disabled plan output so launch and service-startup status are separate
  3. harden queue readiness and make queue submission non-destructive
  4. align events/inspection surfaces
  5. fix docs/default drift
- Verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.planning.test_plan_agent_launch_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_lifecycle_parity`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
- No data migration, schema migration, or worktree cleanup task is required.

## Definition of done
- `envctl --plan` no longer reports a misleading launch success before background bootstrap truth is known.
- The “service startup skipped because runs are disabled for trees” line is understandable and no longer reads like plan-agent launch was skipped.
- Codex queued workflow setup succeeds reliably for supported screen states or degrades explicitly to “initial prompt only.”
- Queue fallback does not leave stray follow-up text typed into the Codex input.
- Docs and inspection surfaces match the actual `codex_cycles` default and launch-result semantics.
- Automated tests cover truthful summary output, queue-readiness behavior, and the corrected startup-disabled messaging.

## Risk register (trade-offs or missing tests)
- Risk: waiting for final bootstrap truth before printing the summary could lengthen perceived command completion.
  - Mitigation: envctl is already kept alive by non-daemon bootstrap threads; use that time to report final truth rather than optimistic placeholders.
- Risk: queue-readiness heuristics may remain sensitive to future Codex UI changes.
  - Mitigation: keep heuristics centralized, bounded, and covered by fixture-style screen tests.
- Risk: changing summary semantics may break tests or operator habits that currently treat “opened surface(s)” as sufficient.
  - Mitigation: preserve concise wording but explicitly separate `surface opened` from `workflow queued`.
- Risk: adding persisted launch-outcome metadata could overcomplicate a mostly ephemeral workflow.
  - Mitigation: keep persistence additive and minimal; use runtime events as the primary source unless later inspection needs prove otherwise.

## Open questions (only if unavoidable)
- None. The repo code plus the captured runtime artifact from the observed run are sufficient to define the fix plan.
