# Envctl Bash Deletion Ledger and Python Prune Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Delete every Bash implementation that is already migrated and behaviorally verified in Python.
  - Produce a deterministic ownership ledger so we can see exactly what is still unmigrated, partially migrated, or intentionally retained in Bash.
  - Convert shell-dependency tests into Python-first parity tests so shell deletions are safe and measurable.
  - Reduce `lib/engine/main.sh` to a minimal compatibility shim and remove `lib/engine/lib/*.sh` modules in phased waves.
- Non-goals:
  - Removing the `envctl` launcher (`/Users/kfiramar/projects/envctl/bin/envctl`, `/Users/kfiramar/projects/envctl/lib/envctl.sh`) in this phase.
  - Rewriting downstream project application code.
  - Breaking compatibility in one big-bang release without gates.
- Assumptions:
  - Python remains the default runtime (`ENVCTL_ENGINE_PYTHON_V1=true`) and shell fallback is transitional.
  - The current Python package under `/Users/kfiramar/projects/envctl/python/envctl_engine/` is the target authority for orchestration.
  - Existing planning standards are inferred from current refactoring plans because `/Users/kfiramar/projects/envctl/docs/planning/README.md` is still missing.

## Goal (user experience)
Users run `envctl` and never need to care about shell internals: behavior is Python-owned, deterministic, and tested. Shell files that are already migrated are gone. A generated ownership report clearly answers: “what Bash remains, why, and what is left to migrate (desired or explicitly out-of-scope).”

## Business logic and data model mapping
- Current invocation path:
  - `/Users/kfiramar/projects/envctl/bin/envctl` -> `/Users/kfiramar/projects/envctl/lib/envctl.sh:envctl_main` -> `/Users/kfiramar/projects/envctl/lib/engine/main.sh`.
  - Python dispatch path: `/Users/kfiramar/projects/envctl/python/envctl_engine/cli.py:run` -> `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`.
- Shell fallback bridge:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/shell_adapter.py:run_legacy_engine`.
  - Toggle points in `/Users/kfiramar/projects/envctl/lib/envctl.sh:173-179`, `/Users/kfiramar/projects/envctl/lib/engine/main.sh:119-125`, and `/Users/kfiramar/projects/envctl/python/envctl_engine/config.py` (`ENVCTL_ENGINE_SHELL_FALLBACK`).
- Shell implementation surface currently loaded when fallback path is active:
  - `/Users/kfiramar/projects/envctl/lib/engine/main.sh:128-161` sources all major shell modules (`run_all_trees_cli.sh`, `requirements_core.sh`, `requirements_supabase.sh`, `services_lifecycle.sh`, `state.sh`, `planning.sh`, etc.).
- Python ownership surface:
  - Routing/parsing: `/Users/kfiramar/projects/envctl/python/envctl_engine/command_router.py`.
  - Runtime/lifecycle: `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py`.
  - Ports and locks: `/Users/kfiramar/projects/envctl/python/envctl_engine/ports.py`.
  - Requirements orchestration: `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements_orchestrator.py` + `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/*.py`.
  - Services/retries: `/Users/kfiramar/projects/envctl/python/envctl_engine/service_manager.py`, `/Users/kfiramar/projects/envctl/python/envctl_engine/process_runner.py`.
  - State/runtime map: `/Users/kfiramar/projects/envctl/python/envctl_engine/state.py`, `/Users/kfiramar/projects/envctl/python/envctl_engine/runtime_map.py`.
  - Action commands: `/Users/kfiramar/projects/envctl/python/envctl_engine/actions_*.py`.
- Data/ownership artifacts relevant to deletion safety:
  - Parity manifest: `/Users/kfiramar/projects/envctl/docs/planning/python_engine_parity_manifest.json`.
  - Shipability gate: `/Users/kfiramar/projects/envctl/python/envctl_engine/release_gate.py` and `/Users/kfiramar/projects/envctl/scripts/release_shipability_gate.py`.

## Current behavior (verified in code)
- Python is default, but shell is still a first-class fallback path:
  - `ENVCTL_ENGINE_SHELL_FALLBACK=true` still routes execution to legacy shell runtime.
- `main.sh` still carries full shell runtime payload:
  - It retains extensive usage text and sources virtually all shell modules in fallback flow (`/Users/kfiramar/projects/envctl/lib/engine/main.sh:3-320`, `:128-161`).
- The shell codebase remains large and function-dense:
  - `lib/engine/lib/*.sh` is ~25,575 LOC and ~606 shell functions.
  - Python engine surfaces ~96 classes/functions today.
- Command-surface mismatch still exists between shell and Python parser:
  - Shell parser advertises ~105 long flags in `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_cli.sh`.
  - Python parser currently handles ~52 long flags in `/Users/kfiramar/projects/envctl/python/envctl_engine/command_router.py`.
  - Shell-only examples still present: `--docker`, `--stop-docker-on-exit`, `--parallel-trees`, `--parallel-trees-max`, `--setup-worktree(s)`, blast volume policy flags.
- Some tests still directly validate shell modules, not Python ownership:
  - `/Users/kfiramar/projects/envctl/tests/bats/default_mode_config.bats` sources `run_all_trees_cli.sh`.
  - `/Users/kfiramar/projects/envctl/tests/bats/planning_config.bats` sources `planning.sh`.
  - `/Users/kfiramar/projects/envctl/tests/bats/requirements_flags.bats` sources `requirements_core.sh`, `requirements_supabase.sh`, `ports.sh`.
  - `/Users/kfiramar/projects/envctl/tests/bats/services_lifecycle_ports.bats` and `/Users/kfiramar/projects/envctl/tests/bats/run_all_trees_helpers_ports.bats` source shell lifecycle/helpers.
- Parity manifest currently marks broad `python_complete`, but it does not drive deletion gating:
  - `/Users/kfiramar/projects/envctl/docs/planning/python_engine_parity_manifest.json` records status.
  - No current CI gate asserts “if python_complete, corresponding shell module/function must be removed or quarantined.”

## Root cause(s) / gaps
- No authoritative function-level ownership ledger exists (shell function -> Python owner -> parity evidence -> deletion status).
- Parity status is command-level and declarative, not linked to file/function deletion enforcement.
- Shell-centric tests still protect shell behavior, which blocks safe removal even when Python behavior exists.
- `main.sh` remains a monolithic compatibility runtime instead of a minimal shim.
- Fallback policy is global and coarse; there is no explicit quarantine boundary for remaining shell-only behaviors.
- No automated drift check catches reintroduction of already-migrated shell logic.

## Plan
### 1) Build a machine-readable ownership ledger (single source of truth)
- Add `docs/planning/refactoring/envctl-shell-ownership-ledger.json` with records:
  - `shell_module`, `shell_function`, `python_owner_module`, `python_owner_symbol`, `status`, `evidence_tests`, `delete_wave`, `notes`.
- Status values:
  - `python_verified_delete_now`
  - `python_partial_keep_temporarily`
  - `shell_intentional_keep`
  - `unmigrated`
- Seed the ledger from current modules loaded in `/Users/kfiramar/projects/envctl/lib/engine/main.sh:128-161` and from function extraction across `/Users/kfiramar/projects/envctl/lib/engine/lib/*.sh`.
- Add a generator script `scripts/generate_shell_ownership_ledger.py` to avoid manual drift.

### 2) Add hard deletion gates tied to ledger status
- Add a CI/local gate script `scripts/verify_shell_prune_contract.py` that fails when:
  - a function marked `python_verified_delete_now` still exists in shell,
  - a `python_complete` command in parity manifest has no mapped Python ownership/evidence in ledger,
  - deleted shell modules are still sourced by `/Users/kfiramar/projects/envctl/lib/engine/main.sh`.
- Extend `/Users/kfiramar/projects/envctl/python/envctl_engine/release_gate.py` to enforce:
  - ledger presence/validity,
  - parity-manifest ↔ ledger consistency,
  - no “delete_now” shell code survives.

### 3) Define shell quarantine boundary before deletions
- Split shell code into two explicit buckets:
  - `compat_shim` (minimal launcher/fallback adapter only).
  - `legacy_orchestration` (everything that Python should own).
- Refactor `/Users/kfiramar/projects/envctl/lib/engine/main.sh` into:
  - minimal Python bootstrap path,
  - optional isolated fallback entrypoint (`main_legacy.sh`) that is not the default integration path.
- Add a strict allowlist of shell files allowed post-prune (initially expected):
  - `/Users/kfiramar/projects/envctl/lib/envctl.sh`
  - `/Users/kfiramar/projects/envctl/lib/engine/main.sh` (reduced shim)
  - `/Users/kfiramar/projects/envctl/scripts/install.sh` (installer utility)
  - any explicitly approved fallback shim files.

### 4) Convert shell-direct tests to Python ownership tests
- Replace BATS tests that source shell libs with Python/BATS tests against Python runtime behavior:
  - `default_mode_config.bats` -> extend `/Users/kfiramar/projects/envctl/tests/python/test_cli_router.py` and `/Users/kfiramar/projects/envctl/tests/python/test_command_exit_codes.py`.
  - `planning_config.bats` -> extend `/Users/kfiramar/projects/envctl/tests/python/test_discovery_topology.py` and new planning-dir tests in Python runtime.
  - `requirements_flags.bats` -> move into `/Users/kfiramar/projects/envctl/tests/python/test_requirements_orchestrator.py`, `/Users/kfiramar/projects/envctl/tests/python/test_ports_lock_reclamation.py`, `/Users/kfiramar/projects/envctl/tests/python/test_engine_runtime_real_startup.py`.
  - `services_lifecycle_ports.bats` and `run_all_trees_helpers_ports.bats` -> consolidate into `/Users/kfiramar/projects/envctl/tests/python/test_service_manager.py` and runtime startup projection tests.
- Keep a minimal shell fallback smoke suite only for explicit fallback contract:
  - `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats` (reduced to shim verification only).

### 5) Delete migrated shell modules in waves (not all at once)
- Wave A (parser/config/planning modules where Python parity is already strong):
  - candidates from ledger likely include parts of `run_all_trees_cli.sh`, `planning.sh`, `runtime_map.sh`.
- Wave B (ports/requirements where Python tests fully cover behavior):
  - candidates from `ports.sh`, `requirements_core.sh`, `requirements_supabase.sh` after parity tests are complete and green.
- Wave C (service lifecycle/state orchestration):
  - candidates from `services_lifecycle.sh`, `state.sh`, `run_all_trees_helpers.sh` once targeted lifecycle and resume semantics are fully covered in Python tests.
- For each wave:
  - remove `source` lines from `main.sh`,
  - delete corresponding shell files/functions,
  - run full Python + BATS matrix,
  - update ledger + manifest + changelog.

### 6) Add unmigrated visibility report (the user-facing answer)
- Add `envctl --doctor` section “shell_migration_status” driven by ledger:
  - count by status bucket,
  - list of `unmigrated` and `shell_intentional_keep` items,
  - last updated timestamp and ledger hash.
- Add `scripts/report_unmigrated_shell.py` to output a plain table and JSON report for PRs.

### 7) Finalize cutover and remove fallback dependency
- When ledger has no `python_partial_keep_temporarily` / `unmigrated` items for desired scope:
  - remove `ENVCTL_ENGINE_SHELL_FALLBACK` behavior from runtime routing,
  - delete `python/envctl_engine/shell_adapter.py`,
  - replace shell fallback docs with archived migration notes.

## Tests (add these)
### Backend tests
- Add `/Users/kfiramar/projects/envctl/tests/python/test_shell_ownership_ledger.py`:
  - validates schema and required fields for every ledger row.
  - validates module/function references exist for non-deleted statuses.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_shell_prune_contract.py`:
  - ensures `python_verified_delete_now` shell functions no longer exist.
  - ensures `main.sh` does not source deleted modules.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_release_shipability_gate.py`:
  - assert gate failure when ledger/parity mismatch exists.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_engine_runtime_command_parity.py`:
  - assert parity manifest + ledger status coherence for all command families.

### Frontend tests
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_runtime_projection_urls.py` and `/Users/kfiramar/projects/envctl/tests/python/test_frontend_projection.py`:
  - ensure projection logic stays stable while shell runtime_map paths are removed.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_frontend_env_projection_real_ports.py`:
  - ensure no reliance on shell helper behavior remains for backend URL injection.

### Integration/E2E tests
- Add `/Users/kfiramar/projects/envctl/tests/bats/python_shell_prune_e2e.bats`:
  - runs with shell fallback disabled and validates no shell module sourcing in runtime path.
- Add `/Users/kfiramar/projects/envctl/tests/bats/python_doctor_shell_migration_status_e2e.bats`:
  - asserts doctor shows ledger-driven unmigrated summary.
- Keep and extend:
  - `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats` for shim-only fallback validation.
  - `/Users/kfiramar/projects/envctl/tests/bats/python_*.bats` matrix to guarantee behavior did not regress after each deletion wave.

## Observability / logging (if relevant)
- Emit structured events in Python runtime:
  - `shell.ledger.loaded`
  - `shell.ledger.mismatch`
  - `shell.prune.wave.start`
  - `shell.prune.wave.complete`
- Persist prune artifacts under runtime dir:
  - `shell_ownership_snapshot.json`
  - `shell_prune_report.json`
- Add doctor output fields:
  - `shell_ledger_hash`
  - `shell_unmigrated_count`
  - `shell_intentional_keep_count`

## Rollout / verification
- Phase 0: introduce ledger + generator + contract checks (no deletions).
- Phase 1: convert shell-direct tests to Python ownership tests.
- Phase 2: execute Wave A deletions and verify full suite.
- Phase 3: execute Wave B deletions and verify full suite.
- Phase 4: execute Wave C deletions and verify full suite.
- Phase 5: remove fallback route and final shell artifacts for migrated scope.
- Verification commands per wave:
  - `.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats --print-output-on-failure tests/bats/python_*.bats`
  - `bats --print-output-on-failure tests/bats/*.bats`
  - `.venv/bin/python scripts/release_shipability_gate.py --repo .`

## Definition of done
- A generated ownership ledger exists and is CI-enforced.
- Every shell function marked `python_verified_delete_now` is physically removed.
- `lib/engine/main.sh` is reduced to shim behavior and does not source orchestration modules already migrated.
- Shell-direct BATS tests for migrated functionality are removed/replaced with Python ownership tests.
- `envctl --doctor` reports precise unmigrated/intentional shell remainder.
- The team can answer at any point: “what shell remains, why, and what still needs migration?” from artifacts, not tribal knowledge.

## Risk register (trade-offs or missing tests)
- Risk: false confidence from command-level parity while function-level edge behavior differs.
  - Mitigation: function-level ledger rows + mandatory evidence tests per row.
- Risk: deleting shell modules can break fallback users unexpectedly.
  - Mitigation: quarantine fallback to explicit shim; wave-by-wave deletion with rollback tags.
- Risk: migrating tests away from shell can lose low-level behavior coverage.
  - Mitigation: replace each shell-direct test with Python behavior-equivalent tests before deletion.
- Risk: ownership drift (new shell code added after deletion waves).
  - Mitigation: prune-contract gate fails on new shell functions outside allowlisted shim files.

## Open questions (only if unavoidable)
- Should shell fallback remain as an explicitly supported long-term compatibility mode, or be fully removed after migration waves complete?
- Which shell files are intentionally retained forever (launcher/install ergonomics) vs scheduled for deletion?
- Do we want `ENVCTL_ENGINE_SHELL_FALLBACK` deprecated immediately after Wave C, or one release later?
