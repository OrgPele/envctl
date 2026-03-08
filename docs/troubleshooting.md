# Troubleshooting

## Could not resolve repository root
- Confirm the path is a git repo root (`.git` dir or file).
- Use `--repo /absolute/path` when running outside the repo tree.

## Port collisions or stale reservations
- Run `envctl --doctor`.
- Run `envctl --clear-port-state`.
- Adjust base ports in `.envctl`.
- Inspect `${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}/python-engine/ports_manifest.json`.

## Slow startup latency (requirements dominate)
Recommended capture:
1. Run a deep startup sample:
   - `ENVCTL_DEBUG_UI_MODE=deep ENVCTL_DEBUG_RESTORE_TIMING=1 ENVCTL_DEBUG_REQUIREMENTS_TRACE=1 ENVCTL_DEBUG_DOCKER_COMMAND_TIMING=1 ENVCTL_DEBUG_STARTUP_BREAKDOWN=1 envctl --headless`
2. Print diagnosis:
   - `envctl --debug-report`

Decision tree:
1. If `slowest_components` shows `adapter_command create` as top contributor:
   - Check `requirements.adapter.command_timing` in deep traces.
   - Verify Docker daemon cold-start/host pressure separately (`docker run -d` control sample).
2. If startup repeatedly recreates existing requirement containers:
   - Verify `requirements.adapter.port_mismatch` and `requirements.port_adopted` events.
   - Default policy is reuse (`ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY=adopt_existing`).
   - Temporary rollback policy: `ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY=recreate`.
3. If first startup after idle is slow:
   - Keep prewarm enabled (`ENVCTL_DOCKER_PREWARM=1`, default).
   - Tune `ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS` if needed.
4. If n8n startup dominates and not needed for current run:
   - Use temporary mitigation: `N8N_ENABLE=0`.

## Interactive input/spinner/state issues (recommended workflow)
1. Run one deep debug session:
   - `ENVCTL_DEBUG_UI_MODE=deep envctl`
2. Reproduce the issue once and exit.
3. Package bundle:
   - `envctl --debug-pack`
4. Print quick diagnosis:
   - `envctl --debug-report`
5. Share bundle path:
   - `envctl --debug-last`

Expected bundle artifacts include:
- `events.debug.jsonl`
- `events.runtime.redacted.jsonl`
- `timeline.jsonl`
- `anomalies.jsonl`
- `command_index.json`
- `diagnostics.json`
- `bundle_contract.json`

If diagnosis says `next_data_needed`, rerun with deep mode and keep strict redaction defaults.

Spinner visibility quick checks:
- Force spinner on in a real TTY:
  - `ENVCTL_UI_SPINNER_MODE=on envctl`
- Force spinner off:
  - `ENVCTL_UI_SPINNER_MODE=off envctl`
- Check spinner diagnostics in report output:
  - `envctl --debug-report`
  - Look for `spinner_disabled_reasons` and `missing_spinner_lifecycle_transition`.

Textual backend quick checks:
- Force Textual backend:
  - `ENVCTL_UI_BACKEND=textual envctl --dashboard`
- Use compatibility alias (maps to Textual, emits deprecation event):
  - `ENVCTL_UI_BACKEND=legacy envctl --dashboard`
- Force snapshot-only mode:
  - `ENVCTL_UI_BACKEND=non_interactive envctl --dashboard`
- If Textual cannot run (non-TTY/missing dependency), runtime falls back to safe non-interactive snapshot mode and emits `ui.fallback.non_interactive`.

Selector reliability quick checks:
- Default selector engine is Textual plan-style:
  - `envctl`
- Prompt-toolkit rollback path (for emergency terminal compatibility):
  - `ENVCTL_UI_SELECTOR_IMPL=planning_style envctl`
- `legacy` remains a compatibility alias for Textual:
  - `ENVCTL_UI_SELECTOR_IMPL=legacy envctl`
- In deep reports, look for selector diagnostics:
  - `selector_input_inactive`
  - `selector_input_low_throughput`
- Long-running Apple Terminal key-throughput investigation notes:
  - `docs/troubleshooting/interactive-selector-key-throughput-readme.md`
- Permanent write-up of the post-plan dashboard input bug and fix:
  - `docs/troubleshooting/service-launch-io-ownership.md`

## Python runtime vs shell fallback
- Default runtime is Python.
- To force shell fallback temporarily: `ENVCTL_ENGINE_SHELL_FALLBACK=true envctl --resume`.
- Compare `run_state.json` and `runtime_map.json` artifacts between runs when debugging parity issues.

## Wrong services are starting
- If `ENVCTL_SERVICE_<N>` is set, auto-discovery is disabled.
- Remove/fix explicit service entries.

## Infra not starting as expected
Check toggles:
- `ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE`
- PostgreSQL and Supabase toggles
- `REDIS_*`
- `N8N_*`

## Planning files are not found
- Check `ENVCTL_PLANNING_DIR` in `.envctl`.
- Verify files exist under that directory and are `.md` files.
- Use `envctl --plan` interactively to confirm discovery.
