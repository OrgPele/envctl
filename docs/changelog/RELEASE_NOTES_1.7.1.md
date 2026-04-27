# envctl 1.7.1

`envctl` 1.7.1 is a hotfix release on top of `1.7.0`. It ships the plan-agent dependency bootstrap fix so AI implementation sessions do not start inside newly created worktrees before backend and frontend dependencies are ready.

## Why This Hotfix Matters

The 1.7.0 release made plan-agent launch workflows easier to start, but newly synced implementation worktrees could still reach the AI prompt before local dependency artifacts existed. In Supportopia-shaped projects, that meant a plan-agent could begin work in a tree without `backend/venv` or installed frontend dependencies even though envctl already had bootstrap logic for normal service startup.

This hotfix moves dependency preparation ahead of plan-agent handoff while keeping the path dependency-only: it does not start application services and it does not run migrations.

## Highlights

### Dependency prep before AI handoff

- Plan-agent launches now prepare selected worktrees before submitting the implementation prompt.
- Backend and frontend preparation reuse the existing service bootstrap helpers and fingerprint/state files.
- Headless output reports dependency preparation progress before the launch summary.
- Bootstrap failures stop the launch before any prompt is submitted into a broken worktree.

### Prepared Python runner for configured backends

- Configured backend commands that start with generic Python (`python`, `python3`, or `python3.12`) now resolve through the prepared backend runtime.
- Poetry projects use `poetry run python ...` when Poetry is available.
- Requirements/venv projects use the worktree-local `backend/venv/bin/python`.
- Explicit commands such as `poetry run ...`, absolute paths, and relative paths remain authoritative.

### Safer plan worktree dependency strategy

- Plan-agent worktrees use per-worktree dependency artifacts instead of relying on shared `node_modules` or virtualenv symlinks from the base repo.
- Existing setup-worktree compatibility symlinks remain limited to their previous paths.
- Dependency-only bootstrap explicitly skips backend migrations, even when startup migrations are enabled.

### Prompt handoff cleanup

- The `implement_task` prompt now requires the final response to include both PR status and the PR URL, avoiding follow-up questions after automated implementation runs.

## Included Changes

- PR #144: Prepare dependencies before plan-agent handoff.

## Verification

Validated in the implementation/release worktree with:

- `python -m pytest tests/python -q` ✅
- `python -m pytest tests/python/runtime/test_prompt_install_support.py -q` ✅
- `/root/.local/bin/uvx ruff check <changed Python files>` ✅
- `/root/.local/bin/uvx basedpyright --level error <changed Python files>` ✅
- `git diff --check && python -m py_compile $(find python scripts -name '*.py' -type f | sort)` ✅
- `tmp/run_plan_agent_dependency_e2e.sh` ✅
- `TREE=... PYTHONPATH=... python - <<'PY' ... resolve_service_start_command(...) ... PY` ✅

Release-candidate validation before tagging:

- `.venv/bin/python -m pytest -q`
- `.venv/bin/python -m build`
- `.venv/bin/python scripts/release_shipability_gate.py --repo .`
- `git diff --check`
- `.venv/bin/python -m compileall -q python tests/python`
- `.venv/bin/ruff check --select F python tests/python`

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

After build, the artifacts are available under `dist/`.

## Upgrade Notes

- No data migration or manual config migration is required.
- Plan-agent launches can spend additional time preparing dependencies before prompt submission; this is intentional and visible through `planning.dependency_bootstrap.*` events plus concise headless progress lines.
- Backend migrations remain controlled by the existing startup migration setting and are skipped by dependency-only plan-agent bootstrap.

## Summary

`envctl` 1.7.1 hardens the 1.7 planning workflow by ensuring generated implementation worktrees are dependency-ready before an AI agent begins work, while preserving service-startup and migration boundaries.
