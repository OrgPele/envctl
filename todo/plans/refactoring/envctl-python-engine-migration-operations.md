# Envctl Python Engine Migration Operations

## Runtime Selection
- Default runtime is Python.
- Shell fallback is opt-in via `ENVCTL_ENGINE_SHELL_FALLBACK=true`.
- To force Python explicitly: `ENVCTL_ENGINE_PYTHON_V1=true`.

## Rollback Steps
1. Export `ENVCTL_ENGINE_SHELL_FALLBACK=true`.
2. Re-run the previous command (`envctl --plan`, `envctl --resume`, etc.).
3. Confirm shell diagnostics with `envctl --doctor`.

## Python Runtime Artifacts
Artifacts are stored under `${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}/python-engine/`:
- `run_state.json`
- `runtime_map.json`
- `ports_manifest.json`
- `error_report.json`
- `events.jsonl`

## Known Failure Signatures
- `Missing required executables:`
  Install missing prerequisites (`docker`, `git`, `lsof`, and `npm` or `bun`).
- `No previous state found to resume.`
  Run a startup flow first (`envctl --plan`, `envctl --tree`, or `envctl --main`).
- `Unknown option: tees=true`
  Use `trees=true`, `--tree`, or `--trees`.

## Recovery Checklist
1. Run `envctl --list-targets` and verify expected projects are discovered.
2. Run `envctl --plan` and inspect `ports_manifest.json` for unique ports.
3. Run `envctl --resume` and confirm `runtime_map.json` URLs match service ports.
4. If required, run with shell fallback and compare outputs to isolate parity issues.
