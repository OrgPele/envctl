# Envctl Prompt Overwrite Confirmation And Origin Review Preset Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Replace `install-prompts` backup-on-overwrite behavior with an explicit overwrite confirmation so user-local AI command directories do not accumulate `.bak-*` prompt commands.
  - Add a new built-in prompt preset for origin-side review of an implementation worktree, where the edited code lives in the created worktree and the unedited baseline remains in the current local repo.
  - Keep the current prompt installation and discovery model intact across Codex, Claude Code, and OpenCode.
  - Preserve the existing default cmux sibling workspace naming contract of `"<current workspace> implementation"` for plan-agent launches.
- Non-goals:
  - Deleting or migrating pre-existing `.bak-*` prompt files that users already have in their home directory.
  - Adding a second automatic post-`--plan` launch action into cmux surfaces.
  - Changing top-level envctl command names or creating a new runtime command family.
- Assumptions:
  - “Add another command” means “add another installable AI prompt preset/command file,” not “add a new top-level envctl CLI command.”
  - The new review preset is invoked manually from the original/local repo CLI after planning or implementation, and it receives the target worktree path/name via `$ARGUMENTS`.
  - Existing parsed approval flags (`--yes`, optionally `--force`) should be consumed by `install-prompts` for non-interactive overwrite approval rather than adding a new flag.

## Goal (user experience)
When users run `envctl install-prompts`, existing prompt files are not renamed to `.bak-*` siblings that later show up in Codex/OpenCode prompt pickers. Instead, envctl detects overwrite targets, asks once for confirmation in interactive mode, and overwrites the selected files in place. In addition, users can install a new built-in review preset from the local/origin repo CLI and run it against a generated worktree so the review command knows the edited code is in that worktree while the current local repo is the unedited baseline.

## Business logic and data model mapping
- Prompt installation ownership:
  - `python/envctl_engine/runtime/prompt_install_support.py`
    - `run_install_prompts_command(...)`
    - `_install_prompt_for_cli(...)`
    - `_available_presets()`
    - `_template_files()`
    - `_print_install_results(...)`
    - `PromptInstallResult`
    - `PromptTemplate`
- CLI routing and command-family ownership:
  - `python/envctl_engine/runtime/command_router.py`
  - `python/envctl_engine/runtime/command_policy.py`
  - `python/envctl_engine/runtime/engine_runtime_dispatch.py`
  - `python/envctl_engine/runtime/cli.py`
- Prompt template registry and current preset corpus:
  - `python/envctl_engine/runtime/prompt_templates/__init__.py`
  - `python/envctl_engine/runtime/prompt_templates/create_plan.md`
  - `python/envctl_engine/runtime/prompt_templates/implement_task.md`
  - `python/envctl_engine/runtime/prompt_templates/implement_plan.md`
  - `python/envctl_engine/runtime/prompt_templates/review_task_imp.md`
  - `python/envctl_engine/runtime/prompt_templates/continue_task.md`
  - `python/envctl_engine/runtime/prompt_templates/merge_trees_into_dev.md`
- Planning/worktree metadata already available for a future origin-review workflow:
  - `python/envctl_engine/planning/plan_agent_launch_support.py`
    - `CreatedPlanWorktree`
    - `PlanAgentLaunchConfig`
    - `resolve_plan_agent_launch_config(...)`
    - `_run_surface_bootstrap(...)`
    - `_slash_command(...)`
  - `python/envctl_engine/planning/worktree_domain.py`
    - `_select_plan_projects(...)`
    - `_create_feature_worktrees_result(...)`
  - `python/envctl_engine/startup/startup_orchestrator.py`
    - `_select_contexts(...)` launches plan-agent terminals after plan selection
- Config/env surface relevant to current launch behavior:
  - `python/envctl_engine/config/__init__.py`
    - `EngineConfig.plan_agent_preset`
    - `EngineConfig.plan_agent_cli`
    - `EngineConfig.plan_agent_cli_cmd`
    - `EngineConfig.plan_agent_cmux_workspace`
  - Docs:
    - `docs/user/ai-playbooks.md`
    - `docs/user/planning-and-worktrees.md`
    - `docs/reference/commands.md`
    - `docs/reference/configuration.md`

## Current behavior (verified in code)
- `install-prompts` installs prompt files directly from packaged markdown templates discovered by filename:
  - `python/envctl_engine/runtime/prompt_install_support.py:_available_presets()` returns every `.md` file under `python/envctl_engine/runtime/prompt_templates/`.
  - `_render_codex_template(...)`, `_render_claude_template(...)`, and `_render_opencode_template(...)` currently return the raw template body unchanged.
- Overwrite behavior currently creates backup files in the same command directory:
  - `python/envctl_engine/runtime/prompt_install_support.py:_install_prompt_for_cli(...)` computes `backup_path = _backup_path_for_target(...)` whenever the target file exists.
  - The same function calls `target_path.replace(backup_path)` before writing the new template body, then reports status `"overwritten"`.
  - `_print_install_results(...)` appends `(backup: <path>)` to text output whenever `PromptInstallResult.backup_path` is present.
- Backup naming is timestamped and prompt-file-local:
  - `python/envctl_engine/runtime/prompt_install_support.py:_backup_path_for_target(...)` emits `<stem>.bak-<timestamp>.<suffix>`.
  - `_backup_timestamp()` uses wall-clock time for the suffix.
- Existing tests and docs explicitly codify the backup behavior:
  - `tests/python/runtime/test_prompt_install_support.py:test_install_prompts_overwrites_existing_file_with_backup`
  - `docs/user/ai-playbooks.md` says “existing files are backed up in-place before overwrite”
  - `docs/reference/commands.md` says the same
- `install-prompts` already has router support for approval flags, but the utility command ignores them:
  - `python/envctl_engine/runtime/command_router.py` includes `--yes` and `--force` in `BOOLEAN_FLAGS`.
  - `run_install_prompts_command(...)` in `prompt_install_support.py` does not read either flag today.
- Current built-in prompts are six packaged templates:
  - `implement_plan`, `implement_task`, `review_task_imp`, `continue_task`, `merge_trees_into_dev`, and `create_plan`
  - `tests/python/runtime/test_prompt_install_support.py:test_template_registry_discovers_built_in_templates_by_filename` verifies this list.
- The current post-implementation review preset is worktree-local and mutating, not origin-side and comparative:
  - `python/envctl_engine/runtime/prompt_templates/review_task_imp.md` assumes the authoritative source is `MAIN_TASK.md` in the current checked-out repo and instructs the agent to validate, add tests, and make code improvements.
  - It does not describe comparing an edited worktree against the local/origin repo baseline.
- Plan-agent launch only supports one preset command typed into each created worktree CLI:
  - `python/envctl_engine/planning/plan_agent_launch_support.py:PlanAgentLaunchConfig` contains a single `preset` field.
  - `_run_surface_bootstrap(...)` computes one `prompt_text = _slash_command(launch_config.cli, launch_config.preset)` and submits exactly that command.
  - `python/envctl_engine/startup/startup_orchestrator.py:_select_contexts(...)` invokes `launch_plan_agent_terminals(...)` after plan-created worktrees are selected.
- The default sibling workspace naming contract is already present:
  - `python/envctl_engine/planning/plan_agent_launch_support.py:_default_workspace_target(...)` appends the suffix `" implementation"` to the current workspace title when no explicit workspace override is configured.
  - `docs/user/planning-and-worktrees.md` documents that envctl derives the target workspace name as `"<current workspace> implementation"` when enabled without an explicit override.
- Planning metadata already preserves the target worktree root and source plan file:
  - `CreatedPlanWorktree` includes `name`, `root`, and `plan_file`.
  - `python/envctl_engine/planning/worktree_domain.py:_create_feature_worktrees_result(...)` populates those fields.

## Root cause(s) / gaps
1. Prompt overwrites are implemented as file renames rather than as an approval workflow.
   - This is why `.bak-*` files remain in AI command directories and show up as extra prompt commands later.
2. The utility command has no explicit overwrite confirmation contract.
   - It neither prompts the user nor distinguishes interactive vs non-interactive overwrite requests.
   - It also ignores approval flags that are already parsed upstream.
3. The current preset corpus lacks a prompt for origin-side review of a generated implementation worktree.
   - `review_task_imp.md` is a mutate-and-harden prompt for the current repo, not a read-only or review-oriented compare-from-origin flow.
4. The current plan-agent launch model cannot satisfy “run another command from the CLI that created the plan” automatically without expanding the launch contract.
   - There is only one preset slot and it targets the created worktree surface, not the origin/local CLI surface.
5. Docs and tests currently reinforce the undesired overwrite and preset inventory behavior.
   - The behavior is not just code-local; it is encoded in user docs and regression suites.
6. The default workspace naming behavior exists today but is implicit relative to the requested prompt changes.
   - The implementation should preserve `"<current workspace> implementation"` as the default target whenever no explicit workspace override is set.

## Plan
### 1) Replace backup-on-overwrite with a single aggregated confirmation flow
- Update `python/envctl_engine/runtime/prompt_install_support.py:run_install_prompts_command(...)` to precompute the install plan before any writes:
  - resolve target paths for every selected CLI/preset pair
  - detect which targets already exist
  - collect overwrite candidates once for the whole command
- Remove backup-file creation from `_install_prompt_for_cli(...)`:
  - stop calling `_backup_path_for_target(...)`
  - stop renaming the existing target before writing
  - overwrite the file in place after approval
- Keep `PromptInstallResult.backup_path`, but make it `None` for all new writes so JSON output stays structurally stable for current callers.
- Preserve current `"written"` vs `"overwritten"` statuses so callers still know whether the target previously existed, but no `.bak-*` path is emitted.
- Introduce a single confirmation helper local to `prompt_install_support.py`:
  - prompt once when any overwrite candidates exist and `--dry-run` is false
  - summarize the affected prompt files/CLIs so the user understands what will be replaced
  - abort the whole command if the user declines
- Consume existing parsed flags from `route.flags` for automation-safe approval:
  - `--yes` should skip the prompt and approve overwrite
  - `--force` can be treated as an alias if maintainers want overwrite semantics to match other envctl commands that use force-style wording
- Do not prompt in contexts where prompt text would corrupt machine-readable output:
  - if `--json` is set and overwrite approval is required without `--yes`/`--force`, return a failed JSON payload instead of prompting
  - if stdin/stdout are not interactive TTYs and overwrite approval is required without `--yes`/`--force`, return a failed result instead of blocking on `input()`
- Ensure decline/failure happens before any target writes so partial overwrite state cannot occur.

### 2) Add a new origin-side review preset that compares a created worktree against the local repo
- Add a new packaged template file under `python/envctl_engine/runtime/prompt_templates/` using the same filename-driven registration model.
- Name the preset consistently with the current corpus, for example `review_worktree_imp.md`, so it is obviously related to `review_task_imp.md` but distinct in purpose.
- Base the template structure on existing prompt conventions from:
  - `review_task_imp.md` for review rigor and output shape
  - `create_plan.md` for research-first/read-only planning language
- The new preset should explicitly define its review model:
  - current local repo directory is the unedited baseline
  - target worktree path/name comes from `$ARGUMENTS`
  - edited code under review is in that target worktree
  - review should inspect the worktree’s `MAIN_TASK.md`, changed files, tests, and diffs against the local/origin repo
  - review output should be findings-first and read-only by default, not “fix code in place”
- Make the prompt body explicit about safe cross-worktree reads:
  - read-only access to the specified worktree is allowed for comparison
  - no writes should occur in the local/origin repo or the target worktree unless the user later asks for implementation work
- Reuse existing patterns for command inputs:
  - `$ARGUMENTS` should accept the target worktree path or name and optional reviewer notes
  - the prompt should instruct the agent how to resolve relative worktree paths from the current repo root
- Do not change `PlanAgentLaunchConfig` or automatic cmux launch behavior for this first scope.
  - The new review preset is installed and available for manual use from the origin/local CLI.

### 3) Update docs and command inventory references to match the new behavior
- Update prompt-install docs to remove backup language and document overwrite confirmation:
  - `docs/user/ai-playbooks.md`
  - `docs/reference/commands.md`
  - `docs/user/python-engine-guide.md`
- Update the built-in preset lists in docs to include the new review preset.
- Add a short usage note for the new review preset in `docs/user/ai-playbooks.md`:
  - explain that it is intended to be run from the local/origin repo CLI
  - explain that the target worktree path/name is passed as `$ARGUMENTS`
- Keep `docs/user/planning-and-worktrees.md` focused on current automatic plan-agent launch semantics unless maintainers explicitly want that page to advertise the manual origin-review follow-up step.

### 4) Extend tests to lock the new overwrite contract and preset inventory
- Replace backup-specific assertions in `tests/python/runtime/test_prompt_install_support.py` with overwrite-confirmation coverage:
  - existing file prompts once and overwrites in place after approval
  - no `.bak-*` file is created after overwrite
  - decline path exits with failure and leaves the original file unchanged
  - `--yes` (and `--force` if adopted) bypasses prompting
  - `--json` + overwrite-required without approval returns parseable failure payload and no prompt
  - non-TTY overwrite-required without approval fails cleanly rather than blocking on input
  - `--dry-run` against an existing file does not prompt and still reports planned work
- Update preset inventory tests in `tests/python/runtime/test_prompt_install_support.py`:
  - `_available_presets()` includes the new review preset
  - `--preset all` path-count expectations grow from 6 to 7
  - dry-run text output count for `codex: planned` increases accordingly
  - direct `_load_template(...)` smoke test validates the new template shape and core phrases
- Add/extend command-level exit-code tests in `tests/python/runtime/test_command_exit_codes.py`:
  - overwrite-required without approval returns exit code `1`
  - install-prompts still skips local-config bootstrap in these failure and success paths
- Keep router/dispatch tests unchanged unless the implementation decides `install-prompts` should explicitly document or normalize `--force` beyond the already-parsed boolean flag.

### 5) Preserve compatibility boundaries and avoid accidental migration scope creep
- Preserve the existing default workspace targeting rule in `python/envctl_engine/planning/plan_agent_launch_support.py`:
  - when `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` / `CMUX_WORKSPACE` is unset, envctl must continue deriving the sibling workspace title as `"<current workspace> implementation"`
  - docs and tests should continue to reflect that default behavior
- Keep `python/envctl_engine/planning/plan_agent_launch_support.py` unchanged for the initial implementation unless a concrete need emerges during coding.
- Do not add new config/env keys for a “second plan-agent command” in this scope.
- Do not auto-delete existing `.bak-*` prompt files from user home directories.
  - If maintainers later want cleanup, treat that as a separate migration/cleanup feature because it crosses into user-local state management.
- Keep `runtime_feature_inventory.py` untouched unless maintainers want the `install-prompts` notes field to mention the new overwrite contract and preset count.

## Tests (add these)
### Backend tests
- `tests/python/runtime/test_prompt_install_support.py`
  - Replace backup assertions with confirmation, decline, and no-backup coverage.
  - Add inventory coverage for the new origin-review preset.
  - Add JSON/non-TTY overwrite-required failure coverage.
- `tests/python/runtime/test_command_exit_codes.py`
  - Add install-prompts overwrite-required failure/bypass exit-code coverage.

### Frontend tests
- None.
  - This is a CLI utility + prompt-template change; no dashboard/textual UI path should change in the first implementation.

### Integration/E2E tests
- Optional narrow CLI integration check if maintainers want extra confidence:
  - run `envctl install-prompts --cli codex` twice against a temp HOME and assert the second run prompts once and leaves no `.bak-*` file behind
- No cmux/plan-agent E2E coverage should be added in this scope unless the implementation unexpectedly modifies launch behavior.

## Observability / logging (if relevant)
- No new structured runtime events are required for the initial implementation.
- User-visible command messages must still clearly distinguish:
  - written vs overwritten targets
  - overwrite approval required vs overwrite declined
  - unsupported preset / unsupported CLI failures
- If maintainers want richer automation telemetry later, add it as a follow-up once the overwrite contract stabilizes.

## Rollout / verification
- Implement and verify in this order:
  1. Update `prompt_install_support.py` overwrite semantics and add tests first.
  2. Add the new prompt template file and update preset inventory tests.
  3. Update docs and examples.
- Verification commands:
  - `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py tests/python/runtime/test_engine_runtime_dispatch.py -q`
  - Manual temp-HOME sanity pass:
    - `HOME=/tmp/envctl-prompts-test envctl install-prompts --cli codex`
    - run the same command again and confirm single overwrite prompt
    - verify `find /tmp/envctl-prompts-test -name '*.bak-*'` returns nothing for the new overwrite path
  - Manual preset sanity pass:
    - install all prompts
    - from the local/origin repo CLI, invoke the new review preset and pass a created worktree path/name as the argument

## Definition of done
- Running `install-prompts` over an existing prompt file no longer creates `.bak-*` sibling commands.
- Overwrite approval is requested once per command in interactive mode and is bypassable with an explicit approval flag.
- JSON and non-TTY overwrite-required flows fail cleanly without interactive prompting.
- A new built-in origin-review preset is packaged, discovered by filename, installable for all supported CLIs, and documented.
- Prompt-install docs no longer claim backups are created on overwrite.
- Focused runtime tests covering prompt installation and exit-code behavior are green.

## Risk register (trade-offs or missing tests)
- Existing `.bak-*` files will remain in user home directories unless manually removed.
  - This plan intentionally avoids destructive cleanup of previously installed backup prompts.
- The meaning of “run from the CLI that created the plan” is resolved here as a manual origin-side preset, not an automatic second launch action.
  - If maintainers actually want envctl to inject a second command into the origin surface automatically, `plan_agent_launch_support.py` and its config model will need a separate follow-up design.
- If the implementation adds a new structured field such as `would_overwrite` to `PromptInstallResult`, JSON consumers will need to tolerate the schema extension.
  - The plan prefers keeping the existing result schema stable unless implementation experience proves the extra field is necessary.

## Open questions (only if unavoidable)
- None. The implementation can proceed from current repo evidence with the assumptions above.
