# Python Engine Architecture

This inventory records the current Python engine ownership boundaries for refactors. It is a source of truth for where behavior should move as large orchestration modules are thinned.

## Ownership Map

| Workflow area | Owner modules | Stable contracts |
| --- | --- | --- |
| CLI command dispatch | `python/envctl_engine/runtime/command_router.py`, `python/envctl_engine/runtime/engine_runtime.py`, `python/envctl_engine/runtime/engine_runtime_*` | supported flags, command exit codes, runtime feature matrix |
| Startup and resume | `python/envctl_engine/startup/startup_orchestrator.py`, `python/envctl_engine/startup/resume_orchestrator.py`, `python/envctl_engine/startup/*_support.py`, `python/envctl_engine/startup/*_domain.py` | startup logs, degraded handoff, truth reconciliation, `.envctl-state` run artifacts |
| Action commands | `python/envctl_engine/actions/action_command_orchestrator.py`, `python/envctl_engine/actions/action_*`, `python/envctl_engine/actions/project_action_domain.py`, `python/envctl_engine/actions/project_action_reports.py` | `test`, `pr`, `commit`, `review`, `migrate`, worktree action behavior and summaries |
| Planning and worktrees | `python/envctl_engine/planning/worktree_domain.py`, `python/envctl_engine/planning/worktree_orchestrator.py`, `python/envctl_engine/planning/menu.py` | plan selection, worktree provenance, `MAIN_TASK.md` seeding, code-intelligence metadata |
| Plan-agent launch | `python/envctl_engine/planning/plan_agent/` | launch config, transport intent, prompt workflow, readiness, recovery guidance, launch result events |
| Requirements | `python/envctl_engine/requirements/` | adapter API, dependency readiness, user/database setup, runtime dependency contract |
| Dashboard and terminal UI | `python/envctl_engine/ui/`, `python/envctl_engine/ui/dashboard/` | dashboard rendering, command loop behavior, selector interaction, terminal session handling |
| State and artifacts | `python/envctl_engine/state/`, `python/envctl_engine/runtime/engine_runtime_artifacts.py` | state model round trips, runtime-map projection, debug and readiness artifacts |
| Generated contracts | `python/envctl_engine/runtime_feature_inventory.py`, `scripts/generate_*.py`, `contracts/*.json` | runtime feature matrix, Python runtime gap report, parity manifest |

## Invariants

- Preserve every supported CLI flag and compatibility alias unless a task explicitly updates the public command contract.
- Keep `.envctl-state` artifact shapes backward compatible; add fields only when readers tolerate missing values.
- Do not change generated contract formats without updating the generator, checked-in artifact, and contract tests together.
- Keep prompt installation output and plan-agent preset names stable.
- Keep plan-agent launch semantics stable across `cmux`, `tmux`, `omx`, OpenCode, Codex, ULW, Superset, and `--new-session` paths.
- Keep startup degraded-completion and failure summaries tied to debug report paths users can inspect.
- Prefer owner modules for new code. Compatibility facades should delegate and avoid re-owning private behavior.

## Plan-Agent Transport Vocabulary

Transport selection now has a shared intent boundary in `python/envctl_engine/planning/plan_agent/intent.py`.

| Concept | Meaning |
| --- | --- |
| `transport` | selected launch surface: `cmux`, `tmux`, `omx`, or `superset` |
| `cli` | selected AI CLI after route flags and config precedence |
| `readiness_expectation` | readiness surface the launcher must prove before prompt submission |
| `route_launch_requested` | whether route flags explicitly asked envctl to launch an implementation surface |
| `surface_transport_warning` | validation reason for unsupported configured surface values |

`config.py` consumes the intent and continues to own environment parsing for prompt presets, Codex cycles, direct prompt behavior, ULW behavior, Superset options, and launch enablement.

## Change Guidance

- For structural symbol work, use Serena first: `find_symbol`, `get_symbols_overview`, and `find_referencing_symbols`.
- For broad graph checks, use CGC with the `Envctl` context.
- For literal strings, docs prose, config keys, and CLI flag text, use native search.
- Run the owner test suite for the module family you changed before the broader release gate.
