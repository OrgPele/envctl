# Envctl Import Remote Branch Worktrees

## Goals / non-goals / assumptions

Goals:
- Add a user-facing `--import` flow that mirrors `--plan` worktree-and-agent launch behavior, but targets an existing remote branch instead of creating a new generated branch from a plan file.
- Fetch the selected remote branch, create or reuse a local Git worktree for that branch, pull it up to date, write envctl worktree metadata, and make the imported worktree eligible for the same Codex/OpenCode/OMX plan-agent launch paths that `--plan` uses.
- Preserve existing envctl-managed worktree protections: command-scoped Git hook disabling, shared artifact linking, code-intelligence setup, provenance state, project discovery, runtime scope flags, and headless launch reporting.

Non-goals:
- Do not create a plan file or seed `MAIN_TASK.md` from a plan during import unless the user explicitly supplies one later.
- Do not invent a new Git hosting integration. Use local Git plus the configured `origin` remote in the first implementation.
- Do not auto-create remote branches. `--import` is for branches that already exist remotely.
- Do not replace `--setup-worktree`, `ensure-worktree`, or `--include-existing-worktrees`.

Assumptions:
- Initial syntax should be `envctl --import <remote-branch-or-ref> [--cmux|--tmux|--omx] [runtime scope flags]`, with `--import=...` accepted for parity with `--plan=...`.
- Branch refs may be provided as `feature/foo`, `origin/feature/foo`, or `refs/remotes/origin/feature/foo`; envctl should normalize these to remote `origin/<branch>` and local branch `<branch>`.
- Imported worktrees should live under the existing trees root using a deterministic path such as `trees/imported/<slug>` unless the implementation discovers a stronger existing naming convention during the final code pass.

## Goal (user experience)

A user with an existing remote branch should be able to run one command, for example `envctl --import feature/my-branch --cmux --entire-system --headless`, and get a managed local worktree checked out at the remote branch tip. Envctl should fetch/pull that branch, report the imported project name and path, then launch the same implementation prompt workflow that `--plan` launches, without making a new generated branch like `features_task-1`.

## Business logic and data model mapping

- CLI token classification and route creation live in `python/envctl_engine/runtime/command_catalog.py` and `python/envctl_engine/runtime/command_router.py::parse_route()`.
- `--plan` currently maps to command `plan` through `COMMAND_ALIASES` in `command_catalog.py`, and route flags such as `--cmux`, `--tmux`, `--omx`, `--entire-system`, `--headless`, and `--new-session` are already parsed by the shared router.
- Plan-driven worktree sync lives in `python/envctl_engine/planning/worktree_sync_orchestration.py::sync_plan_worktrees_from_plan_counts()` and `sync_single_plan_worktree_target()`.
- Plan worktree creation lives in `python/envctl_engine/planning/worktree_domain.py::_create_feature_worktrees_result()` and `_run_worktree_add()`.
- The low-level Git command builder lives in `python/envctl_engine/planning/worktree_creation_commands.py::run_worktree_add()`, which currently chooses `git worktree add -b` or `-B` for generated branch names.
- Worktree identity is centralized in `python/envctl_engine/planning/worktree_identity.py::worktree_project_name()`.
- Provenance is written by `python/envctl_engine/planning/worktree_provenance.py::build_worktree_provenance()` and `write_worktree_provenance()`, currently recording source branch/ref for generated worktrees.
- Worktree shared artifacts and code-intelligence setup are already invoked by `_create_feature_worktrees_result()` via `_link_repo_local_shared_artifacts()` and `_prepare_worktree_code_intelligence()`.
- Plan-agent launch works with `CreatedPlanWorktree` from `python/envctl_engine/planning/plan_agent/models.py`, and downstream launch surfaces consume its `name`, `root`, `plan_file`, and optional `cli`.

No schema migration is required. Additive local state should be limited to the existing `.envctl-state/worktree-provenance.json` file, with new import fields such as `imported_branch`, `import_remote`, `remote_ref`, and `resolution_reason: "remote_branch_import"`.

## Current behavior (verified in code)

- `parse_route()` runs normalization, classification, command/mode resolution, flag binding, default scope/headless policy, plan-agent validation, and route finalization in `python/envctl_engine/runtime/command_router.py`.
- `command_catalog.py` registers `--plan`, `plan`, `--parallel-plan`, and related aliases as command `plan`; there is no `--import` command alias today.
- `command_catalog.py` already supports the launch and runtime flags this feature should reuse: `--cmux`, `--tmux`, `--omx`, `--codex`, `--opencode`, `--preset`, `--headless`, `--new-session`, `--entire-system`, `--only-backend`, `--only-frontend`, and `--no-infra`.
- `worktree_sync_orchestration.sync_single_plan_worktree_target()` derives a feature name from a plan file, compares desired counts against discovered projects, calls `create_feature_worktrees_result()`, then refreshes project discovery.
- `worktree_domain._create_feature_worktrees_result()` creates missing plan worktrees, writes provenance, prepares code intelligence, seeds `MAIN_TASK.md` from the plan, and appends `CreatedPlanWorktree(name=worktree_project_name(...), root=target.resolve(), plan_file=plan_file, cli=...)`.
- `worktree_creation_commands.run_worktree_add()` builds `git -C <repo> worktree add -b|-B <generated-branch> <target> [start-point]`, with `-B` used when `worktree_branch_exists()` finds `refs/heads/<branch>`.
- `worktree_creation_commands.worktree_start_point()` prefers provenance `source_ref`, then `source_branch`, then `HEAD`, so generated worktrees start from the current source branch or default branch.
- `tests/python/planning/test_worktree_creation_commands.py` covers generated branch naming, existing generated branch reset with `-B`, start-point selection, and hook-disabled command construction.
- `tests/python/planning/test_planning_worktree_setup_provenance.py` verifies plan/setup worktrees write provenance, use `origin/<source-branch>`, preserve provenance when reusing existing worktrees, and rewrite it when recreating.
- `docs/reference/commands.md` documents `--plan`, `ensure-worktree`, and plan-agent launch behavior, but does not document remote branch import.
- `docs/reference/configuration.md` documents `ENVCTL_WORKTREE_GIT_HOOKS` as applying to envctl-managed worktree creation for `--plan`, `--setup-worktree(s)`, and `ensure-worktree`; this feature should extend that policy to `--import`.

## Root cause(s) / gaps

- Envctl has a mature path for creating new managed worktrees from plan files, but no first-class route for importing an already-pushed remote branch into that same managed-worktree surface.
- The low-level Git worktree builder assumes envctl owns branch naming and should create or reset a generated local branch. Importing must instead track an existing remote branch and avoid replacing it with a generated name.
- Provenance currently describes the source branch used to seed a generated worktree, not the imported branch that is itself the worktree branch.
- Plan-agent launch expects `CreatedPlanWorktree` records, but import currently has no producer that can create those records without going through plan count sync.
- Docs and tests do not define how remote refs are normalized, how stale local branches are updated, or what should happen when the target worktree already exists.

## Plan

### 1) Add route parsing for `--import`

- In `python/envctl_engine/runtime/command_catalog.py`, add `--import` and `import` as command aliases mapped to a new command value, for example `import-worktree` or `import`.
- Add `--import` to the appropriate value/inline flag handling so both `envctl --import feature/foo` and `envctl --import=feature/foo` parse consistently. Keep positional `envctl import feature/foo` support if the router pattern for explicit commands makes that straightforward.
- Preserve existing launch/runtime flag parsing. `--import feature/foo --cmux --entire-system --headless` should produce one import command route plus the same plan-agent flags used by `--plan`.
- Add parser tests in `tests/python/runtime/test_cli_router_parity.py` for:
  - `--import feature/foo`
  - `--import=feature/foo`
  - `import feature/foo`
  - import with `--cmux`, `--tmux`, `--omx`, `--preset`, `--headless`, `--new-session`, and runtime scope flags
  - invalid missing branch argument

### 2) Introduce an import-specific worktree command builder

- Add a focused module such as `python/envctl_engine/planning/worktree_import_commands.py`, or extend `worktree_creation_commands.py` if the implementation stays small.
- Implement pure helpers first:
  - normalize branch input (`feature/foo`, `origin/feature/foo`, `refs/remotes/origin/feature/foo`)
  - reject empty refs, path traversal, wildcard refs, detached commit SHAs, and unsupported remotes in v1
  - derive a stable local branch name and project/worktree slug
  - build the fetch command: `git -C <repo> fetch origin <branch>:refs/remotes/origin/<branch>` or the safest equivalent that does not create/update the local branch unexpectedly
  - build worktree add command for first import: `git -C <repo> worktree add --track -b <branch> <target> origin/<branch>` when the local branch does not exist
  - build reuse/update command for existing local branch/worktree: fetch, then run `git -C <worktree> pull --ff-only` or `git -C <worktree> merge --ff-only origin/<branch>` after verifying the checked-out branch matches the requested branch
- Keep command-scoped hook disabling around `git worktree add`, matching `run_worktree_add()` and `ENVCTL_WORKTREE_GIT_HOOKS`.
- Do not use `-B` for imports by default. Resetting an existing local branch to the remote tip can discard local commits; require a later explicit force/recreate flag if that behavior is needed.
- Add unit tests beside `tests/python/planning/test_worktree_creation_commands.py` for normalization, command construction, existing branch reuse, ff-only pull, and local-divergence failure.

### 3) Add import orchestration that mirrors plan worktree creation without plan coupling

- Add a runtime/planning orchestration entrypoint, for example `python/envctl_engine/planning/worktree_import_orchestration.py::import_remote_branch_worktree()`.
- The orchestration should:
  - resolve the repo root from `runtime.config.base_dir`
  - compute target root under the existing trees root
  - fetch and verify the remote branch exists
  - create or reuse the worktree
  - update the worktree using ff-only semantics
  - link shared artifacts via the same helper path plan/setup worktrees use
  - prepare code intelligence via `_prepare_worktree_code_intelligence()`
  - write provenance with import-specific branch fields
  - return a `CreatedPlanWorktree`-compatible record with `plan_file=""` or a sentinel, plus the selected CLI if `ENVCTL_PLAN_AGENT_CLI=both` ever applies
- Factor any shared post-create setup from `_create_feature_worktrees_result()` if needed, but keep the first implementation narrow. Avoid broad refactors of plan sync.
- Ensure project discovery sees the imported worktree name after creation. If discovery currently assumes numeric iteration directories, add the smallest path-discovery extension needed for `trees/imported/<slug>` or choose a path shape that existing discovery already recognizes.

### 4) Route import through startup and plan-agent launch

- Add command dispatch support so the new import route can run before normal runtime startup, similar to how plan/setup worktree creation is prepared before launch.
- After import succeeds, pass the returned `CreatedPlanWorktree` tuple into the existing plan-agent launch path so `--cmux`, `--tmux`, and `--omx` behave like `--plan`.
- Headless output should report:
  - normalized branch
  - remote ref
  - local branch
  - worktree path
  - whether it created, reused, or updated the worktree
  - attach/recovery guidance from the existing launch layer when launch flags are used
- If no launch flag is supplied, import should still create/sync the worktree and print the project/path, but not force AI launch.
- Preserve existing default runtime scope behavior. For implementation-agent launches from this plan, use `--entire-system`.

### 5) Update docs, help, and command metadata

- Update `python/envctl_engine/runtime/help_text.py` with examples:
  - `envctl --import feature/foo --headless`
  - `envctl --import origin/feature/foo --cmux --entire-system --headless`
  - `envctl import feature/foo --tmux --codex --entire-system`
- Update `docs/reference/commands.md` to document import behavior, branch normalization, ff-only update policy, and how it differs from `--plan`.
- Update `docs/reference/configuration.md` so `ENVCTL_WORKTREE_GIT_HOOKS` explicitly applies to `--import`.
- If command discovery or feature definitions require updates, add the new command to `python/envctl_engine/runtime_feature_definitions.py` and command-list tests.

## Tests (add these)

Backend tests:
- Extend `tests/python/runtime/test_cli_router_parity.py` for `--import`, inline `--import=...`, explicit `import`, missing-argument failures, and compatibility with plan-agent/runtime flags.
- Add `tests/python/planning/test_worktree_import_commands.py` for remote-ref normalization, invalid input rejection, fetch/worktree/pull command construction, hook-disabled worktree add, existing local branch handling, and ff-only divergence failure.
- Add `tests/python/planning/test_worktree_import_orchestration.py` for create, reuse, pull/update, provenance writing, shared artifact linking, and code-intelligence preparation.
- Extend startup/launch tests near `tests/python/startup/test_startup_orchestrator_flow_*.py` or planning launch tests to verify imported `CreatedPlanWorktree` records flow into cmux/tmux/OMX launch paths.
- Extend `tests/python/runtime/test_command_dispatch_matrix.py` and `tests/python/runtime/test_engine_runtime_command_parity_help.py` if they assert command inventory/help output.

Frontend tests:
- None. This is CLI/runtime behavior.

Integration/E2E tests:
- Add a Git-backed temp-repo smoke test that creates a bare `origin`, pushes a branch, runs the import orchestration, and verifies the resulting worktree is on the local branch tracking `origin/<branch>` with files present.
- If an existing full runtime startup smoke harness covers `--plan`, add a focused import variant that uses `--headless --no-infra` for pure import and one `--headless --entire-system` launch-path assertion where fake launch dependencies keep it deterministic.

## Observability / logging

- Emit structured events for import normalization, fetch start/result, worktree create/reuse, ff-only update result, provenance write, and launch handoff.
- Include enough fields for diagnosis without leaking secrets: `branch`, `remote`, `remote_ref`, `local_branch`, `worktree_root`, `action`, `returncode`, and a short failure reason.
- On failure, distinguish missing remote branch, invalid branch syntax, local branch already checked out elsewhere, local worktree dirty/diverged, fetch failure, and pull/ff-only failure.

## Rollout / verification

- Recommended implementation launch scope: `--entire-system`. Although the feature is CLI-heavy, it hands off into the same plan-agent/runtime startup path as `--plan`, so full-stack E2E validation is useful.
- Recommended Codex cycles: `2`. This is a normal multi-file CLI/planning/runtime feature with Git command safety concerns and launch-path verification.
- Focused validation:
  - `uv run --extra dev python -m pytest tests/python/runtime/test_cli_router_parity.py`
  - `uv run --extra dev python -m pytest tests/python/planning/test_worktree_creation_commands.py tests/python/planning/test_worktree_import_commands.py`
  - `uv run --extra dev python -m pytest tests/python/planning/test_worktree_import_orchestration.py`
  - `uv run --extra dev python -m pytest tests/python/startup tests/python/runtime/test_command_dispatch_matrix.py tests/python/runtime/test_engine_runtime_command_parity_help.py -k "import or plan or worktree"`
- Manual smoke:
  - create a temporary bare origin with a remote branch
  - run `envctl --import <branch> --headless --no-infra`
  - verify the worktree path, branch tracking config, provenance JSON, and `git -C <worktree> pull --ff-only`
  - run `envctl --import <branch> --cmux --entire-system --headless` with fake or available launch prerequisites and verify launch handoff output

## Definition of done

- `envctl --import <branch>` imports an existing remote branch into a managed local worktree without creating a generated branch.
- Import fetches first and updates existing imported worktrees with ff-only semantics.
- Imported worktrees get provenance, shared artifact links, code-intelligence setup, and project discovery compatibility.
- `--cmux`, `--tmux`, and `--omx` launch paths can consume imported worktrees through the existing `CreatedPlanWorktree` flow.
- Help and reference docs explain syntax, safety behavior, and differences from `--plan`.
- Focused unit tests and a Git-backed smoke cover create, reuse/update, and failure modes.

## Risk register (trade-offs or missing tests)

- Branch names with slashes need careful slugging for project names and paths while preserving the real local branch name for Git operations.
- Existing local branches may be checked out in another worktree; Git will reject duplicate checkout unless the implementation detects and reports that clearly.
- A dirty or diverged imported worktree should fail safely instead of resetting user work.
- Discovery may need a small extension if the chosen imported path does not match the current `trees/<feature>/<iteration>` numeric convention.
- Remote names other than `origin` are intentionally out of scope for v1 unless implementation finds existing repo support that makes multi-remote handling cheap.

## Open questions

- None blocking. The plan assumes `origin` is the v1 remote and that import should fail safely on divergence rather than force-resetting local branches.
