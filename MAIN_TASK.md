# Envctl Imported Tree Discovery And Plan Memory

## Goal

When a repo has imported PR worktrees under `trees/imported/<branch-slug>`,
envctl should list and target each imported branch by its real checked-out branch
name. It must not collapse the whole imported directory into one project named
`imported`.

When a user opens `envctl --plan`, the planning selector should reflect current
worktree reality. Deleted old plan worktrees and old remembered selections should
not appear as active/preselected work.

When a user runs `envctl --tree` / `envctl --trees`, the target selector must
show each imported worktree as its own project row. The current bad rendering is
one row like `● imported  (project)` even though the repo has multiple imported
PR branch worktrees available locally.

## Current behavior (verified in code)

- `python/envctl_engine/planning/__init__.py::discover_tree_projects()` walks the
  configured trees root and calls `_append_feature_projects()` for each direct
  child.
- `_append_feature_projects()` only treats numeric or `iter-*` child directories
  as nested projects. Non-numeric children are ignored for nesting and the parent
  directory can be accepted as one project.
- `_branch_project_name_for_worktree()` already reads the real Git branch name,
  but it is only used for numeric nested iteration directories.
- In Pele, `git worktree list --porcelain` shows imported PR worktrees at
  `trees/imported/<branch-slug>`, each on a real branch such as
  `features_ai_answer_reliability_foundation-2`.
- Running repo-local envctl against Pele currently reports one project:
  `name="imported"`, `root="/Users/kfiramar/projects/pele-monorepo/trees/imported"`.
- Running the user-facing tree flow against Pele currently collapses the same
  topology into one selected project row, `● imported  (project)`, instead of
  showing the six or more imported branch worktrees individually.
- `python/envctl_engine/planning/worktree_selection_memory.py::initial_plan_selected_counts()`
  seeds the interactive `--plan` selector from remembered counts when no current
  existing worktree count is present.
- `python/envctl_engine/planning/worktree_plan_project_selection.py::select_plan_projects()`
  calls the planning prompt with raw projects from discovery, so stale selector
  state is especially confusing when discovery undercounts imported worktrees.

## Root cause(s) / gaps

- Worktree discovery assumes generated envctl worktrees use
  `trees/<feature>/<numeric-iteration>`. Imported branches use
  `trees/imported/<branch-slug>`, so the existing traversal does not descend
  into the imported branch directories.
- Real branch-name probing exists, but the topology gate prevents it from being
  used for imported worktrees.
- The `--tree` / `--trees` target list is downstream of the same discovery
  result, so the UI can only render one `imported` project until discovery
  returns one project per imported branch worktree.
- The planning selector can preserve old positive selections from memory even
  after the corresponding worktrees are gone. That makes `--plan` look like old
  worktrees still exist or are still selected.
- Local Git branches can outlive their worktrees. Plan existing counts must stay
  based on current discovered worktree paths, not branch refs.

## Sequenced implementation plan

### 1) Add discovery coverage for imported branch worktrees

- Extend `_append_feature_projects()` or add a small helper in
  `python/envctl_engine/planning/__init__.py` to detect direct child directories
  that are real Git worktrees even when their names are not numeric iterations.
- For each detected imported child worktree:
  - require `_looks_like_tree_project_root(child)` to stay true
  - require `(child / ".git").exists()` before branch probing
  - use `_branch_project_name_for_worktree(child)` as the project name
  - fall back to a deterministic safe name only if branch probing fails
  - dedupe by `project_name|child.resolve()`
- Preserve current generated-worktree behavior for
  `trees/<feature>/<1|2|iter-*>` and flat roots such as `trees-feature`.
- Do not probe arbitrary non-worktree directories such as `backend`,
  `frontend`, `node_modules`, or nested source trees.

### 2) Keep imported branch display and targeting branch-accurate

- Confirm that project contexts built from discovery keep branch names intact
  for `--project`, `--tree` / `--trees` target selection, `list-trees`, action
  targeting, and runtime status output.
- Add a regression test at the runtime/startup target-selection layer proving a
  raw imported topology renders/selects multiple imported branch projects, not
  one parent `imported` project. Cover the visible failure shape:
  `● imported  (project)` must be replaced by separate imported branch rows.
- Add tests for branch names containing slashes, for example
  `vk/8e38-production-secre`, so envctl preserves the real branch name in the
  project identity while still using the filesystem-safe directory slug as the
  path.
- If any downstream selector cannot accept slash-containing project names, fix
  that selector matching path instead of lying about the branch name.

### 3) Stop stale plan memory from preselecting deleted worktrees

- Change `initial_plan_selected_counts()` so current `existing_counts` are the
  only source of automatic positive selection by default.
- Either ignore remembered positive counts when `existing_counts[plan_file] == 0`
  or add a tiny pruning helper that drops remembered entries for plans with no
  discovered current worktree.
- Keep existing counts authoritative: if two current worktrees exist for a plan,
  the selector should seed `2`.
- Keep saved memory useful only as a UI preference when it does not conflict
  with current discovery. It should not resurrect old work.

### 4) Add focused regression tests

- In `tests/python/planning/test_planning_selection.py` or
  `tests/python/planning/test_worktree_identity.py`, create a temporary Git repo
  with `git worktree add -b <branch> trees/imported/<slug>` and assert
  `discover_tree_projects(repo, "trees")` returns the real branch project at the
  child path, not `("imported", trees/imported)`.
- Add a second discovery test for a branch with `/` in the branch name.
- Add a memory test in a planning selection or worktree selection memory test:
  remembered count is positive, existing count is zero, initial selected count
  becomes zero.
- Add a test proving stale local branches do not affect
  `planning_existing_counts()` unless a matching worktree is present in the
  discovered project list.

### 5) Verify against the live Pele reproduction

- From `/Users/kfiramar/projects/envctl`, run:
  `uv run --extra dev envctl --repo /Users/kfiramar/projects/pele-monorepo --list-trees --json`
- Expected result: the output has one project per imported PR branch under
  `trees/imported/*` and no synthetic `imported` project.
- Also verify the user-facing tree path from the envctl repo:
  `uv run --extra dev envctl --repo /Users/kfiramar/projects/pele-monorepo --tree`
  should show the imported PR worktrees as separate project rows instead of one
  `● imported  (project)` row. Use the actual local imported worktree count from
  `git -C /Users/kfiramar/projects/pele-monorepo worktree list --porcelain`; do
  not hard-code the count in implementation logic.
- Run an interactive or dry-run planning path where practical and confirm old
  plan worktrees are not preselected after deletion.

## Tests to add or extend

- `uv run --extra dev pytest -q tests/python/planning/test_planning_selection.py`
- `uv run --extra dev pytest -q tests/python/planning/test_worktree_identity.py`
- Add or extend a focused test file for
  `worktree_selection_memory.initial_plan_selected_counts()`.
- Add or extend a runtime/tree-selector test proving `--tree` sees the imported
  children individually and does not render one parent `imported` project.
- Run `uv run --extra dev ruff check python/envctl_engine/planning tests/python/planning`.
- Run `git diff --check`.

## Rollout / verification

- Recommended implementation launch scope: `--entire-system`.
- Rationale: the code change is CLI/planning focused, but the user-facing
  failure appears through envctl's main worktree selection and planning flows.
  Full runtime startup may no-op in repos without an app system, but the
  implementation workflow should keep the broad surface available.
- recommended_codex_cycles=1.
- Manual smoke should include the live Pele command above, because that is the
  exact topology that exposed the `imported` collapse.

## Definition of done

- `envctl --list-trees --json` against Pele lists the imported PR branch
  worktrees individually by their checked-out branch names.
- `envctl --tree` / `envctl --trees` against Pele shows the imported PR branch
  worktrees individually in the target selector; it does not show one
  `● imported  (project)` row for the imported parent directory.
- The project named `imported` no longer appears unless there is actually a real
  worktree checked out at `trees/imported`.
- `envctl --plan` initial counts are based on current discovered worktrees, not
  deleted worktrees or stale remembered selections.
- Generated envctl worktrees under numeric iteration directories keep their
  existing project/branch identity behavior.
- Focused tests and live smoke pass.

## Risk register

- Branch names with `/` can be valid Git branch names but awkward UI selectors.
  Preserve branch truth and fix selector matching if needed.
- Discovery must not recurse broadly through arbitrary source trees. Limit the
  new scan to direct children of a candidate feature directory and require real
  Git worktree markers before branch probing.
- Memory behavior may have been intentionally used to remember desired counts
  for future plan creation. Current worktree truth should win because stale
  preselection caused destructive cleanup confusion.
- The global `envctl` wrapper may lag repo-local code. Validate with
  `uv run --extra dev ...` until the implementation is installed.
