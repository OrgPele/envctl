# Envctl Worktree CGC Backend Default Hardening

## Context and objective

The prior task, archived as `OLD_TASK_2.md`, implemented most of the envctl worktree code-intelligence isolation feature:
generated worktrees get unique Serena project names, deterministic CGC contexts, explicit `cgc index <worktree>
--context <context>` commands, `.envctl-state/code-intelligence.json` metadata, docs, and targeted test coverage.

The remaining issue is real CodeGraphContext backend reliability. The implementation currently leaves
`ENVCTL_WORKTREE_CGC_DATABASE` empty by default, so generated worktrees create CGC contexts without `--database`.
On this machine, a real generated-context index used CGC's FalkorDB-backed default path, failed to start FalkorDB
cleanly, fell back, and indexing sat without progress until manually killed. Because this branch also commits
`.cgcignore`, `ENVCTL_WORKTREE_CGC_INDEX=auto` can now trigger CGC indexing for generated envctl worktrees and hit that
flaky default backend path.

Objective: make the default generated-worktree CGC backend robust by defaulting worktree CGC context creation to
`kuzudb` when no explicit database is configured, while preserving explicit user/config overrides and the best-effort
non-fatal behavior from the prior task.

This is a follow-up hardening task, not a rewrite of the prior implementation.

## Remaining requirements (complete and exhaustive)

1. Fully implement a default CGC database backend for envctl-generated worktree contexts.
   - When `ENVCTL_WORKTREE_CGC_DATABASE` is unset or absent from config, `_worktree_cgc_database()` must return
     `kuzudb`.
   - `cgc context create <context>` must therefore include `--database kuzudb` by default for generated worktree CGC
     indexing.
   - Explicit env values must continue to win over config raw values.
   - Explicit config raw values must continue to win over the default.
   - Empty or whitespace-only env/config values must be treated as absent and must fall back to `kuzudb`.

2. Preserve opt-out and override behavior.
   - `ENVCTL_WORKTREE_CGC_INDEX=false` must still skip indexing.
   - `ENVCTL_WORKTREE_CODE_INTELLIGENCE=false` must still skip all code-intelligence bootstrap behavior.
   - A non-empty `ENVCTL_WORKTREE_CGC_DATABASE=<backend>` must still pass that backend to `cgc context create`.
   - Existing context handling must continue to treat "already exists" output as success and proceed to indexing.
   - Missing `cgc`, context creation failure, and index failure must remain non-fatal for worktree creation.

3. Persist and emit the selected default database clearly.
   - `.envctl-state/code-intelligence.json` must record `"cgc_database": "kuzudb"` when the default is used.
   - The `setup.worktree.code_intelligence.cgc_context` event must include `database="kuzudb"` when the default is used.
   - Attempted command metadata must show `["cgc", "context", "create", <context>, "--database", "kuzudb"]` by default.

4. Update docs and repo guidance.
   - `docs/user/planning-and-worktrees.md` must state that generated worktree CGC contexts default to `kuzudb`.
   - The docs must explain that `ENVCTL_WORKTREE_CGC_DATABASE=<backend>` overrides the default.
   - The docs must explain why the default exists: to avoid relying on CGC's global/default backend selection for
     generated worktrees.
   - Do not reintroduce references to the old `codegraph` CLI.

5. Do not retrofit existing worktrees as part of this task.
   - Existing already-created implementation worktrees may still have `.serena/project.yml` with `project_name:
     "envctl"` and may lack `.envctl-state/code-intelligence.json` because they were created before the prior fix.
   - This task must harden behavior for newly generated or regenerated worktrees.
   - Do not mutate sibling worktrees or paths outside the current repo root.

## Gaps from prior iteration (mapped to evidence)

Fully implemented in commits `2cad2a5` and `916789d`:

- Deterministic generated worktree identity exists in
  `python/envctl_engine/planning/worktree_domain.py::_worktree_code_intelligence_identity`.
- Copied Serena project config is rewritten by `_copy_worktree_serena_project_file` and
  `_rewrite_serena_project_name`.
- CGC indexing now calls `cgc context create <context>` before `cgc index <worktree> --context <context>`.
- Metadata is written to `.envctl-state/code-intelligence.json`.
- Docs describe generated Serena project names, CGC contexts, templates, and metadata.
- Targeted validation passed:
  - `uv run --extra dev pytest -q tests/python/planning/test_planning_worktree_setup.py` -> `44 passed`
  - `uv run --extra dev ruff check python/envctl_engine/planning/worktree_domain.py tests/python/planning/test_planning_worktree_setup.py` -> passed
- PR #232 checks passed for `ruff`, `build & shipability`, and `pytest`.

Remaining/partial:

- `_worktree_cgc_database()` currently returns `""` when no env/config value is present, so the default command is
  `cgc context create <context>` with no `--database`.
- Docs currently say users can set `ENVCTL_WORKTREE_CGC_DATABASE=kuzudb`, but they do not say `kuzudb` is the default.
- Existing tests cover explicit `ENVCTL_WORKTREE_CGC_DATABASE=kuzudb`, but not the default-unset path requiring
  `--database kuzudb`.
- Real machine evidence shows the empty default can select a flaky FalkorDB-backed path, fail to start FalkorDB cleanly,
  fall back, and then stall indexing.

Not implemented and not required:

- No retroactive migration for the current implementation worktree's `.serena/project.yml` or missing
  `.envctl-state/code-intelligence.json`.
- No CGC MCP server, no CGC backend implementation, and no old `codegraph` CLI behavior.

## Acceptance criteria (requirement-by-requirement)

- A generated worktree with `ENVCTL_WORKTREE_CGC_INDEX=true` and no `ENVCTL_WORKTREE_CGC_DATABASE` runs:
  - `cgc context create <generated-context> --database kuzudb`
  - `cgc index <worktree> --context <generated-context>`
- A generated worktree with `ENVCTL_WORKTREE_CGC_INDEX=true` and `ENVCTL_WORKTREE_CGC_DATABASE=<backend>` runs:
  - `cgc context create <generated-context> --database <backend>`
  - `cgc index <worktree> --context <generated-context>`
- Metadata for the default path records `"cgc_database": "kuzudb"` and includes the default database in the attempted
  context-create command.
- Metadata for the override path records the override backend.
- Existing tests for missing `cgc`, CGC launch failure, existing context, context failure, and index behavior remain
  green.
- Docs state the default backend and override behavior accurately.
- GitHub PR checks pass after the follow-up commit.

## Required implementation scope (frontend/backend/data/integration)

- Backend/Python engine:
  - Update `python/envctl_engine/planning/worktree_domain.py`.
  - Prefer the narrowest possible change around `_worktree_cgc_database()` and any helper needed to keep env/config
    precedence clear.
- Tests:
  - Update `tests/python/planning/test_planning_worktree_setup.py`.
- Docs:
  - Update `docs/user/planning-and-worktrees.md`.
- Frontend:
  - None.
- Data/migrations:
  - None.
- Runtime services:
  - None.

## Required tests and quality gates

Run all of the following after implementation:

- `uv run --extra dev pytest -q tests/python/planning/test_planning_worktree_setup.py`
- `uv run --extra dev ruff check python/envctl_engine/planning/worktree_domain.py tests/python/planning/test_planning_worktree_setup.py`
- A focused Python 3.12 smoke for the real-git fake-`cgc` test if available locally:
  - `python3.12 -m pytest -q tests/python/planning/test_planning_worktree_setup.py::PlanningWorktreeSetupTests::test_setup_worktree_real_git_smoke_writes_isolated_code_intelligence`

Recommended test additions or adjustments:

- Add or update a test proving the unset database path includes `--database kuzudb`.
- Keep the existing explicit database test proving `ENVCTL_WORKTREE_CGC_DATABASE=kuzudb` or another non-empty backend is
  respected.
- Add a test for whitespace-only `ENVCTL_WORKTREE_CGC_DATABASE` falling back to `kuzudb` if that can be done without
  duplicating excessive setup.
- Ensure metadata assertions cover the selected database for default and override paths.

## Edge cases and failure handling

- Empty or whitespace-only database env/config values fall back to `kuzudb`.
- Non-empty database values are sanitized using existing identity sanitization before being passed to CGC.
- If `cgc` is missing, no context-create or index command runs, and metadata still records the selected database and
  `cgc_available=false`.
- If `cgc context create` fails, worktree creation still succeeds, indexing is skipped, and metadata/events include the
  database, return code, and short stdout/stderr summaries.
- If `cgc context create` reports that the context already exists, indexing still runs with the generated context.
- If `cgc index` fails or hangs in real usage, envctl must still treat the subprocess result/failure as non-fatal within
  the current timeout/error behavior; this task only changes backend selection, not CGC internals.

## Definition of done

- New generated envctl worktrees default to `kuzudb` for CGC context creation when no database override is configured.
- User/config overrides for `ENVCTL_WORKTREE_CGC_DATABASE` still work.
- Metadata and events clearly record the selected database.
- Docs describe the default, override, and rationale.
- Targeted tests and Ruff pass locally.
- Follow-up commit is pushed to PR #232 or its successor.
- GitHub required checks pass.
