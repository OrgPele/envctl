# Envctl Smart Commit Message Pointer File

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Replace changelog-backed default commit-message sourcing with a repo-local proprietary file that is never committed.
  - Make built-in AI prompt presets append structured change summaries into that file after implementation work.
  - Make `envctl commit` derive its default commit message from the section starting at `### Envctl pointer ###` through end-of-file, then advance that pointer to the end of the file after a successful commit.
  - Preserve explicit manual overrides (`--commit-message`, `--commit-message-file`) so operators can still bypass the default flow intentionally.
- Non-goals:
  - Reworking PR-body generation, which still has its own `MAIN_TASK.md` / commit-history logic in `python/envctl_engine/actions/project_action_domain.py:_pr_body(...)`.
  - Changing git push behavior, branch resolution, or commit staging semantics in `run_commit_action(...)` beyond commit-message sourcing and post-commit pointer advancement.
  - Migrating historical changelog content into the new file automatically unless implementation evidence later proves that is necessary.
- Assumptions:
  - “Every change the AI will make will be appended” refers to envctl-installed AI prompt presets (`install-prompts`) and the documented built-in agent workflows, not arbitrary third-party prompts outside envctl control.
  - The proprietary file should live at repo root with a hidden `.envctl*`-prefixed name (recommended: `.envctl-commit-message.md`) so existing ignore logic in `python/envctl_engine/config/persistence.py:ensure_local_config_ignored(...)` already covers it without inventing a second ignore strategy.
  - The default commit flow should remove the changelog fallback entirely; if no explicit override is provided and the proprietary file has no text after the pointer, `envctl commit` should fail with a clear actionable message rather than silently falling back to changelog content.

## Goal (user experience)
After an AI-assisted implementation, the repo contains a hidden local commit-message ledger file that accumulates structured summaries of recent work. When the operator runs `envctl commit` without an explicit `--commit-message` or `--commit-message-file`, envctl should commit exactly the text from `### Envctl pointer ###` to the end of that file, then move the pointer marker to the end so the next commit only sees newly appended summaries. Users should no longer depend on `docs/changelog/...` for commit-message generation, and dashboard/prompt copy should describe the new default clearly instead of referring to changelog fallback.

## Business logic and data model mapping
- Command routing and flag ownership:
  - `python/envctl_engine/runtime/command_router.py:_store_value_flag(...)` maps `--commit-message` and `--commit-message-file` into route flags.
  - `python/envctl_engine/actions/action_command_support.py:build_action_extra_env(...)` forwards those flags as `ENVCTL_COMMIT_MESSAGE` and `ENVCTL_COMMIT_MESSAGE_FILE`.
- Commit action execution:
  - `python/envctl_engine/actions/action_command_orchestrator.py:run_commit_action(...)` delegates the command to the Python action entrypoint returned by `python/envctl_engine/actions/actions_git.py:default_commit_command(...)`.
  - `python/envctl_engine/actions/actions_cli.py:main(...)` and `_run_commit_action(...)` construct `ActionProjectContext` and delegate to `python/envctl_engine/actions/project_action_domain.py:run_commit_action(...)`.
  - `run_commit_action(...)` stages via `_run_git(..., ["add", "-A"])`, checks `status --porcelain`, resolves commit message data via `_resolve_commit_message(...)`, commits with either `git commit -F <file>` or `git commit -m <message>`, then pushes with `git push -u <remote> <branch>`.
- Current commit-message model:
  - `_resolve_commit_message(...)` currently prefers, in order: `ENVCTL_COMMIT_MESSAGE`, `ENVCTL_COMMIT_MESSAGE_FILE`, tree changelog content via `_tree_changelog_path(...)` + `_latest_changelog_commit_message(...)`, then `MAIN_TASK.md`.
  - `_write_commit_message_file(...)` currently materializes changelog-derived text into an OS temp file with suffix `.envctl-commit-message.txt` only for the `git commit -F` call.
- Dashboard/UI surface:
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_apply_commit_selection(...)` only prompts when neither explicit message flag is present.
  - `_prompt_commit_message(...)` currently uses `help_text="Commit message (leave blank to use changelog)."` and `default_button_label="Use changelog"`.
- Installer/template ownership:
  - `python/envctl_engine/runtime/prompt_install_support.py:run_install_prompts_command(...)` installs built-in prompt presets into user-local AI CLI directories.
  - `python/envctl_engine/runtime/prompt_templates/implement_task.md`, `continue_task.md`, `review_task_imp.md`, and `merge_trees_into_dev.md` currently instruct agents to append detailed summaries to `docs/changelog/{tree_name}_changelog.md`.
  - `python/envctl_engine/runtime/prompt_templates/create_plan.md` still has a self-check line `Changelog entry appended.`, which no longer matches a plan-only workflow and becomes more obviously wrong if changelog is retired from commit-message generation.
- Repo-local ignore/bootstrap contract:
  - `python/envctl_engine/config/persistence.py:ensure_local_config_ignored(...)` updates repo `.gitignore` with `.envctl*`, `trees/`, and `MAIN_TASK.md`, and `.git/info/exclude` with `.envctl*`.
  - Docs such as `docs/user/first-run-wizard.md` already describe `.envctl*` ignore behavior as part of the repo-local contract.

## Current behavior (verified in code)
- `envctl commit` already stages all changes, fails cleanly on a clean worktree, and prefers explicit overrides before using fallback content:
  - `python/envctl_engine/actions/project_action_domain.py:run_commit_action(...)`
  - `python/envctl_engine/actions/project_action_domain.py:_resolve_commit_message(...)`
- The current fallback is changelog-centric:
  - `_resolve_commit_message(...)` reads the tree changelog via `_tree_changelog_path(...)` and derives a bounded message from `_latest_changelog_commit_message(...)`.
  - When changelog content is used, `_write_commit_message_file(...)` writes a temp file and `run_commit_action(...)` invokes `git commit -F <tempfile>`.
- `MAIN_TASK.md` is still used as a final commit-message-file fallback if changelog resolution does not produce content.
- Dashboard commit UX still teaches the old contract:
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_prompt_commit_message(...)` explicitly says blank input means “use changelog”.
  - `tests/python/ui/test_dashboard_orchestrator_restart_selector.py:test_commit_prompts_for_message_and_uses_explicit_value_when_provided` and `tests/python/ui/test_text_input_dialog.py` lock that copy today.
- The installer still teaches the old workflow:
  - `python/envctl_engine/runtime/prompt_templates/implement_task.md:22`
  - `python/envctl_engine/runtime/prompt_templates/continue_task.md:22`
  - `python/envctl_engine/runtime/prompt_templates/review_task_imp.md:31`
  - `python/envctl_engine/runtime/prompt_templates/merge_trees_into_dev.md:34`
- Existing tests prove changelog-backed commit sourcing is part of the current contract:
  - `tests/python/actions/test_actions_cli.py:test_commit_action_uses_latest_changelog_h2_section_only`
  - `tests/python/actions/test_actions_cli.py:test_commit_action_truncates_large_latest_changelog_section`
  - `tests/python/actions/test_actions_cli.py:test_commit_action_skips_markdown_subheadings_in_latest_changelog_subject`
- The repo already has a pattern for hidden repo-local managed files that should not be committed:
  - `.envctl*` ignore management in `config/persistence.py`
  - repo-local operational documents like `MAIN_TASK.md`
  - runtime-scoped artifacts under `RuntimeStateRepository.runtime_root`, which are not appropriate here because commit-message history must be repo-local and survive across runtime sessions.

## Root cause(s) / gaps
- Commit-message sourcing is split between explicit overrides and legacy fallbacks, but the default path is still anchored to changelog parsing logic in `_latest_changelog_commit_message(...)` rather than a purpose-built commit ledger.
- The repo has no durable repo-local file dedicated to AI-authored commit-message accumulation, so envctl currently creates only ephemeral temp files right before `git commit -F`.
- Prompt installer templates, dashboard copy, and tests all reinforce the changelog contract, so changing only `_resolve_commit_message(...)` would leave the surrounding tooling inconsistent.
- Pointer-based incremental consumption does not exist anywhere in the current commit flow, so implementation must define:
  - file format
  - bootstrap/creation behavior
  - empty-segment behavior
  - post-commit pointer advancement rules
  - failure handling when commit succeeds or fails
- Current ignore behavior is broad enough to cover `.envctl*`, but no plan yet maps the new file path to that existing ignore contract explicitly.

## Plan
### 1) Introduce a repo-local proprietary commit-message ledger contract
- Add a small Python-owned helper in `python/envctl_engine/actions/project_action_domain.py` (or a nearby focused helper module if extraction keeps the domain file readable) to own the new ledger file contract.
- Recommended default path: `<repo-root>/.envctl-commit-message.md`.
  - This is repo-local, hidden, human-inspectable, and already compatible with `.envctl*` ignore rules in `config/persistence.py:ensure_local_config_ignored(...)`.
  - Do not place it under runtime-scoped directories from `python/envctl_engine/state/repository.py`; those are run/session artifacts under runtime roots, while the requested commit-message history must survive across runtime sessions and be visible to AI prompts operating in the repo.
- Define the on-disk format explicitly in code and docs:
  - freeform appended summaries above and below the marker are allowed
  - one canonical marker line exists: `### Envctl pointer ###`
  - the commit payload is the normalized text strictly after the marker through EOF
  - implementation must guarantee the marker remains present exactly once after any write/advance operation
- Bootstrap behavior:
  - if the file does not exist, create it with a small header and the marker at EOF
  - if the file exists but lacks the marker, fail with a clear repair message rather than guessing where to commit from
  - if the file has multiple markers, fail with a clear integrity error and do not commit

### 2) Replace changelog fallback in commit resolution with pointer-file resolution
- Update `python/envctl_engine/actions/project_action_domain.py:_resolve_commit_message(...)` so the precedence becomes:
  1. explicit `ENVCTL_COMMIT_MESSAGE`
  2. explicit `ENVCTL_COMMIT_MESSAGE_FILE`
  3. proprietary repo-local commit-message ledger segment from pointer to EOF
- Remove changelog-derived commit-message generation from the default commit path:
  - retire `_tree_changelog_path(...)` and `_latest_changelog_commit_message(...)` from commit resolution usage
  - keep any changelog logic still needed by other flows only if those flows remain real consumers
- Replace `MAIN_TASK.md` as the implicit commit-message fallback with a hard failure when the ledger segment is empty or missing.
  - Rationale: the requested new contract is pointer-file based; using `MAIN_TASK.md` would silently produce messages unrelated to the accumulated AI change summaries.
- Preserve existing `git commit -F <file>` behavior by materializing the resolved pointer segment into a temp file using the existing `_write_commit_message_file(...)` pattern.
  - This keeps the git invocation stable while changing only how the message body is sourced.

### 3) Advance the pointer atomically only after successful commit creation
- Extend `python/envctl_engine/actions/project_action_domain.py:run_commit_action(...)` so pointer advancement happens only after `git commit` returns success and before push failure handling is surfaced.
- Use an atomic write strategy similar to `python/envctl_engine/config/persistence.py:_atomic_write(...)` for rewriting the ledger file.
  - Reconstruct the file so everything that was just consumed remains in the historical section above the marker and the marker is rewritten at EOF.
  - Do not mutate the ledger before a successful `git commit`; otherwise failed commits would lose queued summaries.
- Edge cases to handle explicitly:
  - `git commit` fails: leave the file untouched and keep the pointer where it was
  - `git commit` succeeds but `git push` fails: pointer should already be advanced because the local commit consumed those summaries; the operator can retry push without reusing the same ledger segment
  - empty text after pointer: fail before invoking git commit with an actionable message telling the operator to add an explicit commit message or append to the envctl ledger file
  - whitespace-only content after pointer: treat as empty
  - file missing between resolution and advance: fail with a clear integrity error and do not attempt destructive repair

### 4) Update dashboard commit UX and route semantics to describe the new default correctly
- Change `python/envctl_engine/ui/dashboard/orchestrator.py:_prompt_commit_message(...)` copy from changelog language to the new ledger language.
  - Example shape: `Commit message (leave blank to use envctl commit log).`
  - Default button label should reference the envctl ledger instead of changelog.
- Keep `DashboardOrchestrator._apply_commit_selection(...)` behavior the same structurally:
  - blank input means “use default resolution”
  - non-blank input still sets `commit_message`
  - explicit `commit_message_file` route flags remain respected
- Update text-input dialog tests and dashboard route tests to lock the new copy and the unchanged blank-input semantics.

### 5) Update installed AI prompt presets and installer-owned workflow guidance
- Edit the built-in prompt template files under `python/envctl_engine/runtime/prompt_templates/` so implementation-oriented presets append a structured entry to the new ledger file instead of `docs/changelog/{tree_name}_changelog.md`.
- Required template updates:
  - `implement_task.md`
  - `continue_task.md`
  - `review_task_imp.md`
  - `merge_trees_into_dev.md`
- Also update `create_plan.md` so it no longer requires or self-checks a changelog append for a planning-only workflow.
- Keep the append instructions specific and deterministic so installed prompts write to the same repo-local file name and preserve the marker contract.
  - The prompt guidance should instruct agents to append new content above or below the marker in the agreed format without deleting older entries.
  - The implementation should decide one canonical append location; the safer contract is “append to EOF, then rewrite marker to EOF during commit consumption,” because it matches the user’s pointer-to-EOF request and keeps new summaries in the to-be-consumed segment.

### 6) Align docs, tests, and migration messaging with the new source of truth
- Update user/reference docs that mention prompt installation or commit flow so they describe the new ledger-based default:
  - `docs/reference/commands.md`
  - `docs/user/ai-playbooks.md`
  - any relevant developer guide that documents action-command ownership or commit behavior if implementation touches those expectations
- Add a short developer-facing note describing the proprietary file path, why it is ignored, and how pointer advancement works.
- Decide whether changelog files remain for release notes only:
  - if yes, document that changelog is no longer part of commit-message generation
  - if no longer needed in installed prompts, remove prompt references but do not delete historical changelog docs as part of this feature unless separately requested
- Keep feature inventory notes honest if behavior changes materially enough to affect `python/envctl_engine/runtime_feature_inventory.py`’s commit contract description.

## Tests (add these)
### Backend tests
- Extend `tests/python/actions/test_actions_cli.py` with focused commit-flow coverage:
  - default commit action reads only the text after `### Envctl pointer ###` from the proprietary file and uses it as the `git commit -F` payload
  - after successful commit, the pointer is moved to EOF and previously consumed text is no longer part of the next commit payload
  - explicit `--commit-message` still overrides the proprietary file entirely
  - explicit `--commit-message-file` still overrides the proprietary file entirely
  - empty post-pointer segment fails with a clear message and never invokes `git commit`
  - missing marker / duplicate marker fails with a clear integrity error
  - push failure after successful commit does not roll the pointer back
- Remove or replace changelog-specific commit tests that currently codify `_latest_changelog_commit_message(...)` as the default source of truth.
- If helper extraction occurs, add narrow unit tests for pointer parsing / advancement helpers rather than only end-to-end action tests.

### Frontend tests
- Extend `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`:
  - update assertions for the new default button label and help text
  - preserve the existing blank-input route contract (no `commit_message` flag set)
- Extend `tests/python/ui/test_text_input_dialog.py` only as needed if the helper text/default label snapshots need updating.

### Integration/E2E tests
- Extend `tests/python/runtime/test_prompt_install_support.py` to prove installed prompt templates now contain ledger-file instructions instead of changelog instructions.
- Extend `tests/python/runtime/test_cli_router_parity.py` only if any new flag or parsing contract is introduced; avoid parser churn if the file path stays implicit and repo-owned.
- Prefer the existing Python action parity/integration surface over introducing new BATS coverage unless implementation touches shell-wrapper compatibility.

## Observability / logging (if relevant)
- Emit clear operator-facing messages when commit resolution fails because the ledger file is missing, malformed, or empty after the pointer.
- If the repo already emits structured action events for commit lifecycle, add bounded metadata only if useful, for example:
  - commit message source = explicit string / explicit file / envctl ledger
  - ledger bytes consumed
  - pointer advance performed = yes/no
- Do not log the full commit message body into runtime events; commit text may contain sensitive or verbose implementation notes.

## Rollout / verification
- Implement in this order:
  1. define ledger file helpers and pointer validation/advancement in the commit domain
  2. switch `_resolve_commit_message(...)` to the new precedence and remove changelog fallback from commit flow
  3. update dashboard commit copy
  4. update prompt templates + installer-facing tests
  5. update docs and any feature-inventory wording that now overstates changelog ownership
- Verification commands for implementation phase:
  - `./.venv/bin/python -m pytest tests/python/actions/test_actions_cli.py -q`
  - `./.venv/bin/python -m pytest tests/python/ui/test_dashboard_orchestrator_restart_selector.py tests/python/ui/test_text_input_dialog.py -q`
  - `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_cli_router_parity.py -q`
- Manual verification targets:
  - create `.envctl-commit-message.md` with two historical entries and the pointer before the newest one, run `envctl commit`, and confirm only the newest segment is used
  - rerun `envctl commit` without adding new ledger text and confirm it fails with a clear empty-segment message
  - use dashboard `commit`, leave the text blank, and confirm the prompt copy references the envctl ledger rather than changelog
  - run `envctl install-prompts --cli codex --dry-run` and confirm generated prompt content references the proprietary file rather than `docs/changelog/...`

## Definition of done
- `envctl commit` no longer derives its default commit message from changelog or `MAIN_TASK.md`.
- Default commit-message sourcing uses the proprietary repo-local ledger file and consumes only the post-pointer segment.
- Pointer advancement occurs exactly once after successful local commit creation and is not triggered on failed commits.
- Dashboard commit copy and installed prompt presets describe the new default consistently.
- Existing changelog-specific commit tests are replaced with pointer-file contract tests, and all relevant Python action/UI/prompt-installer tests pass.
- Repo docs no longer describe changelog as the default source for commit-message generation.

## Risk register (trade-offs or missing tests)
- Risk: choosing the wrong ledger file location could create cross-run or cross-worktree surprises.
  - Mitigation: keep it repo-local and hidden with a `.envctl*` prefix so it follows existing ignore semantics and remains visible to prompts operating inside the repo.
- Risk: pointer rewrite bugs could duplicate or drop queued commit summaries.
  - Mitigation: isolate parsing/advance helpers, enforce single-marker validation, use atomic rewrite semantics, and cover success/failure cases explicitly in tests.
- Risk: removing `MAIN_TASK.md` fallback may break operators who relied on implicit commit messages without using changelog or prompt-installed flows.
  - Mitigation: provide a clear failure message that points to the new ledger file and preserves explicit `--commit-message` / `--commit-message-file` overrides.
- Risk: prompt templates may append in an inconsistent format across CLIs if the file contract is underspecified.
  - Mitigation: document one canonical file path and one canonical append format inside the templates and installer tests.

## Open questions (only if unavoidable)
- None. The repo evidence is sufficient to produce an implementation plan. The remaining design choice is the exact proprietary filename; this plan recommends `.envctl-commit-message.md` because it fits the existing ignore contract, but implementation can choose a different `.envctl*` name if it keeps the same semantics.
