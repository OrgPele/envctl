# Envctl Interactive UI Migration Plan (prompt_toolkit)

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make interactive menus consistent and reliable for restart/logs/test/stop/pr/commit/analyze/migrate flows.
  - Fix Enter key reliability in interactive dashboard loops and menus.
  - Consolidate interactive input handling into a single, testable path.
  - Migrate menu and input UI to prompt_toolkit with non-TTY fallbacks.
- Non-goals:
  - Rewriting service orchestration logic or command semantics.
  - Changing command routing or flag names beyond what interactive UI needs.
  - Removing shell UX features; parity remains a reference.
- Assumptions:
  - Python engine remains the default runtime path.
  - prompt_toolkit can be added as an optional dependency with a fallback path for non-tty or missing package.
  - Menu behavior should track shell selectors in lib/engine/lib/ui.sh.

## Goal (user experience)
Users can enter interactive mode (post-start, resume, dashboard) and reliably press Enter to submit commands. Interactive commands that require target selection (restart, logs, test, pr, commit, analyze, migrate, errors, delete-worktree) open a clear menu to select targets. The menu behavior matches the shell UX (arrow navigation, Enter to select, q to cancel) and degrades to non-interactive prompts when no TTY is available. Logs follow and command loops remain responsive and do not drop input.

## Business logic and data model mapping
- Entry points for interactive loops:
  - python/envctl_engine/startup_orchestrator.py: start and post-start interactive loop (calls PythonEngineRuntime._run_interactive_dashboard_loop).
  - python/envctl_engine/resume_orchestrator.py: resume interactive loop (calls PythonEngineRuntime._run_interactive_dashboard_loop).
  - python/envctl_engine/dashboard_orchestrator.py: dashboard interactive loop and command parsing.
- Input and TTY handling:
  - python/envctl_engine/terminal_ui.py: RuntimeTerminalUI.read_interactive_command_line, _can_interactive_tty, flush_pending_interactive_input.
  - python/envctl_engine/engine_runtime.py: duplicate interactive loop and TTY handling.
- Command dispatch and target resolution:
  - python/envctl_engine/action_command_orchestrator.py: resolve_targets for test/pr/commit/analyze/migrate.
  - python/envctl_engine/state_action_orchestrator.py: logs/health/errors behavior.
  - python/envctl_engine/lifecycle_cleanup_orchestrator.py: stop/stop-all/blast-all.
  - python/envctl_engine/command_router.py: --interactive, --dashboard-interactive, --batch, --logs-*, target flags.
- Shell parity reference for interactive menus and commands:
  - lib/engine/lib/ui.sh: select_menu, select_restart_target, select_test_target, select_grouped_target, ui_interactive_handle_command, interactive_mode.
  - lib/engine/lib/actions.sh: delete-worktree interactive selector.
  - lib/engine/lib/planning.sh: planning selection menu.

## Current behavior (verified in code)
- Planning selection menu works with raw tty handling:
  - python/envctl_engine/planning_menu.py: PlanningSelectionMenu.run uses tty.setraw(fd) and byte-level key handling (read_key, read_escape_sequence, decode_escape).
  - python/envctl_engine/worktree_planning_domain.py: _run_planning_selection_menu uses terminal_ui.planning_menu.
- Interactive dashboard loop uses readline with partial termios changes:
  - python/envctl_engine/terminal_ui.py: read_interactive_command_line uses termios, disables ISIG only, then handle.readline().
  - python/envctl_engine/engine_runtime.py: _read_interactive_command_line duplicates the same behavior.
  - python/envctl_engine/dashboard_orchestrator.py: _sanitize_interactive_input strips control chars (including carriage return). Enter key failures likely originate here plus readline behavior.
- Missing interactive menus for target selection:
  - python/envctl_engine/action_command_orchestrator.py: resolve_targets returns "No <command> target selected" when no selectors provided.
  - python/envctl_engine/state_action_orchestrator.py: logs/errors/health are non-interactive and expect explicit flags.
- Duplicate interactive loop implementation:
  - python/envctl_engine/engine_runtime.py defines _run_interactive_dashboard_loop and _run_interactive_command while dashboard_orchestrator.py has its own equivalents.

## Root cause(s) / gaps
1. Input handling is inconsistent across modes:
   - Planning menu uses raw byte-level input, but dashboard input uses readline in canonical mode with partial termios changes.
2. Input sanitization removes control characters:
   - dashboard_orchestrator._sanitize_interactive_input strips \r (carriage return), which can drop Enter presses.
3. Interactive menus for target selection are missing in Python:
   - Shell uses select_menu helpers for restart/logs/test/etc., but Python has no equivalent.
4. TTY handling is duplicated:
   - engine_runtime.py duplicates terminal_ui.py logic, increasing drift and inconsistent behavior.
5. Dependency strategy is unclear:
   - No obvious Python packaging file (requirements.txt/pyproject.toml) found in repo root.

## Plan
### 1) Inventory, consolidate, and define a single interactive input controller
- Create a dedicated UI module (python/envctl_engine/ui/) with:
  - terminal_session.py: owns termios state (if legacy path kept) and handles enter/cancel events.
  - input_adapter.py: maps key events to semantic actions (Submit, Cancel, Up, Down, Left, Right).
  - menu.py: selection menu interface (backed by prompt_toolkit or fallback).
  - command_loop.py: interactive loop to render dashboard, read commands, dispatch to existing orchestrators.
- Remove duplicate interactive loop from engine_runtime.py:
  - Route all interactive dashboard flow through dashboard_orchestrator with the new UI controller.
  - Keep engine_runtime.py as the single caller but no longer hosts input logic.

### 2) Add prompt_toolkit integration with a non-TTY fallback
- Introduce prompt_toolkit as an optional dependency (packaging location to be determined).
- Implement prompt_toolkit-backed menu and command input:
  - Use checkboxlist_dialog for multi-select menus (restart/test/logs/errors/delete-worktree).
  - Use radiolist_dialog for single-choice menus (delete-worktree mode: one/all/cancel).
  - Use prompt() for command input in the dashboard loop.
- Implement fallback for non-TTY or missing prompt_toolkit:
  - Numeric prompt selection (print list, ask for number).
  - For command loop, fallback to input() or non-interactive snapshot.

### 3) Build a Python menu parity layer matching shell behavior
- Mirror shell menu semantics from lib/engine/lib/ui.sh:
  - restart: All services, per-project, per-service (select_restart_target).
  - test: Unte sted projects, All projects, per-project (select_test_target).
  - logs/errors: All services, per-project, per-service (select_grouped_target).
  - pr/commit/analyze/migrate: All projects, per-project (select_project_target).
  - delete-worktree: mode selection + path selection (lib/engine/lib/actions.sh).
- Define a shared TargetSelector interface that returns route-compatible selectors:
  - __ALL__ for all services/projects.
  - __PROJECT__:name for project-scoped selections.
  - service name for service-scoped selections.

### 4) Wire interactive selection into command handlers
- action_command_orchestrator.resolve_targets:
  - When no selectors provided and interactive TTY is available, call TargetSelector to select targets.
  - Preserve existing error behavior in batch/non-tty.
- state_action_orchestrator.execute:
  - For logs/errors, allow interactive selection if no explicit targets provided and TTY is available.
  - Keep non-interactive fallback and respect --logs-* flags.
- lifecycle_cleanup_orchestrator:
  - For stop, use menu to select service/project targets (parity with shell stop behavior).
  - stop-all and blast-all remain direct actions.

### 5) Remove Enter key failure conditions
- Replace readline-based input with prompt_toolkit prompt in interactive loop.
- If fallback path is used, normalize Enter handling by explicitly reading bytes and matching \r or \n.
- Update dashboard_orchestrator._sanitize_interactive_input to avoid stripping carriage return (if still used for fallback).

### 6) Test coverage (TDD-first implementation)
- Add/extend tests before implementation to ensure behavior changes are measurable:
  - test_interactive_input_reliability.py: update to cover prompt_toolkit fallback path and Enter normalization.
  - test_planning_menu_rendering.py: add coverage for menu parity mapping and non-tty fallback.
  - test_dashboard_render_alignment.py and test_dashboard_rendering_parity.py: ensure NO_COLOR still honored.
  - tests/bats/python_interactive_input_reliability_e2e.bats: add prompt_toolkit-enabled path or fallback path coverage.
  - New tests for TargetSelector behavior (project/service mapping, __ALL__, __PROJECT__ labels).

### 7) Packaging and dependency decision
- Determine where Python dependencies are managed (no requirements/pyproject found in repo root).
- Decide on dependency strategy:
  - Optional: attempt import prompt_toolkit and fallback gracefully if missing.
  - If there is a hidden packaging file, add prompt_toolkit>=3.0 to it.
  - If no packaging exists, add a minimal python/requirements.txt or document install guidance in docs.

### 8) Rollout and feature flags
- Add an env flag (e.g., ENVCTL_UI_PROMPT_TOOLKIT=true) to force the new path while keeping fallback.
- Default to new path only when prompt_toolkit is available and TTY is interactive.
- Keep batch/non-tty paths unchanged.

## Tests (add these)
### Backend tests
- tests/python/test_interactive_input_reliability.py
  - Enter normalization in fallback path.
  - No control char stripping for Enter in sanitize path.
- tests/python/test_planning_menu_rendering.py
  - prompt_toolkit menu mapping: count selection and cancel behavior.
- tests/python/test_target_selector.py (new)
  - restart/test/logs/errors selector mapping parity with shell.
- tests/python/test_action_command_orchestrator_targets.py (new)
  - resolve_targets uses interactive selection when no selectors and TTY available.
- tests/python/test_state_action_orchestrator_logs.py (extend)
  - interactive selection for logs/errors when no selectors.

### Frontend tests
- None (terminal-only behavior).

### Integration/E2E tests
- tests/bats/python_interactive_input_reliability_e2e.bats
  - Enter handling in interactive loop with fallback path.
- tests/bats/python_interactive_menu_selection_e2e.bats (new)
  - restart/test/logs selection menu flows in Python engine.

## Observability / logging (if relevant)
- Add structured events for UI selection flow:
  - ui.menu.open, ui.menu.select, ui.menu.cancel
  - ui.command_loop.enter, ui.command_loop.exit
  - ui.input.submit (optional, with no user text for privacy)
- Include in runtime events.jsonl to support debugging when input fails.

## Rollout / verification
- Phase 1: Implement prompt_toolkit path behind ENVCTL_UI_PROMPT_TOOLKIT flag.
- Phase 2: Default-on prompt_toolkit when available and TTY is interactive.
- Verify in real terminals (macOS Terminal, iTerm2, tmux) and non-tty (CI).
- Use tests/bats to validate non-tty fallback behavior.

## Definition of done
- Interactive menus exist for restart, logs, test, pr, commit, analyze, migrate, errors, delete-worktree.
- Enter works reliably in dashboard interactive loop.
- No duplicate input handling in engine_runtime.py.
- prompt_toolkit path used by default when available and TTY is interactive.
- All new tests pass and existing suites remain green.

## Risk register (trade-offs or missing tests)
- Packaging risk: no clear dependency file; need explicit decision on how prompt_toolkit is installed.
- Runtime risk: multiple stdin consumers (logs follow) can still steal input; needs serialized input ownership.
- Terminal compatibility: prompt_toolkit color depth and keybindings need validation in tmux/ssh.

## Open questions (only if unavoidable)
1. Where should prompt_toolkit be declared as a dependency (no requirements/pyproject found)?
2. Should the new UI path be default-on or behind a feature flag for the first release?
