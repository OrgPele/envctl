# Envctl Workflow Efficiency And Worktree Identity

## Goals / non-goals / assumptions

Goals:
- Make generated worktree branch names, envctl project names, and user-facing
  `--project` selectors identical.
- Make envctl commands run from an envctl-generated tree directory load the
  owning parent repo `.envctl` automatically.
- Add a focused validation planning surface so agents run relevant tests during
  implementation instead of broad suites for every small change.
- Add a narrow handoff command that combines the existing commit and PR flow,
  then reports GitHub status-check state.
- Keep envctl-local artifacts protected from accidental commits through the
  existing global-excludes and commit-action protection policy.

Non-goals:
- Do not add background ship execution in this pass.
- Do not add `envctl status --handoff`.
- Do not change wrapper passthrough behavior such as `envctl playwright -- --help`.
- Do not make broad release-gate or full-suite validation mandatory for every
  implementation slice.

Assumptions:
- Generated worktrees continue to live under the configured trees root, usually
  `trees/<feature>/<iteration>`.
- Existing repo config may intentionally track `.envctl` in some repositories,
  so artifact protection must stay user-global or local-exclude based rather
  than editing repo `.gitignore`.
- The first version of focused test planning can be deterministic and
  rule-based; deeper import graph or CGC-powered impact analysis can be layered
  later.

## Goal (user experience)

An implementation agent working in a generated worktree should be able to use a
single unambiguous name for the project, branch, runtime services, tests, PR, and
handoff. During implementation it should ask envctl for the narrow relevant
checks to run, and at the end it should hand off with one command instead of
manually repeating `git status`, `git add`, `git commit`, `git push`, `gh pr`,
and `gh pr checks` commands.

## Business logic and data model mapping

- Worktree discovery and project identity live in
  `python/envctl_engine/planning/__init__.py` through
  `discover_tree_projects()`, `_append_feature_projects()`,
  `predict_plan_projects()`, and `planning_existing_counts()`.
- Worktree creation and branch naming live in
  `python/envctl_engine/planning/worktree_domain.py` through
  `_create_feature_worktrees_result()`, `_run_worktree_add()`, and
  `_worktree_branch_name()`.
- Explicit `ensure-worktree` behavior lives in
  `python/envctl_engine/runtime/ensure_worktree_support.py`.
- Runtime project contexts are built by
  `python/envctl_engine/runtime/engine_runtime_startup_support.py::contexts_from_raw_projects()`.
- Config loading starts in
  `python/envctl_engine/config/__init__.py::load_config()`, which calls
  `canonical_envctl_project_root()` and `discover_local_config_state()`.
- Existing commit and PR behavior lives in
  `python/envctl_engine/actions/project_action_domain.py::run_commit_action()`
  and `run_pr_action()`, with action routing through
  `python/envctl_engine/actions/action_command_orchestrator.py`.
- Existing test execution behavior lives in
  `python/envctl_engine/actions/action_test_runner.py::run_test_action()` and
  test-command discovery/config in `python/envctl_engine/actions/actions_test.py`
  plus config fields such as `ACTION_TEST_CMD`.
- Envctl-local artifact protection is centralized in
  `python/envctl_engine/config/local_artifacts.py`, enforced during commit by
  `_partition_envctl_protected_paths()`, and installed into Git global excludes
  by `python/envctl_engine/config/persistence.py::ensure_global_ignore_status()`.

No database schema migration is required. New persistent data should be limited
to optional JSON command output and, if needed, a small local metadata file under
`.envctl-state/` for ship/check status. That state must remain local-only.

## Current behavior (verified in code)

- `planning_feature_name()` derives a feature slug from the plan category and
  file stem, for example `features/foo.md` becomes `features_foo`.
- `worktree_domain._worktree_branch_name()` returns
  `f"{feature}-{iteration}"`, and `_create_feature_worktrees_result()` records
  created worktrees as `CreatedPlanWorktree(name=f"{feature}-{iteration}", ...)`.
- `discover_tree_projects()` derives project names from tree paths. For nested
  numeric iteration directories, `_append_feature_projects()` currently returns
  `f"{feature_name}-{iter_dir.name}"`.
- `ensure_worktree_support.run_ensure_worktree_command()` reports
  `project_name=f"{feature}-{iteration}"` and `branch_name=f"{feature}-{iteration}"`.
- `load_config()` chooses `requested_root` from `RUN_REPO_ROOT` or `Path.cwd()`,
  resolves `base_dir = canonical_envctl_project_root(requested_root)`, then
  calls `discover_local_config_state(base_dir, ENVCTL_CONFIG_FILE)`.
- Existing docs already claim that when envctl runs from a linked worktree it
  uses the owning main repo for `.envctl`, runtime scope, state files, port
  locks, and latest-run artifacts. This must be enforced by tests for the exact
  generated tree path shape.
- `run_commit_action()` already stages non-protected paths, resolves a commit
  message from `.envctl-commit-message.md` or env/config, commits, advances the
  ledger pointer, and pushes the branch.
- `run_pr_action()` already checks `existing_pr_url()` and creates a PR only
  when none exists; if the worktree is dirty, it delegates to `run_commit_action()`.
- `existing_pr_url()` currently uses `gh pr list --head <branch> --state open`.
  There is no product command that waits for PR checks and returns a structured
  status.
- `config/local_artifacts.py` currently marks `.envctl*`, `MAIN_TASK.md`,
  `OLD_TASK_*.md`, `trees/`, and `trees-*` as envctl-local artifacts.
- Config persistence tests verify global exclude entries are installed and that
  repo `.gitignore` is not modified.
- Commit-action tests verify protected envctl-local files are unstaged or
  skipped, including `MAIN_TASK.md` and `.envctl-state/worktree-provenance.json`.

## Root cause(s) / gaps

- Worktree project identity is currently inferred from directory layout and
  duplicated in multiple helper paths. The invariant that project name equals
  branch name is implicit, not validated end-to-end.
- Config discovery depends on the chosen base directory. The docs describe parent
  `.envctl` lookup from generated tree dirs, but the implementation needs a
  direct generated-worktree ownership resolver with tests for
  `<repo>/trees/<feature>/<iteration>`.
- Existing `commit` and `pr` actions are useful but are separate operational
  steps. There is no single command that performs commit + PR + check monitoring
  and returns a structured handoff result.
- Agents lack a deterministic, repo-native command for choosing focused tests
  from changed files. That pushes them toward broad test suites even for small
  implementation slices.
- Artifact protection exists, but the policy needs explicit coverage for the
  workflow files agents use most often, especially `.envctl-commit-message.md`,
  `MAIN_TASK.md`, `.envctl-state/`, and generated tree roots.

## Plan

### 1) Centralize generated worktree identity

- Add a small identity helper module, or a focused section in
  `planning/__init__.py`, that exposes one canonical function for generated
  worktree identity:
  - input: feature slug and iteration
  - output: branch name, project name, and worktree path segment
  - rule: branch name and project name are exactly identical
- Route `_worktree_branch_name()`, `predict_plan_projects()`,
  `_create_feature_worktrees_result()`, `_append_feature_projects()`,
  `planning_existing_counts()`, and `ensure_worktree_support` through that
  helper instead of open-coding `f"{feature}-{iteration}"`.
- Add validation that generated project names discovered from nested tree paths
  match the current branch when the worktree is a Git worktree and branch
  information is cheaply available.
- Keep the existing `features_foo-1` shape for compatibility unless a test
  proves there is already a different branch name in use. The required invariant
  is equality between branch and project, not a new naming format.
- Preserve plan-file inference helpers such as
  `project_action_domain._feature_name_from_project_name()` by updating their
  tests against the centralized identity helper.

### 2) Resolve parent repo config from generated tree directories

- Add a generated-worktree ownership resolver in config loading, before
  `discover_local_config_state()`:
  - detect when `requested_root` or `ENVCTL_EXECUTION_ROOT` is inside
    `<repo>/<trees_dir>/<feature>/<iteration>`
  - read `.envctl-state/worktree-provenance.json` when present to identify the
    owning repo root and original plan
  - fall back to path shape plus nearest ancestor containing `.envctl` and the
    configured trees directory
  - keep `execution_root` as the actual worktree so backend/frontend paths and
    command execution still point at the current worktree
  - set `base_dir` to the owning repo root for `.envctl`, runtime scope,
    planning dir, state, port locks, and tree discovery
- Make `ENVCTL_CONFIG_FILE` explicit override continue to win.
- Add a clear event/debug field for the resolved control-plane root versus
  execution root so failures are inspectable.
- Preserve inspect-only behavior when no `.envctl` exists and no parent config
  can be found.
- Ensure this logic does not walk outside the current repo arbitrarily. It
  should climb only through the current path's ancestors and stop at filesystem
  root or a Git boundary.

### 3) Add focused test planning

- Add a new command surface:
  `envctl test-plan --project <project> --json`.
- Initial implementation should be rule-based and fast:
  - collect changed files from `git diff --name-only`, `git diff --cached
    --name-only`, and untracked non-protected paths
  - map file prefixes to focused test groups
  - include the exact command strings to run
  - include a confidence level and a reason for each command
  - include a separate full-gate recommendation for broad/risky changes
- Suggested first ownership mapping:
  - `python/envctl_engine/planning/` -> `tests/python/planning`
  - `python/envctl_engine/actions/` -> `tests/python/actions`
  - `python/envctl_engine/config/` -> `tests/python/config`
  - `python/envctl_engine/startup/` -> `tests/python/startup`
  - `python/envctl_engine/runtime/` -> `tests/python/runtime`
  - `python/envctl_engine/requirements/` -> `tests/python/requirements`
  - `python/envctl_engine/ui/` -> `tests/python/ui`
  - prompt templates -> `tests/python/runtime/test_prompt_install_support.py`
  - contract JSON/scripts -> relevant generator parity tests plus
    `scripts/release_shipability_gate.py` only when the touched files require it
- Make `envctl test --project <project> --changed` or `--affected` a thin
  follow-up only after `test-plan` is useful; the first deliverable can be a
  planner that prints commands without executing them.
- Default policy:
  - during implementation: run focused commands from `test-plan`
  - before commit: run focused tests plus ruff for touched Python/test/script
    paths
  - before handoff: run broader validation only when `test-plan` marks the
    change broad, runtime-critical, or contract-affecting

### 4) Add a narrow ship command

- Add `envctl ship --project <project> --json`.
- Reuse existing action code rather than duplicating Git/PR behavior:
  - resolve the project context through existing action target selection
  - call the same commit logic as `run_commit_action()` so
    `.envctl-commit-message.md` and protected-path behavior stay consistent
  - call the same PR detection/creation path as `run_pr_action()` so a PR is
    only created if one does not already exist
  - add a check-monitoring step after PR detection/creation
- Implement GitHub checks with `gh` first:
  - identify the current branch
  - identify the PR URL/number
  - run a bounded `gh pr checks --watch` when available
  - fall back to `gh pr checks --json` polling if `--watch` is unavailable or
    unsuitable for JSON mode
  - return status values such as `clean_no_changes`, `committed_pushed`,
    `pr_exists`, `pr_created`, `checks_passed`, `checks_failed`,
    `checks_pending_timeout`, and `gh_unavailable`
- JSON output should include:
  - project name
  - project root
  - branch
  - commit sha when created
  - whether anything was committed
  - whether push happened
  - PR URL and whether it was created
  - checks state, failing checks, pending checks, and monitor duration
  - protected local artifacts skipped
- Plain output should remain concise and link to the PR.
- Do not add background execution yet. The command should be simple and
  composable enough that an agent or future subagent can run it while another
  implementation task continues.

### 5) Tighten artifact protection policy

- Keep `config/local_artifacts.py` as the policy source for files that envctl
  should not commit by default.
- Confirm whether `.envctl-commit-message.md` is intentionally covered by the
  `.envctl*` pattern. If yes, add an explicit test naming that file so future
  changes do not accidentally unprotect it.
- Add or extend tests for:
  - `.envctl-state/`
  - `.envctl-commit-message.md`
  - `MAIN_TASK.md`
  - `OLD_TASK_*.md`
  - `trees/`
  - `trees-*`
- Keep repo `.gitignore` untouched. Continue using Git global excludes from
  config save/bootstrap and commit-action protected-path filtering.
- Add docs that distinguish:
  - repo configuration that may be intentionally tracked
  - envctl runtime/task artifacts that should stay local
  - generated tree roots that should never be committed from the parent repo

### 6) Update prompts and docs to use the efficient workflow

- Update implementation/finalization prompt templates to prefer:
  - `envctl test-plan --project <current-worktree-name> --json` during coding
  - focused test commands from that output
  - `envctl ship --project <current-worktree-name> --json` for final handoff
- Keep guidance that full validation is required for broad/risky changes, but
  stop making full-suite validation sound mandatory for every tiny change.
- Update `docs/user/ai-playbooks.md`, `docs/user/planning-and-worktrees.md`, and
  relevant help text with the project-name-equals-branch invariant and the
  focused-test/handoff flow.

## Tests (add these)

Backend tests:
- `tests/python/planning/test_planning_worktree_setup.py`
  - generated worktree branch, project name, created worktree name, and
    provenance identity match exactly
  - fresh AI worktree creation still targets the newly created identity
- `tests/python/runtime/test_ensure_worktree_support.py` or existing
  ensure-worktree tests
  - JSON output reports identical `project_name` and `branch_name`
- `tests/python/config/test_config_persistence.py` and
  `tests/python/config/test_config_command_support.py`
  - load config from `<repo>/trees/<feature>/<iteration>` using parent
    `<repo>/.envctl`
  - preserve worktree execution root for commands
  - explicit `ENVCTL_CONFIG_FILE` override wins
  - missing parent config preserves current non-interactive failure behavior
- `tests/python/actions/test_actions_cli.py`
  - ship command commits with `.envctl-commit-message.md`
  - ship skips protected envctl-local artifacts
  - ship creates PR only when none exists
  - ship reports existing PR without creating another
  - ship returns failed/pending/passed check status
- `tests/python/actions/test_actions_parity.py`
  - route-level action command orchestration for `ship`
  - artifact protection explicitly covers `.envctl-commit-message.md`
- New `tests/python/actions/test_test_plan_action.py`
  - changed config files recommend config tests
  - changed planning files recommend planning tests
  - changed prompt templates recommend prompt install support tests
  - broad/mixed changes recommend focused tests plus full-gate warning

Frontend tests:
- None expected for the first implementation. This is CLI/runtime workflow
  behavior, not browser-visible UI.

Integration/E2E tests:
- Add a temp-repo smoke test that creates an envctl worktree, runs envctl from
  inside that worktree, and proves parent `.envctl` was loaded.
- Add a fake-`gh` integration test for `envctl ship --json` covering commit,
  existing PR, new PR, and check failure status without network.
- Keep full release-gate validation as an optional final check for the
  implementation branch, not a default per-edit requirement.

## Observability / logging

- Emit a config discovery event or include debug-pack fields for:
  - requested root
  - execution root
  - control-plane/base repo root
  - config file path
  - config source
  - generated worktree provenance source when used
- For `test-plan --json`, include reasons and confidence for every command.
- For `ship --json`, include step timings and the exact final status so agents
  can decide whether to keep implementing or stop for a failed check.

## Rollout / verification

- Recommended Codex cycles: `7`.
  Rationale: this crosses config discovery, worktree identity, action commands,
  GitHub integration, tests, docs, and prompt guidance, with several edge cases.
- Intended launch scope: `--no-infra --headless --new-session`.
  Runtime services do not prove this change; focused unit and temp-repo CLI
  tests are the useful validation signal.
- Launch command:
  `cd <repo-root> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=7 envctl --plan features/envctl-workflow-efficiency-and-identity --cmux --no-infra --headless --new-session`.
- Implementation should be split into commits:
  1. identity helper and tests
  2. parent config discovery and tests
  3. `test-plan` command and docs
  4. `ship` command and fake-`gh` tests
  5. artifact policy tests and prompt/doc updates
- Run focused tests after each commit slice. Run ruff on touched Python/test
  paths. Run broader action/config/planning/runtime tests before PR handoff.

## Definition of done

- Generated worktree project names and branch names are identical everywhere
  envctl reports or selects them.
- Running envctl from a generated tree directory loads the owning parent `.envctl`
  while executing project commands against the current worktree.
- `envctl test-plan --project <project> --json` returns deterministic focused
  commands for common envctl code areas.
- `envctl ship --project <project> --json` commits from
  `.envctl-commit-message.md`, pushes, creates a PR only when needed, monitors
  checks, and returns structured status.
- Envctl-local artifacts remain protected from accidental commits and are present
  in the configured global excludes flow.
- Docs and prompt templates teach focused testing and the narrow ship handoff
  instead of repeated manual Git/GitHub command loops.

## Risk register

- Parent `.envctl` discovery can accidentally choose the wrong ancestor in
  unusual nested repositories. Mitigate with strict generated-worktree shape
  checks, provenance-first resolution, and explicit override precedence.
- `ship` can mask too much if it becomes a giant workflow. Keep it narrow:
  commit, push, PR if missing, check status, structured result.
- Focused test planning can under-select tests. Start with conservative
  mappings, expose confidence/reasons, and recommend full gates for mixed or
  contract-touching changes.
- Artifact protection can conflict with intentionally tracked `.envctl` files.
  Do not edit repo `.gitignore`; keep protection in global excludes and commit
  filtering, and document the distinction.
