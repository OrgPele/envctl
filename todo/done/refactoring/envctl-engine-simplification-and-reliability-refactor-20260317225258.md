# Envctl Python Engine Migration and Simplification Refactor

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Migrate orchestration-critical engine logic from Bash to Python to reduce defect rate in concurrency, state handling, and port lifecycle management.
  - Preserve user-facing CLI behavior (`envctl`, flags, interactive flow) while replacing fragile internal shell state with typed Python models.
  - Eliminate known startup loops and state inconsistencies by implementing deterministic planning, startup, retry, and resume contracts in Python.
  - Keep migration incremental so existing teams can continue using `envctl` during transition.
- Non-goals:
  - Rewriting project applications (backend/frontend code under target repos).
  - Changing top-level launcher binary name (`envctl`) or removing `.envctl`/`.envctl.sh` compatibility in this phase.
  - Big-bang cutover that replaces all shell code in a single release.
- Assumptions:
  - Python 3.12 is available (already a practical requirement in current engine paths, e.g. environment parsing in `/Users/kfiramar/projects/envctl/lib/engine/lib/env.sh:210-243`).
  - Bash wrapper remains for compatibility, but orchestration authority progressively moves to Python.
  - Existing feature toggles remain (`SUPABASE_*`, `POSTGRES_*`, `REDIS_*`, `N8N_*`).

## Goal (user experience)
Running `envctl --plan`, `envctl --tree`, and `envctl --resume` should be deterministic and boring: each project gets stable unique ports, status output always reflects actual listeners, infra retries converge consistently, and resume behavior is predictable with safe state loading.

## Business logic and data model mapping
- Current owning shell modules and call paths (source of truth today):
  - CLI parse and startup mode selection:
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_cli.sh:174` `run_all_trees_cli_parse_args`
    - `/Users/kfiramar/projects/envctl/lib/engine/main.sh:108-151`
  - Tree orchestration and parallel workers:
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_helpers.sh:1859` `run_all_trees_start_tree_projects`
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_helpers.sh:1564-1704` fragment write/merge
  - Service lifecycle and attach/retry:
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/services_lifecycle.sh:1746` `start_project_with_attach`
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/services_lifecycle.sh:1211` `start_service_with_retry`
  - Requirements lifecycle:
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_core.sh:697` `resolve_tree_requirement_ports`
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_core.sh:1463` `ensure_tree_requirements`
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_supabase.sh:1766` `start_tree_supabase`
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_supabase.sh:2108` `start_tree_n8n`
  - State/resume:
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1707` `resume_from_state`
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1799` `load_state_for_command`
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1919` `load_attach_state`
  - Runtime projection:
    - `/Users/kfiramar/projects/envctl/lib/engine/lib/runtime_map.sh:15` `write_runtime_map`
- Proposed Python ownership map:
  - `python/envctl_engine/cli.py`: argument parsing and command dispatch.
  - `python/envctl_engine/models.py`: typed models (`PortPlan`, `ServiceRecord`, `RunState`, `RequirementsResult`).
  - `python/envctl_engine/ports.py`: canonical port planner + reservation/locking.
  - `python/envctl_engine/requirements/`: postgres/redis/supabase/n8n lifecycle implementations.
  - `python/envctl_engine/services.py`: backend/frontend start/retry/attach.
  - `python/envctl_engine/state.py`: validated state read/write/merge/resume.
  - `python/envctl_engine/runtime_map.py`: canonical runtime projection output.
  - `python/envctl_engine/shell_adapter.py`: controlled execution of shell commands (docker, git, npm, bun, poetry, uvicorn).

## Current behavior (verified in code)
- Engine complexity concentration is high:
  - Largest modules by LOC: `requirements_supabase.sh` 2564, `state.sh` 2269, `services_lifecycle.sh` 2100, `run_all_trees_helpers.sh` 2083.
  - Largest by function count: `services_lifecycle.sh` 54, `requirements_supabase.sh` 53, `state.sh` 52.
- Global mutable runtime state in one process (`services`, `service_info`, `service_ports`, `actual_ports`, `SUPABASE_TREE_*`, `N8N_TREE_PORTS`) is initialized in `/Users/kfiramar/projects/envctl/lib/engine/main.sh:338-375`.
- Parallel startup/merge currently uses ad-hoc fragment files:
  - write fragment `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_helpers.sh:1564-1604`
  - merge fragment `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_helpers.sh:1653-1704`
- Resume/state handling is inconsistent:
  - validated load path exists for command mode (`/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1816-1844`),
  - but direct unvalidated `source` remains in resume and attach flows (`/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1727`, `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1928`).

## Root cause(s) / gaps
- Shell orchestration is handling too many concerns at once (CLI parsing, concurrency, state persistence, service supervision, infra orchestration), with no typed contracts.
- State representation is map/array based and mutable from many files, making key-shape bugs easy (e.g., `service_ports` semantics mismatch in `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1469-1470` vs persisted structure at `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:2025-2028`).
- Port lifecycle is duplicated in multiple places with separate fallback logic, causing drift between requested, assigned, and actual ports.
- Retry behavior is asymmetric across stacks: Supabase DB bind conflict retries exist (`/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_supabase.sh:1889-1968`), while n8n startup still fails fast on compose port conflicts (`/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_supabase.sh:2350-2353`).
- User-facing guidance is stale in critical recovery paths (legacy `./utils/run.sh` hints in `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:2098-2111`, `/Users/kfiramar/projects/envctl/lib/engine/lib/actions.sh:241`, `/Users/kfiramar/projects/envctl/lib/engine/lib/actions.sh:258`).
- Parallel race risk is real in app port reservation path (`/Users/kfiramar/projects/envctl/lib/engine/lib/services_lifecycle.sh:1818-1835`), which is a strong signal that a typed Python planner/reservation engine is justified.

## Plan
### 1) Introduce Python engine scaffold while keeping Bash entrypoint stable
- Keep `/Users/kfiramar/projects/envctl/lib/envctl.sh` as launcher.
- Add Python package skeleton under `/Users/kfiramar/projects/envctl/python/envctl_engine/`.
- Add thin Bash bridge in `/Users/kfiramar/projects/envctl/lib/engine/main.sh`:
  - if `ENVCTL_ENGINE_PYTHON_V1=true`, execute Python entrypoint;
  - else keep existing shell path.
- Add startup self-check in Python for version + required executables (`docker`, `git`, `lsof`, `npm`/`bun`, `poetry` where applicable).

### 2) Define typed domain contracts in Python before porting logic
- Add dataclasses/pydantic models:
  - `PortPlan(project, requested, assigned, final, source, retries)`
  - `ServiceRecord(name, type, cwd, pid, requested_port, actual_port, log_path, status)`
  - `RequirementsResult(project, db, redis, supabase, n8n, health, failures)`
  - `RunState(run_id, mode, services, requirements, pointers, metadata)`
- Enforce one canonical map shape for port mappings:
  - `port_to_service` and `service_to_actual_port` represented separately and serialized explicitly.
- Design serialization format:
  - state JSON (`*.state.json`) replacing sourced shell scripts for Python path,
  - compatibility exporter still writes legacy `.state` during transition.

### 3) Port deterministic planning + reservation first (highest ROI)
- Implement `ports.py`:
  - canonical port plan builder for backend/frontend/db/redis/n8n;
  - file-lock based reservation semantics with explicit owner metadata (replacing ad-hoc shared maps).
- Port logic sources from:
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/services_lifecycle.sh:1813-1843`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_core.sh:697-960`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_core.sh:963-1178`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_helpers.sh:1544-1559`
- Required behavior:
  - reservation always happens before start in parallel tree mode,
  - final port updates flow through one API,
  - planner outputs include source tags (`env`, `worktree_config`, `existing_container`, `retry`).

### 4) Port state/resume layer second (safety + usability)
- Implement `state.py` with:
  - strict path validation and header/schema validation,
  - safe parse (no `source`),
  - deterministic merge policy for dashboard multi-state view.
- Explicitly port and fix behavior from:
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1200-1309`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1421-1518`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:1707-1915`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh:2089-2112`
- Command projection API outputs only `envctl` resume/recovery commands.

### 5) Port requirements orchestrator with consistent retry policy
- Implement requirements modules:
  - `requirements/postgres.py`
  - `requirements/redis.py`
  - `requirements/supabase.py`
  - `requirements/n8n.py`
- Normalize bind conflict handling for all infrastructure:
  - detect collision,
  - pick next reserved port,
  - persist updated plan,
  - bounded retry with structured failure classification.
- Separate hard failures vs non-critical bootstrap failures for n8n owner setup:
  - startup availability failure blocks backend;
  - owner bootstrap endpoint mismatch logs warning and proceeds (unless strict mode enabled).

### 6) Port service startup/retry/attach and interactive status projection
- Implement `services.py`:
  - backend start (venv/poetry path),
  - frontend start (npm/bun path),
  - retry classifier for bind vs non-bind failures,
  - attach-to-running behavior with pid and listener verification.
- Replace implicit map writes with typed state updates.
- Ensure status and runtime map derive from `RunState` final ports only.

### 7) Rebuild CLI parsing and command runner in Python with compatibility
- Implement parser in Python (`argparse` or `typer`; prefer `argparse` for zero dependency).
- Keep existing aliases, but remove typo aliases (e.g., `tees=true`) in Python path.
- Define and enforce command exit-code contract in Python command runner:
  - `0` success,
  - `1` actionable failure,
  - `2` controlled quit/interrupt.
- Preserve current command surface (`stop`, `stop-all`, `blast-all`, `restart`, `logs`, `doctor`, etc.).

### 8) Transition strategy and compatibility gates
- Phase A:
  - port planner + state loader in Python behind `ENVCTL_ENGINE_PYTHON_V1`.
- Phase B:
  - requirements + services in Python, shell path still available as fallback.
- Phase C:
  - Python path default, shell fallback opt-in (`ENVCTL_ENGINE_SHELL_FALLBACK=true`) for one release window.
- Phase D:
  - remove dead shell paths after parity criteria are met.

### 9) Documentation and developer workflow updates
- Update architecture docs to present dual-engine period and final Python ownership.
- Add contributor docs for Python engine development (lint, tests, local debugging).
- Keep existing docs around flags/config; update internals and troubleshooting guidance to Python-first paths.

## Tests (add these)
### Backend tests
- Add Python unit tests under `/Users/kfiramar/projects/envctl/tests/python/`:
  - `test_port_plan.py` for deterministic assignment and reservation.
  - `test_state_loader.py` for safe load, merge policy, schema validation.
  - `test_requirements_retry.py` for uniform retry across db/redis/n8n bind conflicts.
  - `test_command_exit_codes.py` for command contract parity.
- Extend existing BATS parity suites:
  - `/Users/kfiramar/projects/envctl/tests/bats/services_lifecycle_ports.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/requirements_flags.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/planning_config.bats`

### Frontend tests
- Add `/Users/kfiramar/projects/envctl/tests/python/test_frontend_projection.py`:
  - verifies backend final port is projected to frontend env.
  - verifies auto-rebound frontend port propagates into status/runtime map.
- Keep BATS checks that parse CLI output for user-facing URL correctness.

### Integration/E2E tests
- Add dual-engine parity tests:
  - `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats`
  - run same scenarios in shell and Python modes and compare resulting state/runtime map.
- Add stress test:
  - `/Users/kfiramar/projects/envctl/tests/bats/parallel_trees_python_e2e.bats`
  - 3+ trees with infra enabled, asserts unique final ports and successful startup.
- Add resume safety test:
  - malformed/out-of-scope state files are rejected in Python mode.

## Observability / logging (if relevant)
- Emit structured JSON logs from Python engine:
  - `port.plan.requested`
  - `port.plan.assigned`
  - `port.plan.final`
  - `requirements.retry`
  - `service.start`
  - `state.resume.source`
- Add run-level artifacts:
  - `ports_manifest.json`
  - `run_state.json`
  - `error_report.json`
- Keep human-readable console output compatible with current UX.

## Rollout / verification
- Rollout gates:
  - Gate 1: Python planner + state parity vs shell on deterministic fixtures.
  - Gate 2: Python requirements/service startup parity on multi-tree scenarios.
  - Gate 3: Python default with rollback toggle.
- Verification checklist:
  - `envctl --plan` repeated runs do not reuse conflicting app ports.
  - resume/restart behavior is stable and safe.
  - no legacy `./utils/run.sh` hints remain in Python mode.
  - runtime map and displayed URLs always match actual listener ports.

## Definition of done
- Python engine owns planning, requirements, services, state, and runtime map in default path.
- Known bug vectors from current shell engine are covered by automated regression tests.
- Shell fallback remains optional and stable for one release window.
- Operator UX remains consistent (`envctl` commands unchanged), with improved reliability in multi-tree workflows.

## Risk register (trade-offs or missing tests)
- Risk: Mixed shell/Python phase increases short-term complexity.
  - Mitigation: strict feature gating, parity tests, explicit ownership boundaries per phase.
- Risk: External process behavior differs by platform when launched from Python.
  - Mitigation: shell adapter abstraction + OS-specific integration tests.
- Risk: Hidden dependencies in `.envctl.sh` hooks may break if evaluation timing changes.
  - Mitigation: maintain hook invocation points initially and add compatibility tests before tightening contract.
- Risk: Delivery can stall if migration tries to port everything at once.
  - Mitigation: port by defect density (planner/state first), enforce phase exit criteria.

## Open questions (only if unavoidable)
- Should Python mode support sourcing `.envctl.sh` directly, or only `.envctl` key/value format plus documented hooks?
- Do we keep legacy shell state files indefinitely, or enforce JSON-only state after the compatibility window?
