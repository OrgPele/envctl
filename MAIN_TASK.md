# Envctl Remaining Runtime Orchestrator Decomposition

## Context and objective

The previous deep-refactor iteration is partially complete. Preserve the completed planning/worktree ownership slices and
finish the remaining refactor end-to-end in this checkout.

Current evidence shows the branch is reconciled with the worktree provenance source ref:

- `.envctl-state/worktree-provenance.json` identifies `source_ref` as
  `origin/codex/reuse-cgc-worktree-context`.
- `git merge-base HEAD origin/codex/reuse-cgc-worktree-context` resolves to
  `dc131e8461c70657c63e8faaea72f12a357de62e`, the same commit currently at that source ref.
- Committed divergence from that base contains the deep-refactor commits only:
  `67f588b`, `6a76bbe`, `ddcf515`, `c3bdb24`, `2e9fe27`, `628aa9a`, and `9991180`.

Completed and preserved planning ownership slices:

- `planning/worktree_code_intelligence.py` owns generated-worktree Serena/CGC setup.
- `planning/worktree_provenance.py` owns provenance, source-branch resolution, and active fresh-AI worktree protection.
- `planning/worktree_git_hooks.py` owns `ENVCTL_WORKTREE_GIT_HOOKS` parsing and disabled/inherit policy checks.
- `planning/worktree_main_task.py` owns generated worktree `MAIN_TASK.md` seeding, plan archival into `todo/done`,
  and numeric iteration gap selection.
- `planning/worktree_project_catalog.py` owns project candidate discovery, cleanup, and sorting for generated
  worktrees.
- `planning/worktree_selection_memory.py` owns plan selection memory path resolution, load/save behavior, and initial
  selected-count calculation.
- `planning/worktree_shared_artifacts.py` owns generated-worktree shared-artifact compatibility links.
- `planning/worktree_creation_recovery.py` owns partial worktree-add recovery and placeholder fallback behavior.
- `planning/worktree_plan_selection.py` owns fresh-AI plan-count adjustment, launch transport selection, and
  keep-plan flag/config parsing.
- `planning/worktree_plan_project_selection.py` owns plan selector resolution, dry-run prediction, no-TTY/no-plan
  handling, and plan-worktree sync result mapping.
- `planning/worktree_prompt_selection.py` owns interactive plan-count prompt seeding and memory persistence decisions.
- `planning/worktree_creation_commands.py` owns git worktree-add branch naming, branch existence checks, start-point
  selection, and command execution.
- `planning/worktree_identity.py` owns the shared generated-worktree identity so branch names and envctl project names
  remain identical.
- `planning/worktree_planning_menu.py` owns interactive planning menu invocation, result normalization, fallback, and
  terminal-state cleanup.
- `planning/worktree_setup_entries.py` owns setup flag parsing, include-token resolution, and single/multi setup-entry
  application.
- `planning/worktree_setup_coordinator.py` owns spinner-wrapped setup-worktree selection coordination.
- `planning/worktree_sync_deletion.py` owns excess plan-worktree deletion ordering, fresh-AI protection skips, blast
  cleanup warnings, and delete failure propagation.
- `planning/worktree_sync_orchestration.py` owns plan-count sync aggregation, single-plan create/delete decisions, and
  deletion result summarization.
- `runtime/engine_runtime_action_support.py` owns runtime action command entry-point wrappers, passthrough selector
  parsing, service-name-to-project-name compatibility mapping, action env/replacement handoff, and project action
  delegation.
- `runtime/engine_runtime_cli_support.py` owns runtime help rendering, config command handoff, hook migration command
  handoff, and unsupported-command output.
- `runtime/engine_runtime_doctor_support.py` owns runtime doctor handoff, readiness-gate handoff, release shipability
  evaluation, doctor test policy, and runtime readiness contract enforcement.
- `runtime/engine_runtime_bookkeeping_support.py` owns runtime legacy lock compatibility, emit-listener registration,
  and per-project startup warning bookkeeping.
- `runtime/engine_runtime_state_support.py` owns runtime state artifact JSON helpers, synthetic-state detection,
  state-action handoff, strict mode lookup handoff, and port event forwarding.
- `runtime/engine_runtime_ui_bridge.py` owns runtime dashboard command bridging, interactive command/input parsing,
  UI backend selection, target selection handoff, terminal command input, terminal-state restore, and interactive TTY
  detection.
- `runtime/engine_runtime_dispatch.py` owns runtime dispatch entry setup, process probe creation, effective route-mode
  event emission, debug-recorder configuration, and command-family dispatch.
- `actions/action_runtime_facade.py` owns the action runtime compatibility facade used by action helpers to reach
  runtime collaborators, legacy private methods, state repositories, emitters, selectors, and worktree cleanup hooks.
- `actions/action_failed_rerun_support.py` owns saved failed-test rerun planning, manifest loading and validation,
  invalid-selector reporting, non-rerunnable failure messaging, and extraction-failure detection.
- `actions/action_target_support.py` owns action target context creation, service-target project expansion, selector
  resolution, all/untested/no-target policy, and targeted action execution.
- `actions/action_test_plan_support.py` owns test action execution spec selection, test status rendering, test
  service-selection policy, parallel test policy, configured test command resolution, failed-only delegation,
  additional-service test delegation, legacy tree test-script detection, and frontend test path precedence.
- `actions/action_test_service_support.py` owns additional-service test selection, service test command validation,
  service-specific cwd resolution, and per-target additional-service test execution specs.
- `actions/action_test_summary_support.py` owns failed-test summary artifact rendering, failed-test collection, manifest
  entries, suite overview rendering, summary error-line formatting, traceback/captured-output extraction, suite display
  names, failed-only preservation, test git-state fingerprints, test-summary artifact persistence, and per-run
  test-results directory allocation.
- `actions/action_output_support.py` owns action command color enablement and ANSI style rendering for action/test
  terminal output.
- `actions/action_command_execution_support.py` owns action command dispatch, target-resolution finish handling, action
  spinner lifecycle orchestration, interrupt finish events, and deferred post-action output execution.
- `actions/action_spinner_support.py` owns action command spinner status bridging, action spinner lifecycle update
  emission, and legacy `_emit` bridge restoration.
- `actions/action_worktree_runner.py` owns delete/blast worktree execution and self-destruct worktree execution,
  including current-worktree target resolution, worktree-layout repo root detection, current-worktree validation,
  cleanup warning reporting, main-repo resolution handoff, and detached helper launch handoff.
- `actions/action_migrate_execution_support.py` owns migrate command resolution, migrate process execution handoff,
  migrate action outcome collection, failure headline/summary mapping, and deferred noninteractive result summaries.
- `actions/action_migrate_support.py` owns migrate result records, backend-env hints, compact multi-project failure
  summaries, migrate failure headline selection, migrate requirements/context projection, migration failure log
  rendering, and report path display.
- `actions/project_action_support.py` owns project action replacements, base action environment construction,
  backend test env projection, migrate backend env contract metadata persistence, project action command resolution,
  streaming review execution policy, process-run wiring, targeted-action execution handoff, project action
  success/failure handler construction, project action success status, review artifact path parsing, failure report
  writing, and persisted project action report metadata.
- `planning/worktree_domain.py` remains a compatibility facade for those extracted helpers.

Fully implement the remaining decomposition work without changing CLI semantics, persistent state formats, generated
contract formats, prompt preset behavior, plan-agent launch behavior, startup logs, debug reports, release-gate behavior,
or user-facing output except where a compatibility-preserving refactor requires a tested update.

All file edits must stay inside this checkout. Do not modify sibling worktrees or paths outside the current repo root.
The local `.envctl-state/worktree-provenance.json` change is state metadata and must stay out of unrelated
implementation commits unless a task explicitly requires changing it.

## Remaining requirements (complete and exhaustive)

1. Finish planning/worktree responsibility separation.
   - Keep the completed owner modules listed above as the implementation owners for their behavior.
   - Keep `planning/worktree_domain.py` as a compatibility facade for the extracted planning owner modules.
   - Keep public helper names and orchestrator call sites stable until callers are moved safely.
   - Preserve the strict boundary that planning operations only write inside the current checkout or generated plan
     worktrees.
   - Add focused tests for every extracted owner, including sibling-worktree safety, fresh-AI protection, provenance
     preservation, git-hook policy behavior, code-intelligence setup, `MAIN_TASK.md` seeding, plan archival, and
     iteration selection.

2. Thin `PythonEngineRuntime` into explicit runtime delegates.
   - Reduce `python/envctl_engine/runtime/engine_runtime.py` from a broad facade into construction, command dispatch,
     compatibility wrappers, and delegation to focused owner modules.
   - Group and move cohesive clusters into existing `runtime/engine_runtime_*_support.py` modules or new owner modules
     where no clear owner exists:
     - dispatch/help and command policy,
     - project resolution and target selection,
     - lifecycle start/resume/stop and cleanup,
     - action command entry points,
     - debug, doctor, release-gate, and generated contract helpers,
     - dashboard and interactive commands,
     - service command helpers and environment overlays,
     - hook bridging,
     - state truth, readiness, and listener reconciliation.
   - Preserve `PythonEngineRuntime` as the public CLI/test facade.
   - Preserve command routing behavior, exit statuses, output shapes, state writes, and generated runtime feature matrix
     contents unless a generator output change is intentional and committed with evidence.
   - Add focused runtime facade/delegate tests so route selection, exit status, and output cannot drift.

3. Decompose startup orchestration by lifecycle phase.
   - Extract plan-agent worktree preparation and launch handoff from `startup/startup_orchestrator.py` into a narrow
     planning/startup coordinator with explicit input/result objects.
   - Extract restart/reuse/pre-stop policy into a startup policy module.
   - Extract success, degraded, and failure finalization into helpers that own user-facing summaries and debug report
     references.
   - Extract requirement and service startup sequencing into a service bootstrap coordinator while preserving readiness
     and truth reconciliation semantics.
   - Keep `StartupOrchestrator.execute` as the readable high-level sequence owner.
   - Preserve behavior for degraded handoff, plan-agent launch skip/resume, disabled modes, startup logs, state truth,
     runtime startup integration, debug report references, and final summaries.

4. Split action command orchestration into action-owned helpers.
   - Move remaining target resolution and project scope selection logic into action target helpers.
   - Move `test` action execution and failed-test summary formatting into test action helpers.
   - Move `migrate` hints, migration logs, and migration result reporting into migrate action helpers.
   - Move remaining self-destruct worktree handling into worktree action helpers with explicit safety checks.
   - Move project action environment/replacement/artifact persistence into reusable project action support.
   - Keep `ActionCommandOrchestrator` as the compatibility entry point.
   - Split `tests/python/actions/test_actions_parity.py` into action-owned suites as production seams are extracted,
     preserving fixtures and assertion intent.

5. Normalize plan-agent transport concepts and option-matrix coverage.
   - Introduce or complete shared vocabulary for launch intent, selected surface, prompt preset, readiness expectation,
     command preview, session identity, failure reason, and recovery guidance.
   - Keep transport-specific process/session behavior in the existing transport modules:
     `planning/plan_agent/cmux_transport.py`, `tmux_transport.py`, `omx_transport.py`, `superset_transport.py`,
     OpenCode/Codex launch paths, workflow helpers, and recovery modules.
   - Route common option mapping and result rendering through shared helpers.
   - Add tests that exercise the same option matrix across `--cmux`, `--tmux`, `--omx`, `--codex`, `--opencode`,
     `--ulw`, `--no-ulw-loop`, `--new-session`, `--headless`, direct-prompt behavior, skipped launches, and resumed
     launches.
   - Keep OpenCode-specific readiness failures observable with active command, expected prompt state, transport, timeout,
     and recovery guidance.
   - Regenerate and compare `contracts/runtime_feature_matrix.json` only if declared feature inventory changes.

6. Break requirements adapters into lifecycle components, starting with Supabase.
   - Split `requirements/supabase.py` into smaller owners for:
     - configuration and env resolution,
     - Docker/process lifecycle,
     - health and readiness checks,
     - database setup,
     - QA/auth user setup,
     - repair and reinit,
     - summary reporting.
   - Keep the existing adapter API stable for startup and runtime callers.
   - Add adapter-level tests proving contract behavior before and after the split.
   - Apply the same component pattern to other adapters only where it reduces complexity without hiding behavior behind
     generic abstractions.

7. Split dashboard orchestration and oversized UI tests by behavior owner.
   - Reduce `ui/dashboard/orchestrator.py` to a coordination layer with explicit owners for backend resolution,
     rendering, restart selection, PR flow, command parsing, and terminal interaction.
   - Split `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` by behavior owner once production seams are
     in place.
   - Preserve dashboard rendering contracts, restart selector behavior, backend selection, PR flow behavior, and
     terminal command semantics.

8. Split remaining oversized tests after production seams exist.
   - Split tests by behavior owner, not arbitrary line count:
     - plan-agent launch options,
     - transport readiness,
     - action parity,
     - runtime startup,
     - requirement adapter contracts,
     - dashboard restart selector behavior.
   - Move tests in the same commit as the production extraction they protect where practical.
   - Preserve existing fixtures, assertions, and regression coverage.
   - Add structure/import guards only after realistic module boundaries exist, and include explicit waivers for
     legitimate compatibility facades.

9. Tighten generated contracts, docs, and release checks.
   - Keep `docs/reference/python-engine-architecture.md` aligned after each major extraction.
   - Add or update contributor-facing "how to change this area" notes for runtime, startup, actions, planning,
     transports, requirements, and dashboard code as owner modules become real.
   - Re-run generated contract scripts only when behavior or declared feature inventory intentionally changes:
     `scripts/generate_runtime_feature_matrix.py`,
     `scripts/generate_python_runtime_gap_report.py`,
     `scripts/generate_python_engine_parity_manifest.py`.
   - Compare generated JSON artifacts and commit updates only when intentional.
   - Keep import-cycle and structure-layout failures actionable by pointing to the owning module family.

10. Preserve all compatibility and persistent contracts.
    - Do not redesign the CLI or remove compatibility commands.
    - Do not resurrect the old shell runtime.
    - Do not change prompt preset semantics, runtime state schemas, generated contract formats, `.envctl-state`
      artifact shape, startup logs, debug reports, plan-agent launch semantics, release-gate expectations, or
      user-facing command output except where a compatibility-preserving update is explicitly required by the refactor.
    - Do not make application-service, infrastructure, database, or migration changes.

## Gaps from prior iteration (mapped to evidence)

Fully implemented:

- Branch/source reconciliation is complete: source ref `origin/codex/reuse-cgc-worktree-context` resolves to
  `dc131e8461c70657c63e8faaea72f12a357de62e`, and `git merge-base HEAD origin/codex/reuse-cgc-worktree-context`
  returned that same commit.
- Architecture inventory exists at `docs/reference/python-engine-architecture.md` and is linked from
  `docs/reference/README.md`.
- Generated-worktree code-intelligence setup is extracted to
  `python/envctl_engine/planning/worktree_code_intelligence.py`.
- Worktree provenance, branch resolution, and active fresh-AI worktree protection helpers are extracted to
  `python/envctl_engine/planning/worktree_provenance.py`.
- Worktree git-hook policy resolution is extracted to `python/envctl_engine/planning/worktree_git_hooks.py`.
- Generated worktree `MAIN_TASK.md` seeding, plan archival, and numeric iteration gap selection are extracted to
  `python/envctl_engine/planning/worktree_main_task.py`.
- Project candidate discovery, cleanup, and sorting are extracted to
  `python/envctl_engine/planning/worktree_project_catalog.py`.
- Plan selection memory load/save and initial selected-count calculation are extracted to
  `python/envctl_engine/planning/worktree_selection_memory.py`.
- Generated-worktree shared-artifact compatibility links are extracted to
  `python/envctl_engine/planning/worktree_shared_artifacts.py`.
- Partial worktree-add recovery and placeholder fallback behavior are extracted to
  `python/envctl_engine/planning/worktree_creation_recovery.py`.
- Fresh-AI plan-count adjustment, launch transport selection, and keep-plan flag/config parsing are extracted to
  `python/envctl_engine/planning/worktree_plan_selection.py`.
- Plan selector resolution, dry-run prediction, no-TTY/no-plan handling, and sync result mapping are extracted to
  `python/envctl_engine/planning/worktree_plan_project_selection.py`.
- Interactive plan-count prompt seeding and memory persistence decisions are extracted to
  `python/envctl_engine/planning/worktree_prompt_selection.py`.
- Git worktree-add branch naming, branch existence checks, start-point selection, and command execution are extracted to
  `python/envctl_engine/planning/worktree_creation_commands.py`.
- Generated-worktree project and branch identity is centralized in
  `python/envctl_engine/planning/worktree_identity.py`.
- Interactive planning menu invocation, result normalization, fallback behavior, and terminal-state cleanup are
  extracted to `python/envctl_engine/planning/worktree_planning_menu.py`.
- Setup flag parsing, include-token resolution, and single/multi setup-entry application are extracted to
  `python/envctl_engine/planning/worktree_setup_entries.py`.
- Spinner-wrapped setup-worktree selection coordination is extracted to
  `python/envctl_engine/planning/worktree_setup_coordinator.py`.
- Excess plan-worktree deletion ordering, fresh-AI protection skips, blast cleanup warnings, and delete failure
  propagation are extracted to `python/envctl_engine/planning/worktree_sync_deletion.py`.
- Plan-count sync aggregation, single-plan create/delete decisions, and deletion result summarization are extracted to
  `python/envctl_engine/planning/worktree_sync_orchestration.py`.
- Runtime action command entry-point wrappers, passthrough selector parsing, service-name-to-project-name compatibility
  mapping, action env/replacement handoff, and project action delegation are extracted to
  `python/envctl_engine/runtime/engine_runtime_action_support.py`.
- Runtime help rendering, config command handoff, hook migration command handoff, and unsupported-command output are
  extracted to `python/envctl_engine/runtime/engine_runtime_cli_support.py`.
- Runtime doctor handoff, readiness-gate handoff, release shipability evaluation, doctor test policy, and runtime
  readiness contract enforcement are extracted to `python/envctl_engine/runtime/engine_runtime_doctor_support.py`.
- Runtime legacy lock compatibility, emit-listener registration, and per-project startup warning bookkeeping are
  extracted to `python/envctl_engine/runtime/engine_runtime_bookkeeping_support.py`.
- Runtime state artifact JSON helpers, synthetic-state detection, state-action handoff, strict mode lookup handoff,
  and port event forwarding are owned by `python/envctl_engine/runtime/engine_runtime_state_support.py`.
- Runtime dashboard command bridging, interactive command/input parsing, UI backend selection, target selection handoff,
  terminal command input, terminal-state restore, and interactive TTY detection are owned by
  `python/envctl_engine/runtime/engine_runtime_ui_bridge.py`.
- Runtime dispatch entry setup, process probe creation, effective route-mode event emission, debug-recorder
  configuration, and command-family dispatch are owned by
  `python/envctl_engine/runtime/engine_runtime_dispatch.py`.
- Action runtime compatibility facade behavior, including runtime collaborator lookup, legacy private-method fallback,
  state loading, emit forwarding, selectors, project discovery, command splitting, and worktree cleanup hooks, is owned
  by `python/envctl_engine/actions/action_runtime_facade.py`.
- Saved failed-test rerun planning, manifest loading and validation, invalid-selector reporting, non-rerunnable failure
  messaging, and extraction-failure detection are owned by
  `python/envctl_engine/actions/action_failed_rerun_support.py`, with `ActionCommandOrchestrator` retaining
  compatibility wrappers for existing dashboard/runtime callers.
- Action target context creation, service-target project expansion, selector resolution, all/untested/no-target policy,
  and targeted action execution are owned by `python/envctl_engine/actions/action_target_support.py`.
- Test action execution spec selection, test status rendering, test service-selection policy, parallel test policy,
  configured test command resolution, failed-only delegation, additional-service test delegation, legacy tree
  test-script detection, and frontend test path precedence are owned by
  `python/envctl_engine/actions/action_test_plan_support.py`, with `ActionCommandOrchestrator` retaining
  compatibility wrappers for existing dashboard/runtime callers.
- Additional-service test selection, service test command validation, service-specific cwd resolution, and per-target
  additional-service test execution specs are owned by
  `python/envctl_engine/actions/action_test_service_support.py`, with `ActionCommandOrchestrator` retaining
  compatibility wrappers for existing dashboard/runtime callers.
- Failed-test summary artifact rendering, failed-test collection, manifest entries, suite overview rendering, summary
  error-line formatting, traceback/captured-output extraction, suite display names, failed-only preservation, and test
  git-state fingerprints, test-summary artifact persistence, and per-run test-results directory allocation are owned by
  `python/envctl_engine/actions/action_test_summary_support.py`.
- Action command color enablement and ANSI style rendering for action/test terminal output are owned by
  `python/envctl_engine/actions/action_output_support.py`, with `ActionCommandOrchestrator` retaining compatibility
  wrappers for existing test-action output callers.
- Action command dispatch, target-resolution finish handling, action spinner lifecycle orchestration, interrupt finish
  events, and deferred post-action output execution are owned by
  `python/envctl_engine/actions/action_command_execution_support.py`, with `ActionCommandOrchestrator.execute`
  remaining the public compatibility entry point.
- Action command spinner status bridging, action spinner lifecycle update emission, and legacy `_emit` bridge
  restoration are owned by `python/envctl_engine/actions/action_spinner_support.py`, with
  `ActionCommandOrchestrator` retaining compatibility wrappers for existing dashboard/runtime callers.
- Worktree delete/blast execution and self-destruct worktree execution are owned by
  `python/envctl_engine/actions/action_worktree_runner.py`, including current-worktree target resolution,
  worktree-layout repo root detection, current-worktree validation, cleanup warning reporting, main-repo resolution
  handoff, and detached helper launch handoff.
- Migrate command resolution, migrate process execution handoff, migrate action outcome collection, failure
  headline/summary mapping, and deferred noninteractive result summaries are owned by
  `python/envctl_engine/actions/action_migrate_execution_support.py`, with `ActionCommandOrchestrator` retaining
  compatibility wrappers for existing dashboard/runtime callers.
- Migrate result records, backend-env hints, compact multi-project failure summaries, migrate failure headline
  selection, migrate requirements/context projection, migration failure log rendering, and report path display are owned by
  `python/envctl_engine/actions/action_migrate_support.py`, with
  `ActionCommandOrchestrator` retaining compatibility wrappers for existing dashboard/runtime callers.
- Project action replacements, base action environment construction, backend test env projection, migrate backend env
  contract metadata persistence, project action command resolution, streaming review execution policy, process-run
  wiring, targeted-action execution handoff, success/failure handler construction, project action success status,
  review artifact path parsing, failure report writing, and persisted project action report metadata are owned by
  `python/envctl_engine/actions/project_action_support.py`, with `ActionCommandOrchestrator` retaining compatibility
  wrappers for existing dashboard/runtime callers.
- Startup final run-state construction, preserved-service merge-event emission, project startup warning rendering and
  route-level warning output routing, restart port rebound summary text, plan dry-run preview text, final failure
  resolution/text, final failure status/context rendering, headless plan output gating, headless plan-session summary validation/printing/text,
  interactive plan-agent attach handoff, successful startup artifact/timing/snapshot/summary finalization,
  degraded plan-agent handoff artifact writing, and degraded plan-agent handoff terminal rendering/summary text are owned by
  `python/envctl_engine/startup/finalization.py`, with successful/failure/degraded finalization wired directly from
  `StartupOrchestrator` without startup finalization pass-through wrappers. Unused finalization compatibility wrappers for plan-session summary lines, failure status
  rendering, failure context labels, headless plan-output gating, and restart rebound summary printing have been removed
  from `StartupOrchestrator`; preserved-service merge emission and plan dry-run preview printing are now passed directly
  to finalization support; successful startup, disabled startup, and run-reuse now bind headless plan summary printing
  directly; degraded handoff terminal rendering is bound directly to finalization support; and remaining attach/headless
  summary, plan dry-run resolution, and project-warning rendering wrappers have been removed from `StartupOrchestrator`.
- Plan-agent dependency bootstrap, terminal launch execution, launch-state event emission, launch spinner text, launch failure
  policy/messages, validation/degradation decisions, stale attach-target degradation, local startup failure
  classification, degraded handoff session mutation, and degraded handoff warning/event emission are owned by
  `python/envctl_engine/startup/plan_agent_handoff.py`. Plan-agent dependency bootstrap, terminal launch, post-launch
  attach validation, launch-state emission, and launch failure handling are wired directly through plan-agent handoff
  support without a `StartupOrchestrator` sequence wrapper. The local-startup handoff degradation decision and
  sequence-level handoff validation are now wired directly from plan-agent handoff support without `StartupOrchestrator`
  pass-through wrappers. Unused plan-agent launch failure policy/message and launch-state event wrappers have been
  removed from `StartupOrchestrator`, along with unused launch spinner text, local startup failure classifier, handoff
  validation-required, stale-handoff recording, launch-spinner, and plan-agent launch sequence wrappers.
- Configured backend/frontend service-type resolution for a runtime mode is owned by
  `python/envctl_engine/startup/service_bootstrap_domain.py`. Disabled startup, run reuse, and fresh-start replacement
  paths now bind `configured_service_types_for_mode` directly from service bootstrap support without a
  `StartupOrchestrator` pass-through wrapper.
- Plan debug orch-group parsing, dashboard stopped-service restore metadata parsing/removal, dashboard stopped-service
  restore route/session/event preparation, fresh-start replacement service selection, and fresh-start existing-service
  termination handoff are owned by `python/envctl_engine/startup/run_reuse_support.py`. Dashboard stopped-service restore,
  fresh-start replacement service selection, and existing-service replacement are now bound directly to run-reuse support
  without `StartupOrchestrator` pass-through wrappers, and unused dashboard stopped-service static pass-through wrappers
  have been removed from `StartupOrchestrator`.
- Trees start selection requirements, interactive trees project selection, plan-backed preselection, and restart
  requirement inclusion policy are owned by `python/envctl_engine/startup/startup_selection_support.py`, with
  tree-selection requirement/project-selection helpers wired directly into context selection and restart selection helpers
  wired directly into requirement/service startup without `StartupOrchestrator` pass-through methods. Service startup now
  resolves the process runtime directly from runtime context instead of through a `StartupOrchestrator` process-runtime
  pass-through method. Docker prewarm remains owned by requirements execution and is wired into execution preparation
  without a `StartupOrchestrator` prewarm pass-through method. Restart requirement reuse remains owned by requirements
  execution without a `StartupOrchestrator` restart-requirements pass-through method. Startup finalization now calls the
  requirements timing, progress reporting, progress-suppression, and timing-suppression helpers directly without
  `StartupOrchestrator` pass-through methods.
- Startup project discovery/selection orchestration, explicit project filtering, duplicate selection handling,
  project-selection phase/snapshot emission, empty-selection messaging, and plan-agent worktree recovery after plan
  selection are owned by `python/envctl_engine/startup/context_selection.py`, with startup plan-handoff snapshot emission
  owned by `python/envctl_engine/ui/debug_snapshot.py`; context selection and restart-port application are wired directly
  without `StartupOrchestrator` pass-through wrappers.
- Selected-context startup execution, spinner policy/lifecycle emission, parallel/sequential project startup dispatch,
  project startup result recording, per-project warning rendering handoff, and plan-agent degraded local-startup
  handling are owned by `python/envctl_engine/startup/selected_context_startup.py`. The selected-context sequence,
  result-recording, degraded-local-startup mutation helpers, and runtime-bound selected-context startup helper are now
  wired directly from their owner modules instead of through `StartupOrchestrator` pass-through methods.
- Post-start strict truth reconciliation, degraded plan-agent handoff reconciliation skips, `state.reconcile` event
  emission, strict-truth failure marking, and degraded-service error construction are owned by
  `python/envctl_engine/startup/post_start_reconcile.py` without a `StartupOrchestrator` pass-through wrapper.
- Startup session creation, run-id resolution, run/session identifier announcement, startup hook contract validation,
  mode-toggle validation, runtime readiness gate emission, and generic startup phase event emission are owned by
  `python/envctl_engine/startup/session_lifecycle.py`. Generic `startup.phase` emission, startup route contract
  session creation, validation, run-id creation, resolved run-id lookup, and run/session identifier announcement are now wired directly from session lifecycle support without `StartupOrchestrator`
  pass-through methods.
- Startup run-reuse phase orchestration, run-reuse event emission, exact/subset resume handoff, reuse-expand metadata
  preservation, dashboard-resume finalization, planning-PR action handoff, and startup branch-entry snapshots are owned
  by `python/envctl_engine/startup/run_reuse_resolution.py` and are wired directly without a `StartupOrchestrator`
  sequence wrapper.
- Disabled startup dashboard-state finalization, artifact writes, plan-agent handoff validation, disabled plan messaging,
  headless plan summary handoff, plan-agent attach handoff, and interactive dashboard entry are owned by
  `python/envctl_engine/startup/disabled_startup_resolution.py` and are wired directly without a `StartupOrchestrator`
  sequence wrapper.
- Docker prewarm execution preparation and `docker_prewarm` phase emission are owned by
  `python/envctl_engine/startup/execution_preparation.py` and wired through its runtime-bound helper without a
  `StartupOrchestrator` pass-through wrapper.
- Successful startup finalization, final artifact writes, timing summary routing, startup breakdown emission,
  dashboard summary/status output, plan dry-run preview output, restart port rebound summary output,
  before-dashboard-entry snapshots, headless summary handoff, plan-agent attach handoff, and interactive dashboard entry are owned by
  `python/envctl_engine/startup/finalization.py`, without a `StartupOrchestrator` sequence-level wrapper.
- Failed startup finalization, startup failure event emission, started-service cleanup, port session release, failure
  artifact writes, and rendered final failure status output are owned by `python/envctl_engine/startup/finalization.py`,
  without a `StartupOrchestrator` pass-through wrapper.
- Degraded plan-agent handoff finalization, degraded artifact writes, degraded handoff rendering, headless output-only
  handling, plan-agent terminal attach handoff, and degraded handoff terminal path-link formatting are owned by
  `python/envctl_engine/startup/finalization.py` without a `StartupOrchestrator` pass-through wrapper.
- Restart pre-stop phase orchestration, spinner lifecycle emission, state lookup/fallback, selection policy, route
  conversion, service/requirement preservation policy, restart port assignment mapping/application, orphan-listener scan
  planning, orphan-listener PID/cwd matching, and matched listener termination/release policy are owned by
  `python/envctl_engine/startup/restart_prestop_support.py`; restart pre-stop, restart-port, orphan-listener process
  lookup, and runtime-bound orphan termination/release are wired directly without `StartupOrchestrator` pass-through
  wrappers.
- Structure guards exist in `tests/python/shared/test_structure_layout.py` for the planning owner modules.
- Focused planning tests exist for `worktree_git_hooks.py`, `worktree_main_task.py`, and
  `worktree_creation_commands.py`, `worktree_creation_recovery.py`, `worktree_identity.py`,
  `worktree_plan_project_selection.py`,
  `worktree_plan_selection.py`,
  `worktree_planning_menu.py`, `worktree_project_catalog.py`, `worktree_prompt_selection.py`,
  `worktree_selection_memory.py`, and
  `worktree_setup_coordinator.py`, `worktree_setup_entries.py`, `worktree_sync_deletion.py`,
  `worktree_sync_orchestration.py`, and `worktree_shared_artifacts.py`.
- Focused runtime action support tests exist in `tests/python/runtime/test_engine_runtime_action_support.py`, with a
  structure guard for `engine_runtime_action_support.py`.
- Focused runtime CLI support tests exist in `tests/python/runtime/test_engine_runtime_cli_support.py`, with a
  structure guard for `engine_runtime_cli_support.py`.
- Focused runtime doctor support tests exist in `tests/python/runtime/test_engine_runtime_doctor_support.py`, with a
  structure guard for `engine_runtime_doctor_support.py`.
- Focused runtime bookkeeping support tests exist in `tests/python/runtime/test_engine_runtime_bookkeeping_support.py`,
  with a structure guard for `engine_runtime_bookkeeping_support.py`.
- Focused runtime state support tests in `tests/python/runtime/test_engine_runtime_state_support.py` cover state-action
  handoff, strict mode lookup handoff, synthetic-state detection, state artifact JSON, and port event forwarding.
- Most recent reported validation:
  - `uv run --extra dev pytest -q tests/python/planning/test_worktree_main_task.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_worktree_main_task_has_owned_module`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/planning/test_worktree_selection_memory.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_worktree_selection_memory_has_owned_module`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/planning tests/python/shared/test_structure_layout.py tests/python/startup/test_support_module_decoupling.py tests/python/shared/test_utility_consolidation_contract.py`
    -> `331 passed, 28 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/planning tests/python/planning tests/python/shared/test_structure_layout.py docs/reference/README.md docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_action_support.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_engine_runtime_action_support_has_owned_module`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_action_support.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_dispatch.py tests/python/shared/test_structure_layout.py`
    -> `124 passed, 59 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/runtime/engine_runtime.py python/envctl_engine/runtime/engine_runtime_action_support.py tests/python/runtime/test_engine_runtime_action_support.py tests/python/shared/test_structure_layout.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/runtime tests/python/runtime/test_runtime_feature_inventory.py`
    -> `868 passed, 15 skipped, 259 subtests passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_cli_support.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_engine_runtime_cli_support_has_owned_module`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_cli_support.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_dispatch.py tests/python/runtime/test_command_exit_codes.py tests/python/shared/test_structure_layout.py`
    -> `164 passed, 59 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/runtime/engine_runtime.py python/envctl_engine/runtime/engine_runtime_cli_support.py tests/python/runtime/test_engine_runtime_cli_support.py tests/python/shared/test_structure_layout.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/runtime tests/python/runtime/test_runtime_feature_inventory.py`
    -> `873 passed, 15 skipped, 259 subtests passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_doctor_support.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_engine_runtime_doctor_support_has_owned_module`
    -> `5 passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_doctor_support.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_release_shipability_gate.py tests/python/runtime/test_release_shipability_gate_cli.py tests/python/shared/test_structure_layout.py`
    -> `139 passed, 59 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/runtime/engine_runtime.py python/envctl_engine/runtime/engine_runtime_doctor_support.py tests/python/runtime/test_engine_runtime_doctor_support.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/shared/test_structure_layout.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/runtime tests/python/runtime/test_runtime_feature_inventory.py`
    -> `877 passed, 15 skipped, 259 subtests passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_bookkeeping_support.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_engine_runtime_bookkeeping_support_has_owned_module`
    -> `5 passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_bookkeeping_support.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_event_support.py tests/python/startup/test_support_module_decoupling.py tests/python/shared/test_structure_layout.py`
    -> `145 passed, 59 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/runtime/engine_runtime.py python/envctl_engine/runtime/engine_runtime_bookkeeping_support.py tests/python/runtime/test_engine_runtime_bookkeeping_support.py tests/python/shared/test_structure_layout.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/runtime tests/python/runtime/test_runtime_feature_inventory.py`
    -> `881 passed, 15 skipped, 259 subtests passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_state_support.py`
    -> `5 passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_state_support.py tests/python/runtime/test_engine_runtime_state_lookup.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/state/test_state_action_orchestrator_logs.py`
    -> `119 passed, 56 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/runtime/engine_runtime.py python/envctl_engine/runtime/engine_runtime_state_support.py tests/python/runtime/test_engine_runtime_state_support.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/runtime tests/python/runtime/test_runtime_feature_inventory.py`
    -> `883 passed, 15 skipped, 259 subtests passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py`
    -> `3 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `32 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k selected_context_pass_through_wrappers`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_record_project_startup`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k selected_context_pass_through_wrappers`
    -> `1 passed, 18 deselected` after removing selected-context pass-through wrappers.
  - `uv run --extra dev pytest -q tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_support_module_decoupling.py -k 'record_project_startup or local_startup_failure or degrade or plan_agent or startup_finalization or selected_context_pass_through_wrappers'`
    -> `30 passed, 35 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/selected_context_startup.py python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k tree_selection_pass_through_wrappers`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_trees_start_selection_required`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k tree_selection_pass_through_wrappers`
    -> `1 passed, 19 deselected` after removing tree-selection pass-through wrappers.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_selection_support.py tests/python/startup/test_startup_trees_selection.py tests/python/startup/test_support_module_decoupling.py -k 'trees_start_selection_required or select_start_tree_projects or tree_preselected_projects or tree_selection_pass_through_wrappers'`
    -> `10 passed, 19 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_selection_support.py tests/python/startup/test_startup_trees_selection.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_orchestrator_flow.py -k 'trees_start_selection_required or select_start_tree_projects or tree_preselected_projects or tree_selection_pass_through_wrappers or project_selection or plan_agent_worktrees or disabled_startup or run_reuse'`
    -> `15 passed, 43 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_selection_support.py tests/python/startup/test_startup_trees_selection.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> initially surfaced two reuse-expand failures after the tree-selection wiring change, then `58 passed` after preserving reuse-expand start-only-new-context behavior and fresh failure run ids.
  - `uv run --extra dev ruff check python/envctl_engine/startup/context_selection.py python/envctl_engine/startup/startup_selection_support.py python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/run_reuse_resolution.py tests/python/startup/test_startup_selection_support.py tests/python/startup/test_startup_trees_selection.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k process_runtime_pass_through_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_process_runtime`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k process_runtime_pass_through_wrapper`
    -> `1 passed, 20 deselected` after removing the process-runtime pass-through wrapper.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/runtime/test_runtime_context_protocols.py -k 'process_runtime or start_project_services or support_reexports or process_runtime_pass_through_wrapper'`
    -> initially surfaced service-start fixture gaps after the helper started using runtime context directly, then `6 passed, 21 deselected` after moving fixture process runtime onto the runtime object.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_service_bootstrap_domain.py tests/python/runtime/test_runtime_context_protocols.py`
    -> `63 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/service_execution.py python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/protocols.py python/envctl_engine/startup/startup_selection_support.py tests/python/startup/test_support_module_decoupling.py tests/python/runtime/test_runtime_context_protocols.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k restart_selection_pass_through_wrappers`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_restart_include_requirements`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k restart_selection_pass_through_wrappers`
    -> `1 passed, 21 deselected` after removing restart-selection pass-through wrappers.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_profiles.py -k 'restart_service_types or restart_requirements or runtime_scope_flags or startup_only_flags'`
    -> `5 passed, 16 deselected` after moving assertions to startup selection support helpers.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_profiles.py tests/python/startup/test_startup_selection_support.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_restart_prestop_support.py tests/python/startup/test_run_reuse_support.py -k 'restart_service_types or restart_requirements or runtime_scope_flags or startup_only_flags or restart_selection_pass_through_wrappers or start_project_services or restart_include_requirements'`
    -> `11 passed, 66 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_profiles.py tests/python/startup/test_startup_selection_support.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_service_bootstrap_domain.py`
    -> `84 passed, 8 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/service_execution.py python/envctl_engine/startup/requirements_execution.py python/envctl_engine/startup/protocols.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_orchestrator_profiles.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_selection_support.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k prewarm_pass_through_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_maybe_prewarm_docker`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k prewarm_pass_through_wrapper`
    -> `1 passed, 22 deselected` after removing the prewarm pass-through wrapper.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_prewarm.py tests/python/startup/test_support_module_decoupling.py -k 'prewarm or prewarm_pass_through_wrapper'`
    -> `5 passed, 21 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_prewarm.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_support_module_decoupling.py -k 'prewarm or execution_preparation or prewarm_pass_through_wrapper'`
    -> `6 passed, 21 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_prewarm.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_support_module_decoupling.py`
    -> `27 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/requirements_execution.py tests/python/startup/test_startup_orchestrator_prewarm.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k prepare_execution_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_prepare_execution`; after
    binding startup execution preparation directly in the startup sequence, `1 passed, 41 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_execution_preparation.py`
    -> `1 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_prewarm.py tests/python/startup/test_startup_orchestrator_flow.py -k 'prewarm or startup_branch_enter or plan_agent'`
    -> `16 passed, 16 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_orchestrator_prewarm.py tests/python/startup/test_startup_orchestrator_flow.py -k 'prepare_execution_wrapper or prepare_startup_execution or prewarm or startup_branch_enter or plan_agent'`
    -> `23 passed, 52 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_orchestrator_prewarm.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `75 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/execution_preparation.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_orchestrator_prewarm.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k restart_requirements_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_requirements_for_restart_context`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k restart_requirements_wrapper`
    -> `1 passed, 28 deselected` after removing the unused restart-requirements pass-through wrapper.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_orchestrator_profiles.py tests/python/startup/test_startup_execution_preparation.py -k 'restart_requirements_wrapper or requirements_for_restart_context or restart_requirements or runtime_scope_flags or startup_only_flags'`
    -> `4 passed, 47 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_orchestrator_profiles.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_orchestrator_prewarm.py`
    -> `54 passed, 8 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k requirements_timing_pass_through_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_requirements_timing_enabled`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k requirements_timing_pass_through_wrapper`
    -> `1 passed, 23 deselected` after removing the requirements-timing pass-through wrapper.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'requirements_timing or requirements_timing_pass_through_wrapper or startup_finalization or print_startup_summary'`
    -> `30 passed, 52 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k suppress_timing_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_suppress_timing_output`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k suppress_timing_wrapper`
    -> `1 passed, 29 deselected` after binding timing suppression directly to startup progress support.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'suppress_timing_wrapper or requirements_timing or startup_finalization or print_startup_summary'`
    -> `31 passed, 57 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `88 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k suppress_progress_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_suppress_progress_output`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k suppress_progress_wrapper`
    -> `1 passed, 30 deselected` after binding progress suppression directly to startup progress support.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_restart_prestop_support.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'suppress_progress_wrapper or suppress_progress or restart_prestop or render_project_startup_warnings or startup_finalization or launch_plan_agent_terminals_with_spinner'`
    -> `49 passed, 72 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_restart_prestop_support.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `121 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k report_progress_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_report_progress`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k report_progress_wrapper`
    -> `1 passed, 31 deselected` after threading explicit progress callbacks through startup execution support.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_spinner_integration.py -k 'report_progress_wrapper or prepare_plan_agent_dependencies_for_launch or dependency_bootstrap or replace_existing_services or fresh_start_replacement or fingerprint_mismatch or spinner_policy or project_warning or shared_tree_requirements'`
    -> `10 passed, 63 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_spinner_integration.py`
    -> `73 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/startup_execution_support.py python/envctl_engine/startup/requirements_execution.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k process_cwd_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_process_cwd`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k process_cwd_wrapper`
    -> `1 passed, 32 deselected` after moving process cwd lookup into restart pre-stop support.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_restart_prestop_support.py tests/python/startup/test_startup_orchestrator_flow.py -k 'process_cwd_wrapper or orphan_listener or restart_prestop or terminate_restart_orphan'`
    -> `19 passed, 61 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_restart_prestop_support.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `80 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k restart_orphan_listener_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_terminate_restart_orphan_listeners`, then `1 passed, 53 deselected` after moving runtime-bound orphan listener termination into restart pre-stop support.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_restart_prestop_support.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `112 passed` for restart pre-stop, run-reuse replacement, and orchestrator flow coverage.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k plan_agent_launch_sequence_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_prepare_and_launch_plan_agent_worktrees`, then `1 passed, 54 deselected` after moving the launch lifecycle into plan-agent handoff support.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py -k 'prepare_and_launch_plan_agent_worktrees or prepare_plan_agent_dependencies_for_launch'`
    -> `3 passed, 15 deselected` for the plan-agent launch owner lifecycle and dependency bootstrap coverage.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `102 passed` for plan-agent handoff, launch, and orchestrator flow coverage.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k disabled_startup_resolution_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_resolve_disabled_startup_mode`, then `1 passed, 55 deselected` after moving runtime-bound disabled startup resolution into the owner module.
  - `uv run --extra dev pytest -q tests/python/startup/test_disabled_startup_resolution.py -k 'runtime_bound or disabled_startup'`
    -> `3 passed` for disabled startup owner coverage, including the runtime-bound helper.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `117 passed` for disabled startup, finalization, and orchestrator flow coverage.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k run_reuse_resolution_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_resolve_run_reuse`, then `1 passed, 56 deselected` after moving runtime-bound run-reuse resolution into the owner module.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_run_reuse_resolution.py -k 'runtime_bound or planning_prs or fresh_run'`
    -> `3 passed` for run-reuse owner coverage, including the runtime-bound helper.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `100 passed` for run-reuse, run-reuse support, and orchestrator flow coverage.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/restart_prestop_support.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k plan_dry_run_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_resolve_plan_dry_run`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k plan_dry_run_wrapper`
    -> `1 passed, 33 deselected` after moving plan dry-run resolution into finalization support.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'plan_dry_run_wrapper or dry_run or plan_dry_run or startup_branch_enter'`
    -> `4 passed, 88 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `92 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/finalization.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k emit_snapshot_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_emit_snapshot`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k emit_snapshot_wrapper`
    -> `1 passed, 34 deselected` after moving startup snapshot emission into debug snapshot support.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_context_selection.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'emit_snapshot_wrapper or plan_handoff.snapshot or debug_plan_snapshot or startup_branch_enter or auto_resume_evaluate or finalize_successful_startup'`
    -> `3 passed, 95 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_context_selection.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `98 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/ui/debug_snapshot.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_context_selection.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k emit_phase_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_emit_phase`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k emit_phase_wrapper`
    -> `1 passed, 35 deselected` after moving startup phase emission into session lifecycle support.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py -k 'emit_startup_phase or runtime_readiness_gate'`
    -> `2 passed, 2 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_startup_context_selection.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `103 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/session_lifecycle.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k strict_truth_reconcile_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_reconcile_strict_truth`; after binding post-start strict truth reconciliation directly to post-start reconcile
    support, `1 passed, 47 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_post_start_reconcile.py`
    -> `3 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py -k 'strict_truth or degraded_plan_agent_handoff or plan_agent'`
    -> `14 passed, 15 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_post_start_reconcile.py tests/python/startup/test_startup_orchestrator_flow.py -k 'strict_truth_reconcile_wrapper or reconcile_strict_truth_after_start or post_start_reconcile or strict_truth or degraded_plan_agent_handoff or plan_agent'`
    -> `21 passed, 59 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_post_start_reconcile.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `80 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/post_start_reconcile.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_post_start_reconcile.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k finalize_failure_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_finalize_failure`; after
    binding failure finalization directly to finalization support, `1 passed, 48 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k 'finalize_failed_startup or render_final_failure_status'`
    -> `3 passed, 26 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py -k 'failed or failure or strict_truth or plan_agent'`
    -> `19 passed, 10 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'finalize_failure_wrapper or finalize_failed_startup or render_final_failure_status or failed or failure or strict_truth or plan_agent'`
    -> `41 passed, 66 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `107 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/finalization.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k degraded_handoff_finalization_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_finalize_plan_agent_degraded_handoff`; after binding degraded handoff finalization directly to finalization
    support, `1 passed, 49 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k 'finalize_plan_agent_degraded_handoff or degraded_handoff'`
    -> `5 passed, 24 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py -k 'degraded_handoff or plan_agent'`
    -> `13 passed, 16 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'degraded_handoff_finalization_wrapper or finalize_plan_agent_degraded_handoff or degraded_handoff or plan_agent'`
    -> `26 passed, 82 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `108 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/finalization.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k run_id_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_ensure_run_id`; after
    binding run-id creation directly to session lifecycle support, `1 passed, 43 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py -k 'ensure_run_id or announce_session_identifiers or resolved_run_id'`
    -> `1 passed, 3 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'run_id or session_id or disabled_startup or finalize or plan_agent'`
    -> `32 passed, 28 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'run_id_wrapper or ensure_run_id or announce_session_identifiers or resolved_run_id or run_id or session_id or disabled_startup or finalize or plan_agent'`
    -> `37 passed, 71 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `108 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/session_lifecycle.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k resolved_run_id_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_resolved_run_id`; after
    binding resolved run-id lookup directly to session lifecycle support, `1 passed, 44 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py -k 'resolved_run_id or announce_session_identifiers'`
    -> `1 passed, 3 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_orchestrator_flow.py -k 'resolved_run_id or run_id or session_id or disabled_startup or selected_context or plan_agent'`
    -> `24 passed, 10 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_orchestrator_flow.py -k 'resolved_run_id_wrapper or resolved_run_id or announce_session_identifiers or run_id or session_id or disabled_startup or selected_context or plan_agent'`
    -> `31 passed, 52 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `83 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/session_lifecycle.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_selected_context_startup.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k announce_session_identifiers_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_announce_session_identifiers`; after binding run/session identifier announcement directly to session lifecycle
    support, `1 passed, 45 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py -k announce_session_identifiers`
    -> `1 passed, 3 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_orchestrator_flow.py -k 'announce or session_id or disabled_startup or run_reuse or auto_resume or plan_agent'`
    -> `32 passed, 12 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_orchestrator_flow.py -k 'announce_session_identifiers_wrapper or announce_session_identifiers or announce or session_id or disabled_startup or run_reuse or auto_resume or plan_agent'`
    -> `38 passed, 56 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `94 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/session_lifecycle.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_run_reuse_support.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k create_session_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained `_create_session`; after
    binding startup session creation directly to session lifecycle support, `1 passed, 46 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py -k create_startup_session`
    -> `1 passed, 3 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py -k 'startup_branch_enter or plan_agent'`
    -> `13 passed, 16 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_startup_orchestrator_flow.py -k 'create_session_wrapper or create_startup_session or startup_branch_enter or plan_agent'`
    -> `18 passed, 62 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `80 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/session_lifecycle.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k route_contract_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_validate_route_contract`; after binding startup route contract validation directly to session lifecycle support,
    `1 passed, 42 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py -k 'validate_startup_route_contract or runtime_readiness_gate'`
    -> `1 passed, 3 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py -k 'startup_branch_enter or plan_agent'`
    -> `13 passed, 16 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_startup_orchestrator_flow.py -k 'route_contract_wrapper or validate_startup_route_contract or runtime_readiness_gate or startup_branch_enter or plan_agent'`
    -> `18 passed, 58 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `76 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/session_lifecycle.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_session_lifecycle.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k configured_service_types_pass_through_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_configured_service_types_for_mode`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k configured_service_types_pass_through_wrapper`
    -> `1 passed, 24 deselected` after removing the configured-service-types pass-through wrapper.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_service_bootstrap_domain.py tests/python/startup/test_startup_orchestrator_flow.py -k 'configured_service_types or configured_service_types_pass_through_wrapper or disabled_startup or run_reuse or fresh_start_replacement'`
    -> `8 passed, 82 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_service_bootstrap_domain.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `90 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'should_fail_for_plan_agent_launch_result or plan_agent_launch_failure_message or emit_plan_agent_launch_state or plan_agent or startup_finalization'`
    -> `29 passed, 175 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'spinner or local_startup_failure_reason or plan_agent or startup_finalization'`
    -> `27 passed, 16 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'plan_agent_handoff_validation_required or record_stale_plan_agent_handoff or validate_plan_agent_handoff or plan_agent or startup_finalization'`
    -> `29 passed, 175 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k plan_agent_handoff_decision_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_should_degrade_to_plan_agent_handoff`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k plan_agent_handoff_decision_wrapper`
    -> `1 passed, 36 deselected` after moving validated local-startup degradation decisions into plan-agent handoff support.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py -k 'validated_plan_agent_handoff or validate_plan_agent_handoff or should_degrade_to_plan_agent_handoff'`
    -> `3 passed, 13 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'plan_agent_handoff_decision_wrapper or validate_plan_agent_handoff or validated_plan_agent_handoff or local_startup_failure or stale_attach_target or plan_agent_handoff'`
    -> `21 passed, 61 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `82 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/plan_agent_handoff.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'maybe_attach_plan_agent_terminal or print_headless_plan_session_summary or disabled_startup or run_reuse or finalize_successful_startup or finalize_plan_agent_degraded_handoff or startup_finalization or degraded_handoff'`
    -> `35 passed, 184 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'render_plan_agent_degraded_handoff_for_terminal or finalize_plan_agent_degraded_handoff or degraded_handoff or startup_finalization'`
    -> `30 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed after wrapping the lambda expression.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'print_headless_plan_session_summary or maybe_attach_plan_agent_terminal or disabled_startup or run_reuse or headless_plan_session_summary or startup_finalization or degraded_handoff'`
    -> `35 passed, 184 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'print_headless_plan_session_summary or maybe_attach_plan_agent_terminal or finalize_successful_startup or headless_plan_session_summary or startup_finalization or degraded_handoff'`
    -> `30 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'print_plan_dry_run_preview or plan_dry_run or dry_run or disabled_startup or run_reuse or startup_finalization'`
    -> `34 passed, 185 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'emit_preserved_service_merge or finalize_successful_startup or startup_finalization or preserved'`
    -> `29 passed, 29 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/startup/test_startup_spinner_integration.py -k 'print_restart_port_rebound_summary or restart_port_rebound or finalize_successful_startup or startup_finalization or restart'`
    -> `38 passed, 36 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'headless_plan_output_only or announce_session_identifiers or disabled_startup or run_reuse or startup_finalization or degraded_handoff'`
    -> `35 passed, 184 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py tests/python/runtime/test_engine_runtime_port_reservation_failures.py -k 'finalize_failed_startup or failure_context_label or render_final_failure_status or plan_session_summary_lines or headless_plan_session_summary or degraded_handoff or startup_finalization or port_reservation'`
    -> `31 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k finalize_plan_agent_degraded_handoff`
    -> `2 passed, 27 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'finalize_plan_agent_degraded_handoff or degraded_handoff or startup_finalization'`
    -> `30 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k headless_plan_output_only`
    -> initially failed for the expected missing extracted function, then passed with `1 passed, 27 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'headless_plan_output_only or headless_plan_session_summary or startup_finalization or degraded_handoff'`
    -> `29 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k render_plan_agent_degraded_handoff_for_terminal`
    -> `1 passed, 26 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'render_plan_agent_degraded_handoff_for_terminal or degraded_handoff or startup_finalization'`
    -> `28 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k render_project_startup_warnings_for_route`
    -> `1 passed, 25 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_orchestrator_flow.py -k 'render_project_startup_warnings or warning or warnings or startup_finalization'`
    -> `26 passed, 32 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k project_warning_render_pass_through_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_render_project_startup_warnings`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k project_warning_render_pass_through_wrapper`
    -> `1 passed, 25 deselected` after binding project-warning rendering directly to finalization support.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'project_warning_render or render_project_startup_warnings or startup_finalization or start_selected_contexts'`
    -> `30 passed, 54 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `84 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k maybe_attach_plan_agent_terminal`
    -> initially failed for the expected missing extracted function, then passed with `3 passed, 22 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'maybe_attach_plan_agent_terminal or print_headless_plan_session_summary or headless_plan_session_summary or startup_finalization or degraded_handoff'`
    -> `26 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py`
    -> `3 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_startup_session_lifecycle_has_owned_module`
    -> `4 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_session_lifecycle.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_cutover_gate_truth.py -k 'session_lifecycle or runtime_readiness_gate or strict_runtime_readiness or disabled_startup or startup_hook'`
    -> `8 passed, 31 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/session_lifecycle.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_session_lifecycle.py tests/python/shared/test_structure_layout.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_orchestrator_flow.py -k 'run_reuse or auto_resume or dashboard_resume or planning_prs or startup_branch_enter'`
    -> `9 passed, 29 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_run_reuse_resolution.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_startup_run_reuse_resolution_has_owned_module`
    -> `3 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'run_reuse or auto_resume or dashboard_resume or planning_prs or startup_branch_enter'`
    -> `20 passed, 179 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/run_reuse_resolution.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/shared/test_structure_layout.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_disabled_startup_resolution.py`
    -> initially failed for the expected missing module, then `2 passed` after implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_disabled_startup_resolution.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_lifecycle_parity.py -k 'disabled_startup or runs_are_disabled or plan_launch_hook_runs_before_disabled_startup_dashboard_write or plan_agent_dependency_bootstrap_runs_before_disabled_startup_launch'`
    -> `11 passed, 75 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_disabled_startup_resolution.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_disabled_startup_resolution_has_owned_module`
    -> `3 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/disabled_startup_resolution.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_disabled_startup_resolution.py tests/python/shared/test_structure_layout.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py`
    -> `4 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_spinner_integration.py -k 'restart or prestop or preserves_other_services'`
    -> `9 passed, 7 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py`
    -> `8 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/restart_prestop_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_restart_prestop_support.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'startup_execution or parallel_startup_execution or plan_mode_defaults_to_parallel or no_parallel_trees or start_trees_env_false or selected_context or local_startup_failure or plan_agent'`
    -> `21 passed, 171 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/selected_context_startup.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_selected_context_startup.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_post_start_reconcile.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_post_start_reconcile_has_owned_module`
    -> `4 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_post_start_reconcile.py tests/python/startup/test_startup_orchestrator_flow.py -k 'strict_truth or post_start_reconcile or degraded_plan_agent_handoff'`
    -> `5 passed, 27 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/post_start_reconcile.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_post_start_reconcile.py tests/python/shared/test_structure_layout.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py -k matching`
    -> `1 passed, 8 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py`
    -> `9 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_spinner_integration.py -k 'restart or prestop or preserves_other_services'`
    -> `9 passed, 7 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/restart_prestop_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_restart_prestop_support.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py -k handle_restart_prestop`
    -> initially failed for the expected missing extracted function, then `3 passed, 15 deselected` after implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py`
    -> `18 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py tests/python/startup/test_startup_spinner_integration.py -k 'restart or prestop or preserves_other_services'`
    -> `27 passed, 7 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/restart_prestop_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_restart_prestop_support.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_execution_preparation.py`
    -> initially failed for the expected missing module, then `1 passed` after implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_orchestrator_prewarm.py`
    -> `4 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_execution_preparation.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_startup_execution_preparation_has_owned_module`
    -> `2 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/execution_preparation.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_execution_preparation.py tests/python/shared/test_structure_layout.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k finalize_successful_startup`
    -> `2 passed, 11 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'finalize_successful_startup or startup_finalization or before_dashboard_entry or headless_plan_session_summary or startup_breakdown or dashboard_summary_or_status'`
    -> `13 passed, 190 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k finalize_failed_startup`
    -> initially failed for the expected missing extracted function, then `2 passed, 13 deselected` after
    implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py tests/python/runtime/test_engine_runtime_port_reservation_failures.py -k 'finalize_failed_startup or finalize_successful_startup or startup_finalization or before_dashboard_entry or headless_plan_session_summary or startup_breakdown or dashboard_summary_or_status or port_reservation'`
    -> `16 passed, 190 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k finalize_plan_agent_degraded_handoff`
    -> initially failed for the expected missing extracted function, then `1 passed, 15 deselected` after
    implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k 'finalize_plan_agent_degraded_handoff or finalize_failed_startup or finalize_successful_startup'`
    -> `5 passed, 11 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py tests/python/runtime/test_engine_runtime_port_reservation_failures.py -k 'finalize_plan_agent_degraded_handoff or finalize_failed_startup or finalize_successful_startup or startup_finalization or before_dashboard_entry or headless_plan_session_summary or startup_breakdown or dashboard_summary_or_status or port_reservation or degraded_handoff'`
    -> `18 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py -k prepare_dashboard_stopped_service_restore`
    -> initially failed for the expected missing extracted function, then `2 passed, 7 deselected` after
    implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_spinner_integration.py -k 'dashboard_stopped_services or restore_stopped_services or run_reuse'`
    -> `12 passed, 15 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/run_reuse_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_run_reuse_support.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py -k replace_existing_project_services_for_fresh_start`
    -> initially failed for the expected missing extracted function, then `2 passed, 9 deselected` after
    implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py -k 'replace_existing_project_services_for_fresh_start or fresh_start_replacement_services'`
    -> `4 passed, 7 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_spinner_integration.py -k 'dashboard_stopped_services or restore_stopped_services or replace_existing_services or fresh_start or run_reuse'`
    -> `14 passed, 15 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/run_reuse_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_run_reuse_support.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_selected_context_startup.py -k record_project_startup`
    -> initially failed for the expected missing extracted function, then `1 passed, 2 deselected` after
    implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'record_project_startup or selected_context or startup_execution'`
    -> `7 passed, 186 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/selected_context_startup.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_selected_context_startup.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k format_degraded_handoff_text_for_terminal`
    -> initially failed for the expected missing extracted function, then `1 passed, 16 deselected` after
    implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'format_degraded_handoff_text_for_terminal or degraded_handoff or startup_finalization'`
    -> `18 passed, 189 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k print_plan_dry_run_preview`
    -> initially failed for the expected missing extracted function, then `2 passed, 17 deselected` after
    implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'print_plan_dry_run_preview or plan_dry_run or dry_run or startup_finalization'`
    -> `19 passed, 190 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k print_restart_port_rebound_summary`
    -> initially failed for the expected missing extracted function, then `1 passed, 19 deselected` after
    implementation.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/startup/test_startup_spinner_integration.py -k 'print_restart_port_rebound_summary or restart_port_rebound or startup_finalization or restart'`
    -> `29 passed, 36 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py -k apply_restart_port_assignments`
    -> `1 passed, 9 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py`
    -> `10 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_spinner_integration.py -k 'restart or prestop or preserves_other_services'`
    -> `9 passed, 7 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/restart_prestop_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_restart_prestop_support.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py -k restart_prestop_selection`
    -> `1 passed, 10 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py`
    -> `11 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_spinner_integration.py -k 'restart or prestop or preserves_other_services'`
    -> `9 passed, 7 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/restart_prestop_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_restart_prestop_support.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py -k restart_prestop_state`
    -> `1 passed, 11 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py`
    -> `12 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_spinner_integration.py -k 'restart or prestop or preserves_other_services'`
    -> `9 passed, 7 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/restart_prestop_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_restart_prestop_support.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_spinner_integration.py -k 'restart or prestop or preserves_other_services'`
    -> `9 passed, 7 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py`
    -> `3 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'handoff or missing_service_start_command'`
    -> `8 passed, 24 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'handoff or plan_agent_launch_state or missing_service_start_command'`
    -> `9 passed, 24 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'handoff or plan_agent_launch_state or missing_service_start_command or launch_failed'`
    -> `13 passed, 23 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'handoff or plan_agent_launch_state or missing_service_start_command or launch_failed or launch_spinner'`
    -> `14 passed, 23 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/startup/test_startup_spinner_integration.py -k 'handoff or plan_agent_launch_state or missing_service_start_command or launch_failed or launch_spinner or plan_agent'`
    -> `24 passed, 31 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'handoff or stale_attach or attach_target_stale_after_launch or plan_agent_launch_state or missing_service_start_command or launch_failed or launch_spinner or plan_agent'`
    -> `26 passed, 14 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'handoff or stale_attach or attach_target_stale_after_launch or plan_agent_launch_state or missing_service_start_command or launch_failed or launch_spinner or plan_agent'`
    -> `28 passed, 14 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py -k prepare_plan_agent_dependencies_for_launch`
    -> `1 passed, 13 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py`
    -> `14 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py -k 'plan_agent or dependency_bootstrap or launch_state or handoff'`
    -> `14 passed, 15 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/plan_agent_handoff.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_service_bootstrap_domain.py -k configured_service_types_for_mode`
    -> `2 passed, 34 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py -k 'disabled_startup or configured_service_types'`
    -> `5 passed, 24 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/service_bootstrap_domain.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_service_bootstrap_domain.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py`
    -> `4 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_spinner_integration.py -k 'dashboard_stopped_services or restores_dashboard_stopped_services'`
    -> `1 passed, 15 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_spinner_integration.py -k 'fingerprint_mismatch or replace_existing_services or dashboard_stopped_services or restores_dashboard_stopped_services'`
    -> `2 passed, 14 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/run_reuse_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_run_reuse_support.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k fresh_start_replacement_services_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_fresh_start_replacement_services`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k fresh_start_replacement_services_wrapper`
    -> `1 passed, 26 deselected` after binding fresh-start replacement service selection directly to run-reuse support.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_spinner_integration.py tests/python/startup/test_support_module_decoupling.py -k 'fresh_start_replacement or replace_existing_services or fingerprint_mismatch or dashboard_stopped_services or restores_dashboard_stopped_services'`
    -> `7 passed, 47 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_spinner_integration.py tests/python/startup/test_support_module_decoupling.py`
    -> `54 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k run_reuse_replacement_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_replace_existing_project_services_for_fresh_start`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k run_reuse_replacement_wrapper`
    -> `1 passed, 37 deselected` after moving fresh-start existing-service replacement defaults into run-reuse support.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py -k 'replace_existing_project_services_for_fresh_start or fresh_start_replacement_services'`
    -> `4 passed, 7 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_orchestrator_flow.py -k 'run_reuse_replacement_wrapper or replace_existing_project_services_for_fresh_start or fresh_start_replacement or auto_resume or run_reuse'`
    -> `15 passed, 65 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `80 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/run_reuse_support.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_run_reuse_support.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k dashboard_stopped_restore_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_prepare_dashboard_stopped_service_restore`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k dashboard_stopped_restore_wrapper`
    -> `1 passed, 38 deselected` after binding dashboard stopped-service restore directly to run-reuse support.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py -k prepare_dashboard_stopped_service_restore`
    -> `2 passed, 9 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py::StartupOrchestratorFlowTests::test_interactive_plan_resume_exact_attaches_plan_agent_instead_of_dashboard tests/python/startup/test_startup_orchestrator_flow.py::StartupOrchestratorFlowTests::test_interactive_plan_opencode_without_tmux_launches_existing_worktree_and_attaches`
    -> `2 passed` after fixing positional/keyword binding for the direct callback.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_orchestrator_flow.py -k 'dashboard_stopped_restore_wrapper or prepare_dashboard_stopped_service_restore or dashboard_stopped_services or restores_dashboard_stopped_services or auto_resume or run_reuse'`
    -> `16 passed, 65 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_run_reuse_resolution.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `81 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/run_reuse_support.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_run_reuse_support.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k plan_agent_handoff_validation_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_validate_plan_agent_handoff`; after binding sequence-level validation directly to plan-agent handoff support,
    `1 passed, 39 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py -k 'validate_plan_agent_handoff or validated_plan_agent_handoff'`
    -> `2 passed, 14 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py -k 'validate_plan_agent_handoff or print_headless_plan_session_summary or maybe_attach_plan_agent_terminal or degraded_handoff or plan_agent'`
    -> `24 passed, 34 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `114 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/plan_agent_handoff.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k plan_agent_launch_spinner_wrapper`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_launch_plan_agent_terminals_with_spinner`; after binding launch spinner execution directly to plan-agent handoff
    support, `1 passed, 40 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_plan_agent_handoff.py -k launch_plan_agent_terminals_with_spinner`
    -> `1 passed, 15 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_orchestrator_flow.py -k 'plan_agent or launch'`
    -> `17 passed, 12 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py -k 'plan_agent_launch_spinner_wrapper or launch_plan_agent_terminals_with_spinner or plan_agent or launch'`
    -> `36 passed, 50 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `86 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/plan_agent_handoff.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_plan_agent_handoff.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k dashboard_stopped_services_static_wrappers`
    -> initially failed before implementation because `StartupOrchestrator` still retained
    `_dashboard_stopped_service_entries` and `_metadata_without_dashboard_stopped_services`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k dashboard_stopped_services_static_wrappers`
    -> `1 passed, 27 deselected` after removing the unused dashboard stopped-service static pass-through wrappers.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_spinner_integration.py tests/python/startup/test_support_module_decoupling.py`
    -> `55 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_support_module_decoupling.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py -k run_reuse_debug_orch_groups`
    -> `1 passed, 6 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_run_reuse_support.py tests/python/startup/test_startup_orchestrator_flow.py -k 'run_reuse_debug_orch_groups or run_reuse or startup_branch_enter'`
    -> `7 passed, 29 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/run_reuse_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_run_reuse_support.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_selection_support.py tests/python/shared/test_structure_layout.py::StructureLayoutTests::test_startup_selection_support_has_owned_module`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_selection_support.py tests/python/startup/test_startup_trees_selection.py tests/python/startup/test_startup_orchestrator_profiles.py -k 'selection or restart_requirements'`
    -> `10 passed, 20 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_context_selection.py`
    -> `3 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_context_selection.py tests/python/startup/test_startup_orchestrator_flow.py -k 'plan_agent or project_selection or duplicate or startup_branch_enter'`
    -> `15 passed, 17 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py -k 'apply_restart_ports_to_contexts or terminate_restart_orphan_listeners'`
    -> `3 passed, 12 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_restart_prestop_support.py tests/python/startup/test_startup_spinner_integration.py -k 'restart or prestop or preserves_other_services'`
    -> `24 passed, 7 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/restart_prestop_support.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_restart_prestop_support.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py`
    -> `5 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `34 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py`
    -> `6 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `35 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py`
    -> `7 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `36 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py`
    -> `8 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'dry_run or plan_dry_run'`
    -> `1 passed, 197 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py`
    -> `9 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `38 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py`
    -> `11 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/startup/test_startup_spinner_integration.py -k 'warning or warnings or startup_finalization'`
    -> `12 passed, 44 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k print_headless_plan_session_summary`
    -> `2 passed, 20 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/runtime/test_engine_runtime_real_startup.py -k 'print_headless_plan_session_summary or headless_plan_session_summary or startup_finalization'`
    -> `22 passed, 190 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/finalization.py python/envctl_engine/startup/startup_orchestrator.py tests/python/startup/test_startup_finalization.py docs/reference/python-engine-architecture.md`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k success_finalization_wrapper`
    -> failed before implementation because `StartupOrchestrator._finalize_success` still existed; passed after direct wiring with `1 passed, 57 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_finalization.py -k 'runtime_bound_success or finalize_successful_startup'`
    -> `3 passed, 27 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `117 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/finalization.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_selected_context_startup.py -k runtime_bound`
    -> failed before implementation because `start_selected_contexts_with_runtime` did not exist; passed after owner binding with `1 passed, 3 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k selected_context_startup_runtime_binding`
    -> `1 passed, 58 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_startup_execution_preparation.py -k runtime_bound`
    -> failed before implementation because `prepare_startup_execution_with_runtime` did not exist; passed after owner binding with `1 passed, 1 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `124 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/finalization.py python/envctl_engine/startup/selected_context_startup.py python/envctl_engine/startup/execution_preparation.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py -k lifecycle_owner`
    -> failed before implementation because `StartupOrchestrator.execute` still owned a broad startup sequence; passed after extracting `startup/lifecycle.py` with `1 passed, 59 deselected`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_startup_orchestrator_flow.py`
    -> `89 passed`.
  - `uv run --extra dev pytest -q tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/startup/test_startup_spinner_integration.py`
    -> `141 passed`.
  - `uv run --extra dev ruff check python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/lifecycle.py python/envctl_engine/startup/finalization.py python/envctl_engine/startup/selected_context_startup.py python/envctl_engine/startup/execution_preparation.py tests/python/startup/test_support_module_decoupling.py tests/python/startup/test_selected_context_startup.py tests/python/startup/test_startup_execution_preparation.py tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/startup/test_startup_spinner_integration.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/actions/test_actions_parity.py -k git_action_methods_delegate`
    -> failed before implementation because `run_pr_action`, `run_commit_action`, `run_ship_action`, and
    `run_review_action` still selected default commands inside `ActionCommandOrchestrator`; passed after extracting
    `actions/action_git_command_support.py` with `1 passed, 133 deselected`.
  - `uv run --extra dev pytest -q tests/python/actions/test_actions_parity.py -k 'git_actions_use_python_native_defaults_when_available or git_action_methods_delegate'`
    -> `2 passed, 132 deselected`.
  - `uv run --extra dev pytest -q tests/python/actions/test_actions_parity.py tests/python/actions/test_project_action_execution_support.py tests/python/actions/test_action_spinner_integration.py -k 'git_action or git_actions or pr_action or commit_action or ship_action or review_action or raw_command or missing_command or spinner'`
    -> `17 passed, 126 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/actions/action_command_orchestrator.py python/envctl_engine/actions/action_git_command_support.py tests/python/actions/test_actions_parity.py tests/python/actions/test_project_action_execution_support.py tests/python/actions/test_action_spinner_integration.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_command_orchestrator_targets.py -k project_action_handlers_delegate`
    -> failed before implementation because project action success/failure/result persistence binding still lived in
    `ActionCommandOrchestrator`; passed after extracting `actions/action_project_report_owner.py` with `1 passed, 14 deselected`.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_command_orchestrator_targets.py tests/python/actions/test_project_action_report_support.py tests/python/actions/test_actions_parity.py tests/python/actions/test_project_action_execution_support.py tests/python/actions/test_action_spinner_integration.py -k 'project_action_handler or pr_success_handler or review_success_handler or failure_handler or project_action_success or review_success_artifact or git_action or git_actions or pr_action or commit_action or ship_action or review_action or raw_command or missing_command or spinner'`
    -> `27 passed, 139 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/actions/action_command_orchestrator.py python/envctl_engine/actions/action_git_command_support.py python/envctl_engine/actions/action_project_report_owner.py tests/python/actions/test_actions_parity.py tests/python/actions/test_action_command_orchestrator_targets.py tests/python/actions/test_project_action_report_support.py tests/python/actions/test_project_action_execution_support.py tests/python/actions/test_action_spinner_integration.py`
    -> passed.
  - `git diff --check` -> passed.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_command_parity.py -k service_policy_and_command_methods_delegate_to_runtime_owners`
    -> passed after adding runtime facade guards with `1 passed, 89 deselected, 19 subtests passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_commands.py tests/python/runtime/test_engine_runtime_service_policy.py`
    -> initially exposed stale startup-selection helper call sites in runtime inspection support; passed after updating
    inspection/dashboard callers to the keyword-only startup owner contract with `102 passed, 80 subtests passed`.
  - `uv run --extra dev pytest -q tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_commands.py tests/python/runtime/test_engine_runtime_service_policy.py tests/python/runtime/test_engine_runtime_action_support.py tests/python/runtime/test_engine_runtime_env.py tests/python/runtime/test_engine_runtime_service_truth.py tests/python/ui/test_dashboard_orchestrator_restart_selector.py tests/python/startup/test_support_module_decoupling.py`
    -> `301 passed, 88 subtests passed`.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_command_orchestrator_targets.py -k test_plan_action_delegates_to_owner`
    -> failed before implementation because `action_test_plan_support.run_test_plan_action_for_targets` did not exist;
    passed after moving `test-focused` context binding into the action test-plan owner with `1 passed, 15 deselected`.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_test_plan_support.py -k run_test_plan_action_for_targets`
    -> passed after adding owner-level context/failure coverage with `1 passed, 8 deselected`.
  - `uv run --extra dev pytest -q tests/python/actions/test_actions_parity.py -k test_test_focused_without_project_infers_current_worktree`
    -> `1 passed, 133 deselected`.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_command_orchestrator_targets.py tests/python/actions/test_action_test_plan_support.py tests/python/actions/test_actions_parity.py -k 'test_plan_action or test_focused_without_project or build_test_execution_specs or test_service_selection or status_rendering or parallel_policy or spinner_policy'`
    -> `9 passed, 150 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/actions/action_command_orchestrator.py python/envctl_engine/actions/action_test_plan_support.py tests/python/actions/test_action_command_orchestrator_targets.py tests/python/actions/test_action_test_plan_support.py tests/python/actions/test_actions_parity.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_command_orchestrator_targets.py -k migrate_action_delegates_to_owner`
    -> failed before implementation because `run_migrate_action_with_owner` did not exist; passed after extracting the
    migrate orchestrator binding into the action migration execution owner with `1 passed, 16 deselected`.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_migrate_execution_support.py`
    -> passed, 3 passed.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_command_orchestrator_targets.py tests/python/actions/test_action_migrate_execution_support.py tests/python/actions/test_actions_parity.py -k 'migrate_action or test_migrate or migrate_execution or run_migrate'`
    -> `18 passed, 136 deselected`.
  - `uv run --extra dev ruff check python/envctl_engine/actions/action_command_orchestrator.py python/envctl_engine/actions/action_migrate_execution_support.py tests/python/actions/test_action_command_orchestrator_targets.py tests/python/actions/test_action_migrate_execution_support.py tests/python/actions/test_actions_parity.py`
    -> passed.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_command_orchestrator_targets.py -k test_execution_spec_methods_delegate_to_test_plan_owner`
    -> failed before implementation because `build_test_execution_specs_for_orchestrator` and
    `build_failed_test_execution_specs_for_orchestrator` did not exist; passed after extracting test execution spec
    construction into the action test-plan owner with `1 passed, 17 deselected`.
  - `uv run --extra dev pytest -q tests/python/actions/test_action_command_orchestrator_targets.py tests/python/actions/test_action_test_plan_support.py tests/python/actions/test_actions_parity.py tests/python/actions/test_action_failed_rerun_support.py tests/python/actions/test_action_test_service_support.py -k 'test_execution_spec or build_test_execution_specs or failed_flag or additional_service or test_service_selection or test_focused or test_action or failed_test'`
    -> `168 passed, 2 warnings, 6 subtests passed`.
  - `uv run --extra dev ruff check python/envctl_engine/actions/action_command_orchestrator.py python/envctl_engine/actions/action_test_plan_support.py tests/python/actions/test_action_command_orchestrator_targets.py tests/python/actions/test_action_test_plan_support.py tests/python/actions/test_actions_parity.py tests/python/actions/test_action_failed_rerun_support.py tests/python/actions/test_action_test_service_support.py`
    -> passed.

Partially implemented:

- Planning/worktree split has focused owners for the responsibilities named in requirement 1; `worktree_domain.py`
  remains a compatibility facade and still needs broader facade cleanup only as later refactor slices allow.
- Runtime support modules already exist under `runtime/engine_runtime_*_support.py`; action command entry-point wrappers,
  CLI/help handoff, doctor/release-gate handoff, runtime bookkeeping, state-action handoff, service policy, dashboard
  truth policy, and command-resolution wrappers now have focused runtime support owners guarded by facade tests. Runtime
  inspection/dashboard tree-preselection callers now use the keyword-only startup selection owner contract directly, but
  `runtime/engine_runtime.py` still owns many delegate-worthy responsibilities.
- Startup support modules already exist, and project warning rendering, restart rebound summaries, dry-run output,
  preserved-service merge events, plus final
  failure/headless-plan/degraded-handoff summary rendering, startup plan-handoff snapshot emission without a
  StartupOrchestrator pass-through wrapper, plan dry-run resolution without a StartupOrchestrator pass-through wrapper,
  project-warning rendering without a StartupOrchestrator
  pass-through wrapper, plan-agent launch execution/state/spinner text/failure policy/validation decisions/stale
  attach-target/local startup handoff degradation, launch spinner execution, plus sequence-level handoff validation without StartupOrchestrator
  pass-through wrappers, configured service-type resolution without a StartupOrchestrator
  pass-through wrapper, dashboard stopped-service restore metadata without unused StartupOrchestrator static wrappers,
  fresh-start replacement service selection without a StartupOrchestrator pass-through wrapper, and restart
  pre-stop route/preservation policy, restart port assignment mapping, restart requirement reuse without a
  StartupOrchestrator pass-through wrapper, progress reporting plus progress/timing suppression without
  StartupOrchestrator pass-through wrappers, startup session creation, startup route contract validation, run-id creation, resolved run-id lookup, run/session identifier announcement, and Docker prewarm execution preparation without StartupOrchestrator
  pass-through wrapper, orphan-listener process cwd lookup without a StartupOrchestrator
  pass-through wrapper, and orphan-listener scan planning plus runtime-bound orphan listener termination now have
  focused owners; post-start strict truth reconciliation and failure finalization are wired directly without
  StartupOrchestrator pass-through wrappers, degraded handoff finalization and successful startup finalization are wired directly without a
  StartupOrchestrator pass-through wrapper, context selection, restart-port application, selected-context startup
  execution, plan-agent launch lifecycle, disabled startup resolution, run-reuse resolution, and the high-level startup
  lifecycle sequence are wired through focused startup owner modules. `startup/startup_orchestrator.py` is now a thin
  facade for startup lifecycle execution and service-start compatibility methods, but the broader startup module family
  still has additional cleanup opportunities after adjacent runtime/action/requirements slices land.
- Actions have support modules, and target selection, test-focused context binding, test action execution spec selection,
  test status rendering,
  parallel test policy, failed-only rerun planning, additional-service test specs, failed-test summaries, summary
  error-line formatting, action command dispatch/spinner lifecycle orchestration, action spinner status bridging,
  project action env/replacements, project action command execution, PR/commit/ship/review default command selection,
  project action success/failure/result persistence binding, project action reports, migrate output/reporting,
  migrate failure headline selection, migrate
  requirements/context projection, plus worktree execution now have focused owners, and migrate command
  execution/failure outcome collection now has a focused owner, but
  `actions/action_command_orchestrator.py` is still broad and
  `tests/python/actions/test_actions_parity.py` is still about 6,869 lines.
- Architecture docs describe an ownership map, but they do not yet reflect final ownership boundaries for runtime,
  startup, actions, requirements, transports, dashboard, and remaining planning/worktree code.

Not implemented:

- `PythonEngineRuntime` has not been reduced to a thin facade.
- `StartupOrchestrator.execute` has been decomposed into `startup/lifecycle.py`; remaining startup cleanup is limited to
  follow-on owner-module refinement rather than the execute sequence itself.
- Action command orchestration and action parity tests have not been fully split by action owner.
- Plan-agent shared transport vocabulary and full option-matrix tests are not complete;
  `tests/python/planning/test_plan_agent_launch_support.py` is still about 7,415 lines.
- Supabase adapter decomposition is not complete; `requirements/supabase.py` is still about 3,348 lines.
- Dashboard orchestration/test split is not complete; `ui/dashboard/orchestrator.py` is still about 2,209 lines and
  `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` is still about 3,494 lines.
- Generated contract generation/compare pass, full Python test suite, release shipability gate, and final GitHub check
  confirmation have not been completed for the full refactor.

## Acceptance criteria (requirement-by-requirement)

- `planning/worktree_domain.py` is reduced to a documented compatibility facade and remaining planning/worktree
  responsibilities are owned by focused modules with targeted tests.
- `PythonEngineRuntime` is reduced to construction, dispatch, delegation, and compatibility wrappers, with runtime
  delegate tests covering route selection, exit statuses, and output shape.
- `StartupOrchestrator.execute` delegates to the startup lifecycle owner while lifecycle phases are delegated to focused
  startup/planning helpers with preserved degraded, disabled, resume, truth, and finalization behavior.
- `ActionCommandOrchestrator` remains the compatibility entry point while each action route delegates to action-owned
  helpers, and action tests are split without losing parity coverage.
- Plan-agent launch vocabulary is shared where behavior is common, transport-specific code remains transport-owned, and
  the full option matrix is covered by tests.
- Supabase adapter behavior is preserved behind smaller lifecycle/config/health/database/auth/repair/reporting pieces.
- Dashboard orchestration and restart-selector tests are split by behavior owner without changing UI behavior.
- Oversized tests are split only after corresponding production seams exist and existing assertions are preserved.
- Architecture docs, structure/import guards, and generated contracts reflect the final owner modules.
- Public CLI behavior, exit statuses, state artifacts, prompt install output, plan-agent launch behavior, generated
  contracts, release-gate behavior, startup logs, debug reports, and user-facing summaries are preserved.
- Targeted suites for each touched area pass, full Python tests pass, generated contract scripts have been run and
  compared, release shipability gate passes, and PR/GitHub check evidence is recorded.

## Required implementation scope (frontend/backend/data/integration)

- Backend/Python engine:
  - `python/envctl_engine/planning/`
  - `python/envctl_engine/runtime/`
  - `python/envctl_engine/startup/`
  - `python/envctl_engine/actions/`
  - `python/envctl_engine/requirements/`
  - `python/envctl_engine/ui/dashboard/`
  - `python/envctl_engine/state/` only if runtime/contract owner changes require it.
- Tests:
  - `tests/python/planning/`
  - `tests/python/runtime/`
  - `tests/python/startup/`
  - `tests/python/actions/`
  - `tests/python/requirements/`
  - `tests/python/ui/`
  - `tests/python/shared/`
- Docs/contracts:
  - `docs/reference/python-engine-architecture.md`
  - Relevant contributor/user docs when ownership guidance changes.
  - `contracts/*.json` only for intentional generated-output changes.
- Frontend:
  - None expected.
- Data/migrations:
  - None expected.
- Runtime services:
  - No application services are expected for normal validation of this refactor. If runtime validation is attempted and
    blocked by missing repo-local `.envctl` or lack of interactive TTY, report that exact blocker.

## Required tests and quality gates

Run targeted tests after each ownership slice:

- Planning/worktree:
  `uv run --extra dev pytest -q tests/python/planning tests/python/shared/test_structure_layout.py`.
- Runtime:
  `uv run --extra dev pytest -q tests/python/runtime tests/python/runtime/test_runtime_feature_inventory.py`.
- Startup:
  `uv run --extra dev pytest -q tests/python/startup tests/python/runtime/test_engine_runtime_real_startup.py`.
- Actions:
  `uv run --extra dev pytest -q tests/python/actions`.
- Requirements:
  `uv run --extra dev pytest -q tests/python/requirements`.
- UI/dashboard:
  `uv run --extra dev pytest -q tests/python/ui`.
- Shared structure/import:
  `uv run --extra dev pytest -q tests/python/shared/test_structure_layout.py tests/python/startup/test_support_module_decoupling.py tests/python/shared/test_utility_consolidation_contract.py`.
- Static check:
  `uv run --extra dev ruff check python tests scripts`.
- Generated contract checks:
  `uv run --extra dev python scripts/generate_runtime_feature_matrix.py`.
  `uv run --extra dev python scripts/generate_python_runtime_gap_report.py`.
  `uv run --extra dev python scripts/generate_python_engine_parity_manifest.py`.
  Compare resulting checked-in JSON artifacts and commit only intentional changes.
- Final gates:
  `uv run --extra dev pytest tests`.
  `uv run --extra dev python scripts/release_shipability_gate.py`.
  Push the branch, open/update PR #245 or its successor, inspect unresolved PR review threads, and wait for GitHub
  checks. If GitHub reports no checks, record the exact `gh`/API evidence instead of claiming CI passed.

## Edge cases and failure handling

- Dynamic CLI dispatch can hide call sites. Preserve behavior-level dispatch tests and generated feature matrix checks
  for every runtime route move.
- User-facing text can drift during extractions. Preserve assertions around launch guidance, prompt install output,
  failure summaries, debug report references, release-gate messages, startup summaries, and dashboard rendering.
- Generated contract files can drift during refactors. Regenerate intentionally and compare before committing.
- Compatibility wrappers can become permanent. Document remaining facades and remove redundant wrappers once call sites
  are safely moved.
- Planning/worktree changes must not write into sibling worktrees except generated plan worktrees selected by the
  operation.
- Fresh-AI worktree protection must continue to skip active generated worktrees during cleanup/delete flows.
- Supabase decomposition must preserve non-fatal repair/reinit behavior, QA/auth user setup semantics, readiness checks,
  and summary output.
- Dashboard restart selector behavior must remain stable across terminal/non-terminal and backend-resolution paths.
- Serena and CGC indexes can lag after structural moves. Use Serena for exact symbol navigation and diagnostics; use CGC
  context `Envctl` for broad graph checks. Run `serena project health-check` if symbol results look stale and refresh CGC
  with `cgc index . --context Envctl` after major structural changes if broad graph data is needed.
- Keep the current local `.envctl-state/worktree-provenance.json` edit out of unrelated implementation commits.

## Definition of done

- Every remaining requirement above is implemented end-to-end.
- `worktree_domain.py`, `engine_runtime.py`, `startup_orchestrator.py`, `action_command_orchestrator.py`,
  `requirements/supabase.py`, and `ui/dashboard/orchestrator.py` are thin coordination layers or explicitly documented
  compatibility facades with clear owner modules.
- Each major runtime area has focused owner modules and focused test suites.
- Plan-agent transport flags and readiness behavior are covered by a shared option matrix.
- Supabase requirements behavior is preserved behind smaller components.
- Dashboard orchestration and UI tests are split by behavior owner without losing coverage.
- Oversized tests are split by behavior without losing assertions or fixtures.
- Architecture docs, structure guards, import guards, and generated contracts reflect the final boundaries.
- `ruff`, targeted suites, full Python tests, generated contract checks, release shipability gate, and reported GitHub
  required checks pass or report exact no-check evidence.
- PR #245 or its successor is updated with final commits, validation evidence, and review-thread/check status.
