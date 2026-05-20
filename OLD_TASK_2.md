# Envctl Deep Codebase Refactor

## Goals

- Make the Python engine easier to change by shrinking the largest orchestration
  modules into clear ownership areas with stable contracts.
- Preserve every supported CLI flag, state artifact, prompt install behavior,
  runtime feature contract, and plan-agent launch path while moving code.
- Reduce the blast radius of changes in startup, action commands, worktree
  planning, requirements adapters, dashboard orchestration, and plan-agent
  transports.
- Split oversized tests into feature-owned suites that still prove the same
  public behavior and generated contract outputs.
- Add or tighten structural guardrails only after the refactor has created
  realistic module boundaries.

## Non-goals

- Do not redesign the CLI or remove compatibility commands.
- Do not resurrect the old shell runtime.
- Do not change plan-agent semantics, prompt presets, runtime state schemas, or
  generated contract formats except where a compatibility-preserving update is
  explicitly required by the refactor.
- Do not make application-service or infrastructure changes. This plan is about
  envctl's implementation quality.

## User experience goal

Contributors should be able to change one runtime area without reading several
thousand lines of unrelated orchestration code. A behavior change should have a
small implementation surface, a predictable test file, and a contract or
integration check that proves existing envctl workflows still work.

## Business logic and data model mapping

- Runtime command dispatch lives around
  `python/envctl_engine/runtime/engine_runtime.py`,
  `python/envctl_engine/runtime/command_router.py`, and the runtime feature
  contract generators.
- Startup orchestration lives around
  `python/envctl_engine/startup/startup_orchestrator.py`, including restart
  handling, service launch, plan-agent worktree handoff, degraded completion,
  truth reconciliation, and failure reporting.
- Action commands live around
  `python/envctl_engine/actions/action_command_orchestrator.py`, including
  `test`, `pr`, `commit`, `review`, `migrate`, self-destruct worktree actions,
  target resolution, summaries, and artifact persistence.
- Planning and worktree setup live around
  `python/envctl_engine/planning/worktree_domain.py` and
  `python/envctl_engine/planning/plan_agent/*`, including selection memory,
  worktree creation/sync/deletion, provenance, code-intelligence setup, transport
  launch, readiness, and recovery.
- Dependency and service bootstrap logic lives under
  `python/envctl_engine/requirements/`, with
  `python/envctl_engine/requirements/supabase.py` as the largest adapter.
- Dashboard and terminal UI ownership lives under
  `python/envctl_engine/ui/`, especially
  `python/envctl_engine/ui/dashboard/orchestrator.py` and rendering modules.
- The persistent data contracts are the existing state models, generated runtime
  feature matrix, generated Python runtime gap report, parity manifest, startup
  logs, debug reports, and `.envctl-state` artifacts. They must remain
  compatible.

## Current behavior verified in the repo

- `PythonEngineRuntime` is still a broad facade. Its symbol overview includes
  command dispatch, start/resume execution, project discovery, help/config,
  migrate hooks, doctor/debug/release-gate/dashboard actions, action commands,
  stop/blast cleanup, event/debug plumbing, requirement/service command
  resolution, hook bridging, Supabase reinit, listener waits, and truth helpers.
- `StartupOrchestrator` coordinates route validation, pre-stop/restart policy,
  project context selection, plan dry-runs, plan-agent worktree preparation and
  launch, disabled modes, run reuse, startup execution, success/failure
  finalization, degraded handoff, progress display, requirements startup,
  service startup, and handoff validation.
- `ActionCommandOrchestrator` owns target resolution, self-destruct worktree
  behavior, action execution for test/pr/commit/review/migrate, project action
  environment and artifact replacement, status and spinner output, migrate
  hints/logs, failed test collection, git-state summaries, and colorized output.
- `worktree_domain.py` combines plan selection, selection memory, menus,
  sync/create/delete operations, branch/ref handling, git hook policy,
  code-intelligence setup for Serena and CGC, provenance, `MAIN_TASK.md`
  seeding, and fresh AI worktree protection.
- Plan-agent transports are split by surface
  (`cmux_transport.py`, `tmux_transport.py`, `omx_transport.py`,
  `superset_transport.py`), but readiness, launch intent, prompt submission,
  failure context, and option mapping still share concepts that are easy to
  duplicate incorrectly.
- `requirements/supabase.py` is one of the largest production modules and mixes
  adapter configuration, service lifecycle, health/readiness, user/database
  setup, repair, and reinitialization concerns.
- Several test files are larger than many production modules:
  `tests/python/planning/test_plan_agent_launch_support.py`,
  `tests/python/actions/test_actions_parity.py`,
  `tests/python/runtime/test_engine_runtime_real_startup.py`,
  `tests/python/requirements/test_requirements_adapters_real_contracts.py`, and
  `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`.
- The repo already has useful structural contracts:
  `tests/python/shared/test_support_module_decoupling.py`,
  `tests/python/shared/test_utility_consolidation_contract.py`,
  `tests/python/shared/test_structure_layout.py`,
  `contracts/runtime_feature_matrix.json`,
  `contracts/python_runtime_gap_report.json`,
  `contracts/python_engine_parity_manifest.json`, and the scripts that generate
  them.
- CGC is healthy for this checkout with context `Envctl`; `cgc doctor` passes
  and `cgc stats --context Envctl` reports the indexed repo successfully.

## Root causes and gaps

- The Python migration preserved behavior well, but many compatibility facades
  still act as aggregation points instead of thin boundaries.
- Orchestrators coordinate too many lifecycle phases directly, so a small change
  to a launch mode, action summary, or runtime route often requires reading
  unrelated code.
- Test coverage is strong but clustered into very large files, making it harder
  to identify the contract that protects a particular module.
- Generated contract checks exist, but there is not yet a lightweight ownership
  map that tells contributors which module family owns each behavior.
- Transport launchers share semantic concepts but not enough shared vocabulary,
  which increases the risk of flag drift across `tmux`, `cmux`, `omx`,
  OpenCode, Codex, ULW, and new-session paths.
- Requirements adapters are too broad. Supabase should expose the same public
  adapter behavior through smaller lifecycle/config/health/user/database pieces.

## Sequenced implementation plan

### 1. Capture the current architecture and invariants

- Add a short architecture inventory document, for example
  `docs/reference/python-engine-architecture.md`, covering runtime, startup,
  actions, planning/worktrees, plan-agent transports, requirements, UI, state,
  and generated contracts.
- Include an ownership table that maps the current high-level workflows to the
  modules that own them.
- Record invariants that must not change:
  CLI flag behavior, `.envctl-state` artifact shape, generated contract
  contents, prompt install output, plan-agent launch semantics, and release gate
  expectations.
- Use Serena symbol/reference tools for structural navigation during the work.
  Use `cgc ... --context Envctl` for broad graph checks, complexity summaries,
  and dead-code candidates.
- Avoid adding hard size limits in this step. First create a measured baseline
  so later guardrails are defensible.

### 2. Thin `PythonEngineRuntime` into explicit runtime delegates

- Group existing runtime methods by responsibility before moving code:
  dispatch/help, project resolution, lifecycle start/resume/stop, action command
  entry points, debug/doctor/release-gate commands, dashboard/interactive
  commands, service command helpers, hook bridging, and truth/readiness helpers.
- Move cohesive method clusters into existing domain modules where they already
  exist. Add new modules only where there is no clear owner.
- Keep `PythonEngineRuntime` as the public facade for the CLI and tests, but
  reduce it to construction, delegation, and compatibility shims.
- Preserve dispatch behavior in `command_router.py` and any generated feature
  matrix output.
- Add focused tests around the facade/delegate boundary so a method move cannot
  silently change route selection, exit status, or output shape.

### 3. Decompose startup orchestration by lifecycle phase

- Extract plan-agent worktree preparation and launch handoff from
  `StartupOrchestrator` into a planning/startup coordinator with a narrow input
  and result object.
- Extract restart/reuse/pre-stop policy into a dedicated startup policy module.
- Extract success, degraded, and failure finalization into a renderer/finalizer
  module that owns user-facing summaries and debug report references.
- Extract requirement and service startup sequencing into a service bootstrap
  coordinator, while keeping the current readiness and truth reconciliation
  semantics.
- Keep `StartupOrchestrator.execute` as the main sequence owner. It should read
  as orchestration, not contain low-level launch and rendering details.
- Preserve tests that cover degraded handoff, plan-agent launch skip/resume,
  disabled modes, startup logs, and state truth.

### 4. Split action command orchestration into action-owned helpers

- Move target resolution and project scope selection into an actions target
  module.
- Move `test` action execution and failed-test summary formatting into a test
  action module.
- Move `migrate` hints, migration logs, and migration result reporting into a
  migrate action module.
- Move self-destruct worktree handling into a worktree action helper with clear
  safety checks.
- Move project action environment/replacement/artifact persistence into a
  reusable project action support module.
- Keep `ActionCommandOrchestrator` as the compatibility entry point, but make
  each action route call one focused helper.
- Split `tests/python/actions/test_actions_parity.py` into smaller action-owned
  test files after each helper extraction, preserving the same behavior
  assertions.

### 5. Separate planning worktree responsibilities

- Split `worktree_domain.py` along the existing responsibilities:
  selection/menu/memory, worktree sync/create/delete, provenance and
  `MAIN_TASK.md` seeding, git hook policy, fresh AI worktree protection, and
  code-intelligence setup.
- Keep the public functions that callers use stable during the first pass. Move
  implementations behind them, then simplify call sites once tests are green.
- Preserve the strict boundary that plan operations only edit inside the current
  checked-out worktree or generated plan worktrees.
- Preserve Serena and CGC setup behavior, including repo-local ignores and
  context selection.
- Add tests that make accidental sibling-worktree writes and hook-policy drift
  fail early.

### 6. Normalize plan-agent transport concepts

- Introduce shared transport vocabulary for launch intent, selected surface,
  prompt preset, readiness expectation, command preview, session identity,
  failure reason, and recovery guidance.
- Keep transport-specific modules for `tmux`, `cmux`, `omx`, OpenCode, Codex,
  superset, and recovery behavior, but route common option mapping and result
  rendering through shared helpers.
- Add tests that exercise the same option matrix across transports:
  `--cmux`, `--tmux`, `--omx`, `--codex`, `--opencode`, `--ulw`,
  `--no-ulw-loop`, `--new-session`, `--headless`, direct-prompt behavior, and
  skipped/resumed launches.
- Preserve `contracts/runtime_feature_matrix.json` generation and update the
  checked-in artifact only when the generator output changes intentionally.
- Keep OpenCode-specific readiness failures observable with enough context to
  diagnose the active command, expected prompt state, transport, and timeout.

### 7. Break requirements adapters into lifecycle components

- Start with `requirements/supabase.py` because it is the largest adapter.
- Separate configuration/env resolution, Docker/process lifecycle, health and
  readiness checks, database setup, QA/auth user setup, repair/reinit, and
  summary reporting.
- Keep the existing adapter API stable for callers in startup and runtime code.
- Add adapter-level tests that prove real contract behavior before and after the
  split.
- Apply the same pattern to other requirement adapters only where it reduces
  complexity without hiding important behavior behind generic abstractions.

### 8. Split oversized tests after production seams exist

- Split large tests by behavior owner, not by arbitrary line count:
  plan-agent launch options, transport readiness, action parity, runtime startup,
  requirement adapter contracts, and dashboard restart selector behavior.
- Prefer moving tests in the same commit as the production extraction they
  protect, so review can compare old and new assertions.
- Keep test names descriptive and preserve important fixtures to avoid losing
  coverage through mechanical movement.
- Add a lightweight structure test only after the largest modules have been
  reduced. The guard should detect new god modules and require an explicit
  waiver for legitimate aggregators.

### 9. Tighten generated contracts and release checks

- Re-run and update generated artifacts only when behavior or declared feature
  inventory intentionally changes:
  `scripts/generate_runtime_feature_matrix.py`,
  `scripts/generate_python_runtime_gap_report.py`, and
  `scripts/generate_python_engine_parity_manifest.py`.
- Keep `scripts/release_shipability_gate.py` passing throughout the refactor.
- Add contract tests for any new ownership map or architecture inventory if the
  repo should treat it as a maintained source of truth.
- Make import-cycle and structure-layout failures actionable by pointing to the
  owning module family.

### 10. Update contributor-facing documentation

- Update architecture docs after each major extraction, not only at the end.
- Keep `AGENTS.md` guidance aligned with actual tooling:
  Serena for symbol navigation and references, CGC for broad graph analysis,
  and native search for literal strings or already-open files.
- Add a short "how to change this area" note for runtime, startup, actions,
  planning, transports, requirements, and dashboard code.

## Tests

- Static checks:
  `uv tool run ruff check python tests scripts`.
- Shared structure and import checks:
  `uv run python -m pytest tests/python/shared/test_structure_layout.py
  tests/python/shared/test_support_module_decoupling.py
  tests/python/shared/test_utility_consolidation_contract.py`.
- Runtime dispatch and contract checks:
  `uv run python -m pytest tests/python/runtime tests/python/test_runtime_feature_inventory.py`.
- Startup orchestration checks:
  `uv run python -m pytest tests/python/startup tests/python/runtime/test_engine_runtime_real_startup.py`.
- Action command checks:
  `uv run python -m pytest tests/python/actions`.
- Planning and plan-agent checks:
  `uv run python -m pytest tests/python/planning`.
- Requirements adapter checks:
  `uv run python -m pytest tests/python/requirements`.
- UI/dashboard checks:
  `uv run python -m pytest tests/python/ui`.
- Contract generation checks:
  run the runtime feature matrix, Python runtime gap report, and parity manifest
  generators with the checked-in timestamps where applicable, then compare to
  the checked-in JSON artifacts.
- Final gate:
  run the repo release shipability gate and the full Python test suite before
  opening or updating a PR.

## Rollout and verification

- Use small implementation commits by ownership area:
  runtime facade, startup lifecycle, action commands, worktree domain,
  transports, requirements, tests, docs/contracts.
- After each ownership area, run the targeted test group plus ruff.
- After each transport or runtime dispatch change, regenerate and compare
  `contracts/runtime_feature_matrix.json`.
- After any public behavior or release-gate-affecting change, run the full
  release shipability gate before handoff.
- Recommended launch:
  `ENVCTL_PLAN_AGENT_CODEX_CYCLES=8 envctl --plan refactoring/envctl-deep-codebase-refactor --tmux --no-infra --headless --new-session`.
- `--no-infra` is intentional here: the plan concerns envctl's Python
  architecture, tests, contracts, and documentation. Starting project services
  would not prove this refactor and would add noise to validation.

## Definition of done

- The largest orchestrators are reduced to thin coordination layers or clearly
  justified facades.
- Each major runtime area has an obvious owner module and focused tests.
- Plan-agent transport flags and readiness behavior are covered by a shared
  option matrix.
- Supabase requirements behavior is preserved behind smaller components.
- Giant tests are split by behavior without losing assertions.
- Runtime feature matrix, Python runtime gap report, parity manifest, release
  shipability gate, ruff, and the full Python test suite pass.
- Documentation reflects the final ownership boundaries and tool guidance.

## Risk register

- Dynamic CLI dispatch can hide call sites from structural tools. Mitigation:
  keep behavior-level dispatch tests and generated feature matrix checks.
- Moving code may accidentally change user-facing text. Mitigation: preserve
  snapshot-like assertions around launch guidance, prompt install output,
  failure summaries, and release-gate messages.
- Generated contract files can drift during refactors. Mitigation: regenerate
  only intentionally and compare generator output in tests.
- Long-lived compatibility facades can become permanent. Mitigation: document
  each facade's owner and remove redundant wrappers once call sites are updated.
- Broad refactors can conflict with active plan-agent work. Mitigation: sequence
  by ownership area and avoid touching unrelated files in a commit.
- CGC and Serena indexes can lag after structural moves. Mitigation: let Serena
  refresh automatically, run `serena project health-check` if symbol results
  look stale, and refresh CGC with `cgc index . --context Envctl` after major
  structural changes.
