# Envctl Python Interactive and Color Parity Restoration Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Restore the Python engine UX to parity with the legacy shell UX for interactive operations, colorized output, dashboard richness, and logs workflows.
  - Remove the current mismatch where docs/flags promise interactive behavior but runtime output is mostly plain, single-pass, and non-interactive.
  - Make Python the only primary runtime path for an equivalent day-to-day operator experience (manual and AI-assisted workflows).
- Non-goals:
  - Rewriting downstream project service code.
  - Replacing launcher/install flows (`bin/envctl`, `lib/envctl.sh`) in this phase.
  - Introducing a heavy external TUI framework by default.
- Assumptions:
  - Python runtime remains default engine (`ENVCTL_ENGINE_PYTHON_V1=true`, `ENVCTL_ENGINE_SHELL_FALLBACK=false`).
  - Existing shell behavior is the parity reference, especially: `lib/engine/lib/ui.sh`, `lib/engine/lib/services_logs.sh`, `lib/engine/lib/actions.sh`.
  - Runtime artifacts under `${RUN_SH_RUNTIME_DIR}/python-engine/` stay the source of truth.

## Goal (user experience)
Running `envctl`, `envctl --resume`, `envctl --dashboard`, and `envctl --logs ...` in Python mode should feel like pre-migration behavior: colorful status sections, clear service grouping, interactive menus for target selection, follow-mode logs with stop controls, and a stable command loop with restart/health/errors/test/pr/commit/analyze/migrate actions. Non-TTY and batch mode should degrade safely to deterministic non-interactive output.

## Business logic and data model mapping
- Current execution path:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/engine/main.sh` -> Python runtime (`python/envctl_engine/cli.py:run`).
- Python command routing/runtime:
  - `python/envctl_engine/command_router.py:parse_route`
  - `python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`
- Runtime truth and state data models:
  - `python/envctl_engine/models.py` (`ServiceRecord`, `RunState`, `RequirementsResult`)
  - `python/envctl_engine/state.py` (persist/load)
  - `python/envctl_engine/runtime_map.py` (projection)
- Shell parity reference (source behavior):
  - Interactive TTY + menu loop: `lib/engine/lib/ui.sh` (`select_menu`, `interactive_mode`, `ui_interactive_handle_command`)
  - Rich status/dashboard/log rendering: `lib/engine/lib/services_logs.sh` (`show_status`, `tail_logs`, `tail_multiple_logs`, `tail_logs_noninteractive`)
  - Dashboard orchestration and command dispatch: `lib/engine/lib/actions.sh` (`run_dashboard`, `run_command`)
  - Color palette + color disable policy: `lib/engine/lib/core.sh:_init_colors`

## Current behavior (verified in code)
- Dashboard interactivity is parsed but not implemented:
  - Router parses `--interactive` and `--dashboard-interactive` (`python/envctl_engine/command_router.py`).
  - Runtime only prints one line (`Dashboard interactive mode enabled.`) then exits (`python/envctl_engine/engine_runtime.py:_dashboard`).
- Logs flags are parsed but not behaviorally honored:
  - Router parses `--logs-tail`, `--logs-follow`, `--logs-duration`, `--logs-no-color`.
  - Runtime `logs` only tails static lines from files; no follow loop, no duration timeout, no color policy (`python/envctl_engine/engine_runtime.py:_state_action`, `_print_logs`).
- No Python interactive command loop equivalent to shell:
  - Shell has continuous command loop with shortcuts and menus (`lib/engine/lib/ui.sh:interactive_mode`, `ui_interactive_handle_command`).
  - Python runtime executes one command and exits (`python/envctl_engine/engine_runtime.py:dispatch`).
- Status/dashboard richness is substantially lower in Python:
  - Shell `show_status` includes grouped projects, PID/listener status, log paths, n8n health, PR/test/analysis metadata, and run hints (`lib/engine/lib/services_logs.sh:show_status`).
  - Python dashboard prints only `backend`/`frontend` URL projection per project (`python/envctl_engine/engine_runtime.py:_dashboard`).
- Color system parity is missing:
  - Shell explicitly initializes ANSI palette with terminal detection and `NO_COLOR` behavior (`lib/engine/lib/core.sh:supports_color`, `_init_colors`).
  - Python runtime currently has no centralized color capability/palette abstraction.
- Public docs and CLI expectations exceed Python UX reality:
  - Docs and examples rely on `dashboard`, `logs --logs-follow`, targeted restart workflows (`docs/commands.md`, `docs/playbooks.md`, `docs/getting-started.md`).
  - Current Python implementations do not match those interaction contracts.
- Command surface mismatch remains material:
  - Shell parser currently exposes ~105 long flags (`lib/engine/lib/run_all_trees_cli.sh`).
  - Python parser currently exposes ~56 long flags (`python/envctl_engine/command_router.py`), with many UX-relevant flags missing.

## Root cause(s) / gaps
- Migration focused on orchestration correctness and parity manifests before terminal UX parity closure.
- No Python UI subsystem boundary exists (TTY capability, color palette, renderers, command loop, menu selectors).
- Parsed flag surface is not wired end-to-end for logs/dashboard interactivity.
- Status rendering logic from shell (`show_status`) has no Python equivalent model and renderer.
- Tests mostly validate routing/startup correctness, not user-facing terminal behavior parity.
- Docs describe high-value workflows that depend on UX features not yet ported.

## Plan
### 1) Define UX parity contract and acceptance matrix
- Add a parity matrix document under `docs/` mapping shell UX features to Python owners:
  - Interactive command loop
  - Dashboard details + health badges
  - Logs tail/follow/duration/no-color
  - Menu-driven target selection for restart/test/pr/commit/analyze/migrate/logs/errors
  - Color policy (`NO_COLOR`, non-TTY fallback)
- Link each matrix row to concrete function owners in Python and required tests.

### 2) Introduce a dedicated Python UI subsystem (no shell dependency)
- Add `python/envctl_engine/ui/` package with explicit modules:
  - `capabilities.py` (TTY detection, ANSI support, NO_COLOR, dumb TERM handling)
  - `palette.py` (semantic color tokens and safe formatting helpers)
  - `render.py` (status/dashboard/log line rendering)
  - `menu.py` (arrow-key list selection + fallback numeric prompt)
  - `interactive_loop.py` (command loop + command dispatch adapter)
  - `log_stream.py` (follow mode with stop controls, timeout support)
- Keep non-interactive fallback behavior deterministic and plain text when capabilities unavailable.

### 3) Port shell status/dashboard semantics into Python renderer
- Rebuild `show_status` parity in Python using `RunState` + runtime truth:
  - Group by project.
  - Service rows with icon, label, URL, PID/listener details.
  - Log path line per service.
  - n8n health row when present.
  - Optional metadata rows (tests summary, analysis summary, PR label/url, run hints).
- Replace `_dashboard` output with renderer-backed sections and optional interactive mode.

### 4) Implement interactive command loop parity in Python
- Add a loop mode for `start`, `resume`, and dashboard-interactive paths:
  - Header banner parity.
  - Command set parity: `(s)top (r)estart (t)est (p)r (c)ommit (a)nalyze (m)igrate (l)ogs (h)ealth (e)rrors (q)uit stop-all`.
  - Preserve selected target context where applicable.
- Reuse existing runtime action handlers rather than duplicating command logic.
- Add robust Ctrl-C / EOF handling and no-TTY fallback to safe exit.

### 5) Wire logs flags end-to-end (`--logs-tail`, `--logs-follow`, `--logs-duration`, `--logs-no-color`)
- Extend `_state_action("logs")` to:
  - Respect target filters (`--project`, `--service`, `--all`).
  - Stream follow output with timeout duration support.
  - Prefix and colorize lines by service unless no-color/capability-disabled.
  - Support stopping follow mode via Enter/Esc in TTY mode.
- Ensure behavior parity with shell `tail_logs_noninteractive` for batch mode.

### 6) Restore interactive selector menus for targetable commands
- For interactive mode commands (`restart`, `test`, `pr`, `commit`, `analyze`, `migrate`, `logs`, `errors`, `delete-worktree`):
  - Implement selector menu API in Python (`all`, per-project, per-service, grouped options).
  - Match shell semantics where command requires explicit target and return actionable errors when absent.
- Non-interactive mode must still support explicit selectors and deterministic failures.

### 7) Close command flag and alias parity for UX-critical options
- Expand Python router for high-impact UX flags now documented/expected:
  - `--parallel-trees`, `--parallel-trees-max`, `--no-parallel-trees`
  - `--fast`, `--refresh-cache`
  - `--clear-port-state`
  - `--stop-all-remove-volumes` and blast volume policy flags
  - `--interactive` behavior semantics for dashboard/loop paths
- For out-of-scope flags, emit explicit unsupported diagnostics (never silent no-op).

### 8) Build color policy and accessibility behavior
- Implement semantic color tokens with centralized switch:
  - Honor `NO_COLOR`.
  - Disable color in non-TTY.
  - Provide optional forced color env for CI snapshots.
- Preserve readable plain-text output format when color disabled.
- Add stable snapshot-like tests for both colorized and no-color render paths.

### 9) Add docs and examples that match real Python behavior
- Update docs to align command examples with implemented behavior only.
- Add one section documenting interactive-mode constraints:
  - TTY required for selector menus.
  - Batch mode behavior differences.
- Add troubleshooting guidance for TTY/stty edge cases.

### 10) Add migration guardrails and remove shell UX dependence
- Ensure no command family silently relies on shell fallback for interactive UX.
- Add doctor/readiness gate for `ui_parity` check (command matrix complete + tests green).
- Keep fallback explicit and temporary until all UX parity checks pass repeatedly.

## Tests (add these)
### Backend tests
- Add `tests/python/test_ui_capabilities.py`:
  - TTY and NO_COLOR capability policy.
- Add `tests/python/test_ui_palette.py`:
  - token rendering and no-color fallback behavior.
- Add `tests/python/test_dashboard_renderer.py`:
  - grouped service sections, icons/status, log path rows, n8n rows.
- Add `tests/python/test_interactive_command_loop.py`:
  - command shortcuts, quit/EOF/Ctrl-C handling, target menu flows.
- Extend `tests/python/test_engine_runtime_command_parity.py`:
  - assert dashboard/logs interactive flags produce functional behavior, not placeholder output.
- Extend `tests/python/test_cli_router_parity.py`:
  - additional UX-critical aliases/flags from shell surface.

### Frontend tests
- Add `tests/python/test_logs_stream_render.py`:
  - multi-service prefix rendering, color/no-color variants, error highlight behavior.
- Extend `tests/python/test_runtime_projection_urls.py` and `tests/python/test_frontend_projection.py`:
  - dashboard projection rows stay aligned to actual ports after restart/rebind.

### Integration/E2E tests
- Add `tests/bats/python_dashboard_interactive_e2e.bats`:
  - dashboard interactive mode remains active and handles commands.
- Add `tests/bats/python_logs_follow_parity_e2e.bats`:
  - `--logs-follow` and `--logs-duration` behavior parity.
- Add `tests/bats/python_logs_no_color_e2e.bats`:
  - `--logs-no-color` disables color prefixes.
- Add `tests/bats/python_interactive_menu_selection_e2e.bats`:
  - menu-driven target selection and command execution.
- Add `tests/bats/python_status_render_parity_e2e.bats`:
  - status output includes grouped sections, service rows, and log paths.
- Extend existing suites:
  - `tests/bats/python_command_alias_parity_e2e.bats`
  - `tests/bats/python_engine_parity.bats`

## Observability / logging (if relevant)
- Emit structured events for UI workflows:
  - `ui.capabilities.detected`
  - `ui.command_loop.enter/exit`
  - `ui.menu.open/select/cancel`
  - `ui.logs.follow.start/stop/timeout`
  - `ui.dashboard.render`
- Persist optional UI session telemetry under runtime root:
  - `ui_session.json`
  - `ui_events.jsonl`
- Include doctor fields:
  - `ui_parity_status`
  - `ui_capabilities`
  - `ui_interactive_mode_available`

## Rollout / verification
- Phase 0: freeze UX scope and parity matrix.
- Phase 1: land UI subsystem (`ui/` package) + unit tests.
- Phase 2: migrate dashboard/status renderer.
- Phase 3: migrate logs follow/tail/no-color behavior.
- Phase 4: migrate interactive command loop + selector menus.
- Phase 5: close router flag parity for UX-critical options.
- Phase 6: run full verification matrix and update docs.
- Verification commands:
  - `.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats --print-output-on-failure tests/bats/python_*.bats`
  - `bats --print-output-on-failure tests/bats/*.bats`
  - `.venv/bin/python scripts/release_shipability_gate.py --repo .`

## Definition of done
- Python runtime provides interactive loop and menu-driven command UX equivalent to legacy shell for supported command families.
- Dashboard and status rendering provide grouped, colorized, health-aware output with deterministic no-color fallback.
- Logs command fully honors tail/follow/duration/no-color flags and target selection semantics.
- Docs match implemented behavior; no UX claims require shell fallback.
- UX parity tests pass in both Python unit suite and BATS integration suite.
- Shell fallback is no longer required for normal interactive operation.

## Risk register (trade-offs or missing tests)
- Risk: Terminal behavior differs across macOS/Linux shells and CI pseudo-TTYs.
  - Mitigation: capability abstraction + fallback numeric prompt + TTY simulation tests.
- Risk: Interactive loop regressions may block automation workflows.
  - Mitigation: strict `--batch` non-interactive path and regression tests.
- Risk: Colorized output can reduce readability in some terminals.
  - Mitigation: semantic palette + NO_COLOR + explicit no-color flags.
- Risk: Large parity scope can cause phased delivery drift.
  - Mitigation: matrix-driven acceptance gates and per-phase required tests.

## Open questions (only if unavoidable)
- Should we keep the exact shell keybindings and menu presentation, or allow minor presentation differences if command semantics and discoverability are preserved?
- Do we want to keep a tiny shell interactive fallback for one release after Python UI parity lands, or remove it immediately once parity gates are green?
