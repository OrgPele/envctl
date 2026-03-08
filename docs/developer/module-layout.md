# Module Layout

## Python engine

`python/envctl_engine` is organized by domain:

- `actions/`: action execution, git/test/worktree action support
- `config/`: local config loading, persistence, wizard support
- `debug/`: debug bundle, diagnostics, doctor helpers
- `planning/`: planning discovery, planning menu, worktree planning
- `runtime/`: runtime facade, dispatch, lifecycle, startup support bridges
- `shared/`: cross-domain primitives such as parsing, process/port helpers, tooling
- `shell/`: shell parity and pruning contracts
- `startup/`: startup/resume/bootstrap orchestration
- `state/`: run-state models, repository, runtime-map, state actions
- `requirements/`: dependency adapters and requirement orchestration
- `ui/`: dashboard, command loop, selector, terminal integrations

## Import policy

- New implementation code should import from the domain package path, not from the deprecated flat top-level shim modules.
- Public compatibility shims remain at the old flat paths while the migration is in progress.
- `envctl_engine.config`, `envctl_engine.planning`, and `envctl_engine.state` are now package surfaces rather than flat modules.
- Capability probes belong in `python/envctl_engine/ui/capabilities.py`.
- Interactive command parsing belongs in `python/envctl_engine/ui/command_parsing.py`.
- Reusable selector target resolution belongs in `python/envctl_engine/ui/selection_support.py`.
- Shared Textual list navigation belongs in `python/envctl_engine/ui/textual/list_controller.py`.
- Shared prompt-toolkit list execution belongs in `python/envctl_engine/ui/prompt_toolkit_list.py`.
- New shared helpers should be imported from their owning module, not redefined locally.

## Orchestrator ownership

- `startup/*_support.py` and `resume_restore_support.py` are the behavior owners for startup and resume internals.
- `startup_orchestrator.py` and `resume_orchestrator.py` should compose those helpers and keep only compatibility wrappers or orchestration flow.
- `engine_runtime.py` and `engine_runtime_ui_bridge.py` should stay thin bridges over the shared UI and runtime support modules.

## Shell layout

`lib/engine/lib` is grouped by domain:

- `actions/`, `config/`, `debug/`, `docker/`, `git/`, `planning/`, `requirements/`, `runtime/`, `services/`, `shared/`, `state/`, `ui/`, `worktrees/`

Root `*.sh` files remain as compatibility shims that source the grouped implementation.

## Shim policy

- Old Python flat module paths must remain importable until the migration is complete.
- Old shell library file paths must remain sourceable until parity cleanup explicitly removes them.
- New code and tests should prefer the grouped layout.
