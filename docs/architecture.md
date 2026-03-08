# Architecture

`envctl` is split into a launcher and an engine.

- Launcher: resolves repo context, installs PATH entry, forwards commands.
- Engine: runs orchestration for services, infrastructure, logs, state, health, and diagnostics.

```mermaid
flowchart LR
  A["User / AI Agent"] --> B["envctl Launcher"]
  B --> C["Git Repo Resolution"]
  C --> D["envctl Engine"]
  D --> E["Services (backend/frontend)"]
  D --> F["Infrastructure (PostgreSQL/Redis/Supabase/n8n)"]
  D --> G["State, Logs, Health, Doctor"]
```

## Determinism
Determinism comes from:
- Consistent CLI entrypoint (`envctl`).
- Explicit mode/target flags.
- Config precedence (`env > .envctl/.envctl.sh > defaults`).
- Saved runtime state with resume flows.

## Dual Engine Transition
`envctl` now runs Python engine by default and keeps shell as an explicit fallback:
- Default: launcher sets `ENVCTL_ENGINE_PYTHON_V1=true`.
- Fallback: set `ENVCTL_ENGINE_SHELL_FALLBACK=true` to force shell runtime during migration.
- Python runtime enforces startup self-checks, normalizes command exit codes, and introduces typed contracts for ports/state/runtime projection.

### Python Engine Modules
The Python package lives under `python/envctl_engine/`:
- `cli.py`: argument normalization, startup checks, command exit-code contract (`0` success, `1` actionable failure, `2` controlled quit).
- `models.py`: typed dataclasses for `PortPlan`, `ServiceRecord`, `RequirementsResult`, `RunState`.
- `ports.py`: deterministic port planning + lock-file reservation.
- `state.py`: safe JSON state loading and deterministic merge policy.
- `runtime_map.py`: canonical runtime projection with `port_to_service` and `service_to_actual_port`.
- `requirements/*`: shared bind-conflict retry contract across postgres/redis/supabase/n8n.
- `shell_adapter.py`: explicit fallback adapter to the legacy shell engine.

## Runtime Artifacts
Python runtime writes deterministic artifacts under `${RUN_SH_RUNTIME_DIR}/python-engine/`:
- `run_state.json` (canonical state authority)
- `runtime_map.json` (project/service/URL projection)
- `ports_manifest.json` (requested/assigned/final ports + sources/retries)
- `error_report.json` (structured failure summary)
- `events.jsonl` (structured event log)
