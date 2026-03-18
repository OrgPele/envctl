## 2026-03-18 - Nested flat worktree parity for custom `TREES_DIR_NAME`

Scope:
- Closed a planning/worktree parity gap for repositories that configure a nested trees root such as `work/trees` while still using flat feature roots like `work/trees-feature-a`.
- Kept the existing default `trees` behavior unchanged while aligning discovery and worktree root ownership for the nested custom-layout case.

Key behavior changes:
- `discover_tree_projects()` now derives the flat-root prefix from the configured trees directory basename, so `discover_tree_projects(repo, "work/trees")` correctly resolves `work/trees-feature-c/1` as `feature-c-1` instead of incorrectly surfacing raw iteration names like `1` and `2`.
- `_trees_root_for_worktree()` now resolves flat worktree roots relative to the configured trees parent directory, so setup/existing/recreate flows correctly recognize `work/trees-feature-a/<iter>` as belonging to the flat feature root rather than falling back to the nested `work/trees` directory.
- Runtime startup/worktree setup paths now preserve the correct project roots in state metadata when nested custom trees layouts are in use.

Files/modules touched:
- `python/envctl_engine/planning/__init__.py`
- `python/envctl_engine/planning/worktree_domain.py`
- `tests/python/planning/test_discovery_topology.py`
- `tests/python/runtime/test_engine_runtime_real_startup.py`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_discovery_topology tests.python.runtime.test_engine_runtime_real_startup` -> passed (`137` tests).
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_planning_selection tests.python.planning.test_planning_worktree_setup` -> passed (`27` tests).
- `PYTHONPATH=python python3 -m unittest discover -s tests/python/planning -p 'test_*.py'` -> passed (`66` tests).
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup` -> passed (`133` tests).

Config/env/migrations:
- No schema or migration changes.
- No new config keys were added; the fix applies to existing `TREES_DIR_NAME` values.
- Repository-local `.venv` was not present in this worktree, so validation was executed with `python3` plus `PYTHONPATH=python`.

Risks/notes:
- The change is intentionally narrow and only adjusts flat-root prefix/parent resolution for nested trees layouts.
- This does not change how nested roots are created in `_sync_plan_worktrees_from_plan_counts`; it only ensures discovery and worktree ownership stay correct when flat roots already exist for a nested trees directory configuration.
