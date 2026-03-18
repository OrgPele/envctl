# Envctl Interactive UI Library Replacement Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Replace custom terminal input, menu, and spinner implementations with maintained libraries to reduce input/TTY bugs.
  - Standardize interactive command input and menu selection in the dashboard and planning flows.
  - Preserve non-interactive behavior (batch/CI) and existing command semantics.
- Non-goals:
  - Changing orchestration logic, service lifecycle semantics, or routing behavior.
  - Rewriting dashboard rendering and runtime state projection beyond what libraries require.
  - Removing shell parity checks or release gates.
- Assumptions:
  - Python runtime remains the default interactive path.
  - Dependencies may be added in `python/requirements.txt`.
  - Non-tty fallback paths are still required.

## Goal (user experience)
Interactive mode reliably accepts single-key commands (t/r/q/etc) without repeated characters or stuck input. When a command needs target selection, the menu appears consistently and key handling is stable in tmux/ssh/macOS terminals. Spinners/status output no longer corrupts input or interleaves with menus. Behavior remains functional in non-interactive/batch mode with safe fallbacks.

## Business logic and data model mapping
- Interactive loop and command intake:
  - `python/envctl_engine/ui/command_loop.py:run_dashboard_command_loop` (command loop, spinner bridge, input read).
  - `python/envctl_engine/engine_runtime.py:_read_interactive_command_line` (currently forces `prefer_basic_input=True`).
  - `python/envctl_engine/terminal_ui.py:RuntimeTerminalUI.read_interactive_command_line`.
- Menu/input handling:
  - `python/envctl_engine/ui/menu.py` (PromptToolkitMenuPresenter, InteractiveTtyMenuPresenter, raw mode, key decoding).
  - `python/envctl_engine/ui/input_adapter.py` (mapping key tokens to actions).
  - `python/envctl_engine/planning_menu.py:PlanningSelectionMenu.run` (raw tty planning selector).
  - `python/envctl_engine/ui/terminal_session.py` (termios prompt reading, fallback reads, tty checks).
- Target selection integration:
  - `python/envctl_engine/ui/target_selector.py`.
  - `python/envctl_engine/action_command_orchestrator.py:resolve_targets`.
- Spinner/status output:
  - `python/envctl_engine/ui/spinner.py`.
- Process/port truthiness (candidate for library replacement):
  - `python/envctl_engine/process_probe.py` (shell-based process/port ownership and lsof parsing).

## Current behavior (verified in code)
- Command input and fallback are custom:
  - `python/envctl_engine/ui/command_loop.py` uses `TerminalSession(..., prefer_basic_input=True)` and manual sanitization.
  - `python/envctl_engine/ui/terminal_session.py` reads from `/dev/tty`, uses termios/`os.read`, and flushes input.
- Menus are split across two custom implementations:
  - `python/envctl_engine/ui/menu.py` includes a raw-mode `InteractiveTtyMenuPresenter` with manual escape decoding and `_read_terminal_key`.
  - `python/envctl_engine/planning_menu.py` uses `tty.setraw` and byte-level key handling for the planning selector.
- Spinner is custom and writes directly to stderr:
  - `python/envctl_engine/ui/spinner.py` uses a custom thread and ANSI control sequences.
- Process probing is shell-driven:
  - `python/envctl_engine/process_probe.py` relies on `process_runner` and shell commands, then parses text.
- Dependencies:
  - `python/requirements.txt` already includes `prompt_toolkit>=3.0`.

## Root cause(s) / gaps
1. Input handling and menu rendering rely on manual termios + escape parsing, which is fragile in tmux/ssh and after full-screen menus.
2. There are multiple input paths (planning menu vs dashboard vs menu presenter) with their own buffering and flushing logic.
3. Custom spinner and status output can interleave with input, causing corruption or repeated characters.
4. Process/port truthiness depends on shell output parsing, which is platform-sensitive and difficult to harden.

## Plan
### 1) Select library replacements and establish dependency policy
- **Prompt input + menus:** Use `prompt_toolkit` as the primary input and selection engine (already in `python/requirements.txt`).
  - Evidence: prompt_toolkit provides `prompt()` and dialog-based selection (docs: `https://python-prompt-toolkit.readthedocs.io/en/stable/`).
- **Spinner/status output:** Use `rich` for spinners and status rendering (`rich.status`, `rich.live`).
  - Evidence: `https://rich.readthedocs.io/en/stable/reference/status.html`.
- **Process probe:** Use `psutil` for process/port ownership and liveness instead of parsing shell output.
  - Evidence: `https://psutil.readthedocs.io/en/stable`.
- **Optional alternatives:** InquirerPy/Textual are viable but heavier; prefer prompt_toolkit + rich to minimize framework switching.
- Update `python/requirements.txt` to add `rich` and `psutil` (and optionally `InquirerPy` if we decide to use its menu wrappers).

### 2) Replace dashboard command input with prompt_toolkit
- In `python/envctl_engine/ui/terminal_session.py` and `python/envctl_engine/engine_runtime.py`, remove forced `prefer_basic_input=True` for interactive TTY and route to prompt_toolkit `PromptSession`.
- Keep a non-tty fallback (`input()`) path; explicitly guard with `can_interactive_tty()` to preserve batch/CI behavior.
- Remove custom read/flush loops once prompt_toolkit is authoritative for interactive input.
- Edge cases: CTRL+C, EOF, bracketed paste; ensure sanitized output remains consistent with current `dashboard_orchestrator._sanitize_interactive_input`.

### 3) Consolidate menu selection on prompt_toolkit
- Replace `InteractiveTtyMenuPresenter` (raw-mode key handling) in `python/envctl_engine/ui/menu.py` with prompt_toolkit-based menu behavior exclusively for interactive TTY.
- Retain `FallbackMenuPresenter` for non-interactive contexts.
- Migrate `planning_menu.py` to prompt_toolkit as a full-screen checkbox list (or a multi-select dialog) to eliminate custom termios paths.
- Update `python/envctl_engine/ui/target_selector.py` to call the prompt_toolkit presenter consistently for test/restart/logs/pr/commit/analyze/migrate menus.

### 4) Replace spinner/output handling with rich
- Replace `python/envctl_engine/ui/spinner.py` with Rich `Status` or `Live` rendering.
- Update `python/envctl_engine/ui/command_loop.py` to use rich status updates instead of manual ANSI sequences.
- Ensure `NO_COLOR` and non-tty behavior is preserved by configuring Rich `Console` options appropriately.

### 5) Replace shell-based process probes with psutil
- Implement a `PsutilProbeBackend` in `python/envctl_engine/process_probe.py` using:
  - `psutil.pid_exists`, `psutil.Process(pid).is_running()`.
  - `psutil.net_connections(kind="inet")` to determine listening ports and PID ownership.
- Keep the existing shell backend as a fallback (feature-flagged) until parity tests pass.

### 6) Tests (update and add)
- Update existing tests to reflect new behavior paths:
  - `tests/python/test_terminal_ui_dashboard_loop.py` (prompt_toolkit path for input).
  - `tests/python/test_ui_menu_interactive.py` (prompt_toolkit-only path, fallback behavior).
  - `tests/python/test_interactive_input_reliability.py` (prompt_toolkit entry and fallback tests).
- Add new tests for psutil probe backend:
  - `tests/python/test_process_probe_contract.py` or a new `test_process_probe_psutil.py`.
- Add/extend BATS integration tests for interactive loop reliability:
  - `tests/bats/python_interactive_input_reliability_e2e.bats`.

### 7) Rollout and feature flags
- Introduce env flags for staged rollout:
  - `ENVCTL_UI_PROMPT_TOOLKIT=true|false` to force prompt_toolkit path.
  - `ENVCTL_UI_RICH=true|false` for rich spinner/status.
  - `ENVCTL_PROBE_PSUTIL=true|false` for psutil process probes.
- Default to library-backed paths when dependencies are installed and TTY is interactive; fall back otherwise.

## Tests (add these)
### Backend tests
- `tests/python/test_terminal_ui_dashboard_loop.py` (prompt_toolkit input path)
- `tests/python/test_ui_menu_interactive.py` (prompt_toolkit menu path, fallback only for non-tty)
- `tests/python/test_interactive_input_reliability.py` (input handling with prompt_toolkit)
- `tests/python/test_process_probe_contract.py` (psutil backend) or new `test_process_probe_psutil.py`

### Frontend tests
- None (terminal-only behavior)

### Integration/E2E tests
- `tests/bats/python_interactive_input_reliability_e2e.bats` (interactive loop in tmux/ssh)

## Observability / logging (if relevant)
- Emit structured UI events when library-backed paths are used:
  - `ui.input.backend=prompt_toolkit|fallback`
  - `ui.menu.backend=prompt_toolkit|fallback`
  - `ui.spinner.backend=rich|legacy`
  - `probe.backend=psutil|shell`

## Rollout / verification
- Stage 1: enable library-backed paths behind flags; run targeted unit tests and tmux repros.
- Stage 2: default-on when libraries are available; verify BATS interactive tests.
- Stage 3: remove or deprecate legacy raw-mode implementations after parity gates are green.

## Definition of done
- Interactive command input and menus use prompt_toolkit when available; no raw termios key parsing remains in the primary path.
- Planning menu uses prompt_toolkit and no longer relies on custom `tty.setraw` handling.
- Spinner/status output uses rich, with stable rendering and no interleaving artifacts.
- Process probes use psutil by default with shell fallback available.
- All listed tests pass; new E2E coverage in tmux/ssh is green.

## Risk register (trade-offs or missing tests)
- Dependency packaging risk: ensure `python/requirements.txt` is authoritative for deployment environments.
- Terminal compatibility risk: prompt_toolkit + rich must be validated under tmux and SSH.
- Behavior drift risk: menu/selection behavior must match shell parity expectations.

## Open questions (only if unavoidable)
1. Are new dependencies (`rich`, `psutil`, optional `InquirerPy`) acceptable in all target environments?
2. Should prompt_toolkit and rich be default-on immediately or gated via env flags for one release?
