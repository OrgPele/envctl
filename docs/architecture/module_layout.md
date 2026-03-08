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

## Shell layout

`lib/engine/lib` is grouped by domain:

- `actions/`, `config/`, `debug/`, `docker/`, `git/`, `planning/`, `requirements/`, `runtime/`, `services/`, `shared/`, `state/`, `ui/`, `worktrees/`

Root `*.sh` files remain as compatibility shims that source the grouped implementation.

## Shim policy

- Old Python flat module paths must remain importable until the migration is complete.
- Old shell library file paths must remain sourceable until parity cleanup explicitly removes them.
- New code and tests should prefer the grouped layout.
