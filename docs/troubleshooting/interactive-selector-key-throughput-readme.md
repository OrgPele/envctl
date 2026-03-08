# Interactive Selector Key Throughput Investigation (Paused)

Last updated: March 4, 2026  
Status: Open bug, intentionally paused due priority

## Why this document exists
This is a deep continuity doc for a long-running interactive UI bug so future debugging can restart without re-learning context.

Primary bug still present:
- In Apple Terminal, dashboard target selector (`t` and similar target menus) may register only about half of repeated `Down` key presses.
- In VSCode terminal, behavior is often correct.
- In `--plan` flow, selector behavior is often correct (full key throughput observed in captures).

The issue is not fully fixed. This doc captures current facts, what was changed, what was ruled out, and what to do next.

---

## 1) Scope and impact

### Affected path
- Interactive dashboard command loop in `main` mode.
- Target selector screen opened by commands like `t` (tests), and likely other target-selection actions.

### Not consistently affected
- `--plan` selector path (Textual planning selector) frequently captures repeated arrows correctly.
- VSCode terminal often does not reproduce the drop.

### User-visible symptom
- User presses Down 10 times.
- Selector often moves as if only ~5 were received.
- Debug evidence confirms under-capture can happen at input read level, not just UI redraw level.

---

## 2) Clean reproduction command (safe baseline)

Use this command in Apple Terminal when reproducing:

```bash
ENVCTL_UI_SELECTOR_ESCDELAY=100 \
ENVCTL_UI_SELECTOR_FOCUS_REPORTING=0 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
/Users/kfiramar/projects/envctl/bin/envctl
```

Repro steps:
1. Start with command above.
2. At dashboard prompt, type `t`.
3. Press Down exactly 10 times.
4. Exit selector (`q` or Ctrl+C) if needed.
5. Record `session_id` from dashboard header.

---

## 3) Important pitfalls (avoid these while reproducing)

### Do not use this unless specifically testing it
```bash
ENVCTL_UI_BASIC_INPUT_FD=1
```

Why:
- It can make command input read path interact badly with terminal escape traffic in some sessions.
- Symptom seen: random control-looking output like `^[[<35;...` while typing command text.
- This became a separate failure mode and obscured the main selector bug.

### If terminal state looks corrupted
Run once in that same terminal tab:

```bash
printf '\e[?1000l\e[?1002l\e[?1003l\e[?1006l\e[?1004l\e[<u\e[?2004l'
stty sane
```

Then restart with the safe baseline command above.

---

## 4) Investigation timeline (key sessions)

All sessions below are under runtime scope `repo-b15e3f0c8257`.

| Session ID | Terminal | Entry | Observed result | Key evidence |
|---|---|---|---|---|
| `session-20260304122236-59942-4e5d` | VSCode | `envctl` dashboard -> `t` | Good (10 down captured) | `key_events_by_name.down=10` in selector snapshots. |
| `session-20260304122508-62401-6b0b` | Apple Terminal | `envctl` dashboard -> `t` | Bad (~5/10) | `read_samples` had 5 `b'\x1b[B'`; key events plateau at 5. |
| `session-20260304124949-74990-95f4` | Apple Terminal | `envctl --plan` | Good (10/10) | Planning selector summary: `down=10`, no losses. |
| `session-20260304131534-86493-414b` | Apple Terminal | dashboard `t` with extra debug flags | Bad (~4/10) | Input thread alive; only 4 down reads before idle. |
| `session-20260304132035-91356-cc26` | Apple Terminal | dashboard with nonblocking read guard enabled | Regressed badly | Many `b''` reads, almost no key events; guard found unsafe by default. |
| `session-20260304132453-94915-9563` | Apple Terminal | command had truncated env var text | Corrupted command input | Random escape-like characters seen while typing. |
| `session-20260304133518-3280-5c9b` | Apple Terminal | latest code + safe baseline | Still bad (~5/10) | `reset_escape_modes=ok`, but selector still captured only 5 down bytes. |

Takeaway from this timeline:
- We fixed one corruption mode (escape noise in command prompt), but the core “half arrows captured” bug remains for dashboard target selector in Apple Terminal.

---

## 5) Current architecture map (relevant code paths)

### Dashboard target selector path
- Command loop: `python/envctl_engine/ui/command_loop.py`
- Backend preflight: `python/envctl_engine/ui/backend.py`
- Selector UI: `python/envctl_engine/ui/textual/screens/selector.py`

### `--plan` selector path
- Planning domain: `python/envctl_engine/worktree_planning_domain.py`
- Planning Textual screen: `python/envctl_engine/ui/textual/screens/planning_selector.py`

### Command input / terminal state management
- `python/envctl_engine/ui/terminal_session.py`

---

## 6) Findings we are confident about

### Confirmed true
1. Dashboard selector defaults to Textual plan-style engine.
2. Prompt-toolkit rollback is only active when explicitly requested (`ENVCTL_UI_SELECTOR_IMPL=planning_style`).
3. In failing Apple Terminal sessions, under-capture happens at read layer:
   - Fewer arrow byte sequences are read (`b'\x1b[B'`) than user claims to press.
4. In at least one Apple Terminal `--plan` session, all 10 arrows were captured.
5. Input thread is alive in failures; this is not a simple thread death.
6. Command loop is not concurrently reading stdin during selector runtime (for these captured sessions).

### Ruled out or de-prioritized
1. “Wrong selector engine” is not the reason in these sessions.
2. Pure parser-level drop after bytes are read is not primary in the common failing traces.
3. Nonblocking monkeypatch guard as default is not safe (it introduced `b''` read storms).

---

## 7) Changes made during this investigation

### A) Nonblocking read guard made opt-in only
File: `python/envctl_engine/ui/textual/screens/selector.py`

What changed:
- `_guard_textual_nonblocking_read(...)` now does nothing unless:
  - `ENVCTL_UI_SELECTOR_NONBLOCK_READ_GUARD=1` (or `true/yes/on`).
- Emits debug event `ui.selector.key.driver.read_guard` with `guard_enabled=false` by default.

Reason:
- Guard caused severe regressions in some sessions (`read_zero_reads` spikes, no key progress).

### B) Apple Terminal escape-mode reset before command reads
File: `python/envctl_engine/ui/terminal_session.py`

What changed:
- `_restore_stdin_terminal_sane(emit=...)` now calls `_reset_terminal_escape_modes(...)`.
- In `auto` mode, reset applies for `TERM_PROGRAM=Apple_Terminal`.
- Resets:
  - mouse tracking modes (`?1000l`, `?1002l`, `?1003l`, `?1006l`)
  - focus reporting (`?1004l`)
  - kitty keyboard protocol (`<u`)
  - bracketed paste (`?2004l`)
- Emits `ui.tty.transition action=reset_escape_modes result=ok/failed`.

Reason:
- To prevent stale escape protocol state leaking into command input as random `^[[<...` sequences.

### C) Added deeper pending-byte instrumentation
File: `python/envctl_engine/ui/textual/screens/selector.py`

What changed:
- Driver snapshots now include:
  - `stdin_pending_bytes`
  - `stdout_pending_bytes`
  - `read_fd_pending_bytes`
- Uses `ioctl(FIONREAD)` where available.

Reason:
- Needed to distinguish:
  - bytes queued but not consumed
  - bytes never delivered by terminal/input path.

---

## 8) Tests added/validated

Validated repeatedly after changes:
- `tests/python/test_textual_selector_interaction.py`
- `tests/python/test_textual_selector_flow.py`
- `tests/python/test_textual_selector_responsiveness.py`
- `tests/python/test_interactive_selector_key_throughput_pty.py`
- `tests/python/test_selector_input_preflight.py`
- `tests/python/test_terminal_session_debug.py`

Added terminal-session tests:
- Escape-mode reset is applied for Apple Terminal.
- Escape-mode reset is skipped in auto mode for non-Apple terminal programs.

---

## 9) Open hypotheses (ranked)

1. Apple Terminal + dashboard target-selector context is intermittently under-delivering repeated arrow key sequences before app-level parse.
2. `--plan` selector and dashboard selector differ in surrounding runtime context enough to influence input delivery timing/behavior.
3. There may still be a subtle preflight/state transition interaction specific to dashboard target selector invocation timing.

Hypothesis that was tested and parked:
- Forcing nonblocking stdin reads in Textual input driver as default.  
  Rejected as default due regression risk.

---

## 10) Resume plan (when work restarts)

### Phase 1: Re-validate current baseline quickly
1. Run safe baseline command (Section 2) in Apple Terminal.
2. Reproduce once (`t`, Down x10).
3. Capture `session_id`.
4. Confirm in snapshot whether `key_events_by_name.down` is still around 5.

### Phase 2: High-signal isolation experiment
Goal: separate physical keyboard path from app consumption path.

1. Keep selector open in Apple Terminal tab A.
2. In tab B, inject arrows directly to tty:
   ```bash
   for i in {1..10}; do printf '\033[B' > /dev/ttysXXX; done
   ```
   Use `tty` of tab A.
3. Compare selector movement and debug counts.

Interpretation:
- If injected arrows reach 10 reliably, physical keyboard/key repeat path is suspect.
- If injected arrows still drop similarly, app/runtime/selector path is suspect.

### Phase 3: Compare dashboard selector vs planning selector in same terminal session
1. Run dashboard selector test in Apple Terminal.
2. Run `--plan` selector test in same terminal profile/tab style.
3. Compare driver snapshots:
   - `read_calls`
   - `key_events_by_name`
   - `read_samples`
   - `stdin_pending_bytes`
   - non-key message profile.

### Phase 4: If still unresolved
1. Build a minimal standalone Textual repro app in repo (same bindings + list model).
2. Reproduce directly in Apple Terminal.
3. If repro survives outside envctl, open upstream Textual/terminal behavior issue with trace evidence.

---

## 11) Debug bundle workflow for this bug

### Deep run
```bash
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
/Users/kfiramar/projects/envctl/bin/envctl
```

### Bundle commands
```bash
/Users/kfiramar/projects/envctl/bin/envctl --debug-pack --scope-id repo-b15e3f0c8257 --run-id <run_id>
/Users/kfiramar/projects/envctl/bin/envctl --debug-report --scope-id repo-b15e3f0c8257 --run-id <run_id>
```

### Quick local extraction snippets

Print selector engine + key summary:
```bash
python3 - <<'PY'
import json, pathlib
p=pathlib.Path('/tmp/envctl-runtime/python-engine/repo-b15e3f0c8257/debug/<session_id>/events.debug.jsonl')
for line in p.open():
    e=json.loads(line)
    if e.get('event') in {'ui.selector.engine','ui.selector.key.driver.summary'}:
        print(e.get('seq'), e.get('event'), {k:e.get(k) for k in ['selector_id','requested_impl','effective_engine','key_events_by_name','read_calls','read_zero_reads','read_samples']})
PY
```

Inspect most recent selector snapshots:
```bash
tail -n 120 /tmp/envctl-runtime/python-engine/repo-b15e3f0c8257/debug/<session_id>/events.debug.jsonl
```

---

## 12) Config and feature flags relevant to this investigation

- `ENVCTL_UI_SELECTOR_IMPL`
  - default/unset => Textual plan-style selector
  - `planning_style` => prompt-toolkit rollback selector
  - `legacy` => compatibility alias to Textual selector mode

- `ENVCTL_UI_SELECTOR_NONBLOCK_READ_GUARD`
  - default off
  - enable only for controlled experiments

- `ENVCTL_UI_RESET_ESCAPE_MODES`
  - default `auto` (applies reset in Apple Terminal)
  - `off` disables reset
  - `on` forces reset regardless of terminal program

- `ENVCTL_UI_BASIC_INPUT_FD`
  - avoid for this bug unless explicitly testing command-reader behavior

---

## 13) Current bottom line

As of the latest captured run (`session-20260304133518-3280-5c9b`):
- Terminal escape corruption mitigation is active and working.
- Selector still under-captures repeated Down presses in Apple Terminal (5 captured in that run).
- Core issue remains unresolved and is safe to pause.

Use this document as the restart point when priority returns.
