# Envctl Global Ignore For Local Artifacts Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Stop mutating repo-local ignore files for envctl-owned local workflow artifacts during config save/bootstrap.
  - Move envctl’s ignore contract to a per-user Git global excludes workflow so local files such as `.envctl` and `MAIN_TASK.md` stop appearing as repo changes without being committed into project `.gitignore`.
  - Make the config wizard, headless `config` command output, and release/shipability checks reflect the new global-ignore source of truth.
  - Centralize the envctl artifact ignore inventory so new local-only workflow files are added in one place instead of drifting across docs, prompts, and tests.
- Non-goals:
  - Changing `.envctl` from a repo-local file to a user-global config file. The config file remains repo-local; only ignore management changes.
  - Reworking commit/PR behavior that consumes `MAIN_TASK.md` (`python/envctl_engine/actions/project_action_domain.py`).
  - Changing tracked planning files under `todo/plans/`.
  - Automatically deleting legacy `.gitignore` entries from arbitrary downstream repos; existing local repo ignores can remain until users clean them up manually.
- Assumptions:
  - The current minimum envctl local-only artifact set is grounded in repo evidence and should initially include:
    - `.envctl*` from `python/envctl_engine/config/persistence.py:ensure_local_config_ignored`
    - `MAIN_TASK.md` from `python/envctl_engine/planning/worktree_domain.py:_seed_main_task_from_plan` and `python/envctl_engine/actions/project_action_domain.py:_resolve_commit_message_source` / `_pr_body` / `_main_task_title`
    - `OLD_TASK_*.md` because `python/envctl_engine/runtime/prompt_templates/continue_task.md` instructs rotating `MAIN_TASK.md` into archived `OLD_TASK_<iteration>.md`
    - nested worktree roots under `trees/` from `python/envctl_engine/config/persistence.py:ensure_local_config_ignored`
    - flat worktree roots `trees-*` because `python/envctl_engine/planning/worktree_domain.py:_preferred_tree_root_for_feature` and `tests/python/planning/test_discovery_topology.py:test_discovers_flat_trees_dash_feature_roots` already support them
  - Global Git configuration is more sensitive than repo-local `.gitignore`, so envctl should not silently replace a user’s existing global excludes file.

## Goal (user experience)
When a user bootstraps or edits envctl config, envctl should keep `.envctl`, `MAIN_TASK.md`, archived `OLD_TASK_*.md`, and envctl-managed worktree roots out of normal `git status` by relying on the user’s global Git excludes setup instead of editing the repository’s `.gitignore` or `.git/info/exclude`. The wizard and CLI output should explain the global-ignore contract clearly, and release/readiness tooling should behave consistently when these files are ignored globally.

## Business logic and data model mapping
- Config persistence and save result contract:
  - `python/envctl_engine/config/persistence.py:save_local_config`
  - `python/envctl_engine/config/persistence.py:ConfigSaveResult`
  - `python/envctl_engine/config/persistence.py:ensure_local_config_ignored`
  - `python/envctl_engine/config/persistence.py:_ensure_ignore_patterns`
  - `python/envctl_engine/config/persistence.py:config_review_text`
- Interactive/bootstrap and headless command surfaces:
  - `python/envctl_engine/config/wizard_domain.py:ensure_local_config`
  - `python/envctl_engine/config/wizard_domain.py:edit_local_config`
  - `python/envctl_engine/config/wizard_domain.py:_save_message`
  - `python/envctl_engine/config/command_support.py:run_config_command`
  - `python/envctl_engine/config/command_support.py:_run_headless_config_command`
  - `python/envctl_engine/ui/textual/screens/config_wizard.py` review-step summary text
- Downstream consumers of envctl local workflow artifacts:
  - `python/envctl_engine/planning/worktree_domain.py:_seed_main_task_from_plan`
  - `python/envctl_engine/actions/project_action_domain.py:_resolve_commit_message_source`
  - `python/envctl_engine/actions/project_action_domain.py:_pr_body`
  - `python/envctl_engine/actions/project_action_domain.py:_main_task_title`
- Release/readiness behavior that already depends on Git ignore semantics:
  - `python/envctl_engine/shell/release_gate.py:evaluate_shipability`
  - `scripts/release_shipability_gate.py:main`
- Documentation surfaces that currently describe repo-local ignore mutation:
  - `docs/user/first-run-wizard.md`
  - `README.md`
  - `docs/reference/configuration.md`
  - `docs/developer/config-and-bootstrap.md`
  - `docs/user/getting-started.md`
  - `docs/user/python-engine-guide.md`

## Current behavior (verified in code)
- Saving config always writes the repo-local `.envctl`, then mutates repo-local ignore files:
  - `save_local_config(...)` calls `ensure_local_config_ignored(local_state.base_dir)` immediately after writing `.envctl`.
  - `ensure_local_config_ignored(...)` appends `.envctl*`, `trees/`, and `MAIN_TASK.md` to `<repo>/.gitignore`.
  - The same helper appends only `.envctl*` to `<repo>/.git/info/exclude`.
- The save-result contract is too coarse to describe where ignore changes happened:
  - `ConfigSaveResult` only exposes `ignore_updated: bool` and `ignore_warning: str | None`.
  - `config_review_text(...)`, `wizard_domain._save_message(...)`, and `_run_headless_config_command(...)` can only display generic ignore text, not “global ignore configured”, “global ignore missing”, or “global ignore requires consent”.
- Wizard/docs currently promise repo `.gitignore` edits:
  - `python/envctl_engine/ui/textual/screens/config_wizard.py` hard-codes review copy saying “`.envctl*, trees/, and MAIN_TASK.md will be added to .gitignore on save when possible.`”
  - `docs/user/first-run-wizard.md` says save “tries to add `.envctl*` and `trees/` to the repo `.gitignore`.”
- The artifact inventory is incomplete and split across unrelated modules:
  - `ensure_local_config_ignored(...)` does not cover `OLD_TASK_*.md`, even though prompt templates explicitly rotate `MAIN_TASK.md` into archived `OLD_TASK_<iteration>.md`.
  - `ensure_local_config_ignored(...)` does not cover `trees-*`, even though worktree discovery/creation supports flat roots through `_preferred_tree_root_for_feature(...)` and `_trees_root_for_worktree(...)`.
  - Worktree-local `.envctl-state/worktree-provenance.json` exists, but because it lives inside worktree roots it is effectively covered when the worktree root itself is ignored.
- Shipability already honors Git’s standard ignore stack:
  - `evaluate_shipability(...)` calls `git ls-files --others --exclude-standard -- <required scopes>`.
  - That means moving envctl artifacts from repo `.gitignore` to a global excludes file changes release-gate results even if no repo files change.
- Repo evidence shows envctl relies on these local files in daily workflows:
  - new worktrees receive `MAIN_TASK.md` copied from the selected plan via `_seed_main_task_from_plan(...)`
  - PR title/body and commit-message fallback logic read `MAIN_TASK.md` via `project_action_domain.py`
  - current envctl repo `.gitignore` still contains `.envctl*`, indicating the project itself is relying on repo-local ignores today

## Root cause(s) / gaps
- The ignore contract is implemented as repo mutation inside config persistence, which conflicts with the requested per-user/global workflow and leaks envctl-specific local files into tracked repo hygiene.
- There is no single authoritative helper for “envctl-owned local artifacts”, so new workflow files can appear in prompts or planning code without ever being added to ignore management.
- The current save-result/output contract cannot represent global-ignore bootstrap states such as “existing global excludes updated”, “global excludes missing”, or “user declined global config mutation”.
- Release-gate tests cover tracked/untracked required-scope behavior, but there is no regression proving envctl artifacts ignored through global excludes remain invisible to `--exclude-standard`.
- Global Git config mutation is a user-scope side effect and therefore needs an explicit bootstrap/consent policy; the current code has no such policy because repo `.gitignore` edits were comparatively low-risk.

## Plan
### 1) Define an authoritative envctl local-artifact ignore inventory
- Add a single source of truth under `python/envctl_engine/config/` for envctl local-only artifact patterns instead of embedding them inline inside `ensure_local_config_ignored(...)`.
- Seed the initial pattern list from verified repo evidence:
  - `.envctl*`
  - `MAIN_TASK.md`
  - `OLD_TASK_*.md`
  - `trees/`
  - `trees-*`
- Keep tracked planning assets out of this list:
  - `todo/plans/**` stays tracked by design (`docs/user/planning-and-worktrees.md`)
  - `docs/changelog/**` stays tracked
- Document why `.envctl-state/**` is not separately listed:
  - it is already nested under ignored worktree roots
  - adding a root-level `.envctl-state/` ignore would be speculative because repo-root `.envctl-state` is not a documented current contract

### 2) Replace repo-local ignore mutation with a global-excludes manager
- Replace `ensure_local_config_ignored(...)` with a helper dedicated to Git global excludes management, ideally in a focused module such as `python/envctl_engine/config/git_ignore.py` to keep subprocess/home-path logic out of general persistence code.
- The helper should:
  - resolve the current global excludes target from Git config rather than assuming repo-local files
  - preserve any existing user-managed content in that file
  - add/remove only an envctl-managed block so repeated saves stay idempotent
  - stop writing `<repo>/.gitignore`
  - stop writing `<repo>/.git/info/exclude`
- Bootstrap policy should be explicit:
  - if a global excludes file is already configured, update it in place
  - if no global excludes file is configured, do not silently overwrite unrelated global Git state
  - instead, either:
    - add an explicit one-time consent path during interactive config save, or
    - return a structured warning telling the user how to enable envctl’s global ignore setup
- Keep the helper narrow:
  - only manage envctl’s artifact block
  - never reformat the whole user file
  - never delete non-envctl ignore rules

### 3) Expand the save-result contract so UX can report global-ignore state precisely
- Extend `ConfigSaveResult` beyond the current boolean `ignore_updated` so downstream callers can distinguish:
  - `updated_existing_global_excludes`
  - `already_present`
  - `missing_global_excludes_configuration`
  - `permission_or_write_failure`
  - `user_declined_global_git_config_change` if interactive consent is added
- Keep compatibility for existing JSON callers where possible:
  - retain `ignore_updated` as a coarse boolean if needed
  - add structured fields such as `ignore_scope`, `ignore_target_path`, and/or `ignore_status`
- Update:
  - `python/envctl_engine/config/wizard_domain.py:_save_message`
  - `python/envctl_engine/config/command_support.py:_run_headless_config_command`
  - `python/envctl_engine/config/persistence.py:config_review_text`
  so output explains the new global-ignore contract instead of referencing repo `.gitignore`

### 4) Rework interactive and headless config UX around the new contract
- Update the config wizard review step in `python/envctl_engine/ui/textual/screens/config_wizard.py` so it no longer promises repo `.gitignore` edits.
- If interactive consent is part of the chosen bootstrap policy, keep it in the config/bootstrap flow rather than hidden deep in persistence code so the user understands a global Git setting may change.
- Update `docs/user/first-run-wizard.md`, `README.md`, `docs/user/getting-started.md`, `docs/user/python-engine-guide.md`, `docs/reference/configuration.md`, and `docs/developer/config-and-bootstrap.md` to say:
  - `.envctl` remains repo-local
  - envctl local workflow artifacts are expected to be ignored through the user’s global Git excludes setup
  - repo `.gitignore` is no longer auto-mutated by envctl
- Add a short developer note in `docs/developer/config-and-bootstrap.md` covering the new ownership boundary:
  - repo-local persistence writes `.envctl`
  - user-global persistence manages envctl’s ignore block

### 5) Align release/readiness behavior and repository cleanup expectations
- Add coverage proving `python/envctl_engine/shell/release_gate.py:evaluate_shipability` behaves correctly when envctl artifacts are hidden by global excludes rather than repo `.gitignore`.
- Update this repository’s own ignore policy after the feature lands:
  - remove envctl-owned local-artifact entries from this repo’s tracked `.gitignore`
  - do not build code that auto-rewrites downstream repos’ tracked `.gitignore` files to remove historical entries
- Keep release-gate semantics unchanged for genuinely untracked required-scope files; only envctl local artifacts should disappear via standard Git ignore rules.

### 6) Add transition-safe diagnostics and migration guidance
- Emit bounded config events when ignore setup is attempted/completed/fails so bootstrap behavior remains diagnosable:
  - suggested event family: `config.ignore.global.updated`, `config.ignore.global.skipped`, `config.ignore.global.warning`
- Avoid emitting the full contents of the global ignores file; only emit status and the resolved path when useful.
- Add migration notes for operators:
  - existing repo `.gitignore` lines may remain temporarily and are harmless
  - new envctl versions will no longer add them
  - root-level `MAIN_TASK.md`/`OLD_TASK_*.md` visibility now depends on global excludes being configured

## Tests (add these)
### Backend tests
- Extend `tests/python/config/test_config_persistence.py`:
  - verify the new helper updates only the global excludes target and leaves repo `.gitignore` / `.git/info/exclude` untouched
  - verify idempotent envctl-managed block updates
  - verify the expanded artifact set includes `OLD_TASK_*.md` and flat `trees-*`
  - verify missing/unwritable global excludes configuration returns a structured warning instead of mutating repo files
- Extend `tests/python/config/test_config_command_support.py`:
  - verify JSON output includes the new ignore status fields
  - verify non-JSON output surfaces actionable global-ignore warnings when setup is incomplete
- Extend `tests/python/runtime/test_release_shipability_gate.py`:
  - add a repo fixture where `MAIN_TASK.md` or `.envctl` exists under required scopes but is ignored through a temporary global excludes configuration, and assert `evaluate_shipability(...)` stays green
  - keep a regression proving unrelated untracked files in required scopes still fail the gate
- Extend `tests/python/runtime/test_release_shipability_gate_cli.py`:
  - add one CLI-level regression that runs `scripts/release_shipability_gate.py` with a temporary global Git config / excludes file and verifies the output remains clean

### Frontend tests
- Extend `tests/python/config/test_config_wizard_textual.py`:
  - verify the review-step copy no longer promises repo `.gitignore` mutation
  - if interactive consent is added, cover the review/confirm state that introduces global Git configuration
- Extend `tests/python/config/test_config_wizard_domain.py`:
  - verify save messages reflect global-ignore outcomes correctly
  - verify interactive bootstrap/edit flows surface warnings instead of silently claiming local `.gitignore` updates

### Integration/E2E tests
- Prefer focused Python integration coverage over broad BATS for this change:
  - `tests/python/config/test_config_command_support.py` should exercise a real `config --set` / `config --stdin-json` save path against a temporary git repo plus temporary global Git config
  - `tests/python/runtime/test_release_shipability_gate_cli.py` should exercise the shipped CLI script against the same style of isolated global-config fixture
- No frontend/browser or runtime-startup E2E lane is required because startup behavior and service orchestration are unchanged.

## Observability / logging (if relevant)
- Keep new diagnostics at the config/bootstrap layer only.
- Emit status-oriented events, not full file contents:
  - whether envctl updated an existing global excludes file
  - whether no global excludes file was configured
  - whether a write failed or the user declined consent
- Avoid logging raw ignore-file bodies or unrelated user ignore patterns.

## Rollout / verification
- Implementation order:
  1. centralize the artifact inventory
  2. introduce the global-excludes helper and expanded `ConfigSaveResult`
  3. rewire config persistence/wizard/headless messaging
  4. add release-gate/global-excludes tests
  5. update docs
  6. clean this repo’s tracked `.gitignore` entries once the new contract is live
- Verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.config.test_config_persistence`
  - `PYTHONPATH=python python3 -m unittest tests.python.config.test_config_command_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.config.test_config_wizard_domain tests.python.config.test_config_wizard_textual`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_release_shipability_gate tests.python.runtime.test_release_shipability_gate_cli`
- Manual verification:
  - in a temporary git repo with no `.gitignore`, run `envctl config` and confirm `.envctl` is saved while repo `.gitignore` remains unchanged
  - create `MAIN_TASK.md` and verify `git status --short` stays clean when the configured global excludes file contains the envctl block
  - verify a repo with an existing user global excludes file keeps pre-existing lines unchanged
  - verify missing global-ignore bootstrap produces a clear actionable warning instead of a silent failure

## Definition of done
- Config save/bootstrap no longer edits repo `.gitignore` or `.git/info/exclude`.
- Envctl local-only artifacts are managed through a single authoritative global-ignore inventory.
- Wizard, CLI output, and docs consistently describe the global-ignore contract.
- Release-gate tests prove envctl artifacts ignored through global excludes do not create false shipability failures.
- This repo’s tracked ignore policy no longer carries envctl-only local artifact patterns once the new behavior is in place.

## Risk register (trade-offs or missing tests)
- Risk: mutating user-global Git config is a broader side effect than mutating repo `.gitignore`.
  - Mitigation: require explicit consent when envctl would need to create/configure a global excludes target, and preserve existing user content with an envctl-managed block.
- Risk: removing repo-local ignore mutation before a user has global excludes configured will make `.envctl` / `MAIN_TASK.md` appear as untracked files again.
  - Mitigation: return actionable warnings and keep docs/wizard copy explicit about the prerequisite.
- Risk: flat worktree roots (`trees-*`) are supported by discovery but were never part of the old ignore contract, so broadening the inventory could hide files users intentionally wanted visible.
  - Mitigation: scope the new patterns only to envctl-managed worktree root conventions and document the behavior change in migration notes.
- Risk: existing downstream repos may retain historical `.gitignore` entries, producing mixed local-vs-global ignore states during transition.
  - Mitigation: do not auto-delete downstream repo entries; limit automatic cleanup to this repository and document the transition as additive/safe.

## Open questions (only if unavoidable)
- None.
