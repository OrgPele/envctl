# Envctl Prompt Overwrite Verification And Closeout

## Context and objective
The prior iteration implemented the core feature work for prompt overwrite confirmation and the new origin-side review preset:

- `python/envctl_engine/runtime/prompt_install_support.py` now plans installs before writing, removes backup-file creation, and gates overwrites behind one approval decision.
- `python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md` was added.
- `tests/python/runtime/test_prompt_install_support.py` and `tests/python/runtime/test_command_exit_codes.py` were expanded to cover the new behavior.
- `docs/user/ai-playbooks.md`, `docs/reference/commands.md`, and `docs/user/python-engine-guide.md` were updated.

What remains is verification closeout. The previous delivery did not complete the repo-standard pytest lane or a CLI-visible smoke/integration validation pass. This iteration must finish that work end-to-end and fix any issues uncovered during that verification.

## Remaining requirements (complete and exhaustive)
1. Establish the repo-standard Python validation environment inside this worktree.
   - Follow the repository’s documented validation flow from `docs/developer/testing-and-validation.md`.
   - Create a repo-local `.venv` in this worktree if it is missing.
   - Install the project with dev dependencies into that `.venv`.
   - Do not treat `python3 -m unittest ...` alone as the final verification signal for this CLI-visible change.
2. Add CLI-visible integration coverage for the prompt overwrite contract.
   - Cover the actual command path, not only helper-level unit behavior.
   - Exercise prompt installation through the runtime CLI entrypoint (`envctl_engine.runtime.cli.run(...)` or an equivalent existing repo test pattern).
   - Verify a first install writes the prompt file and a second install overwrites in place without creating any `.bak-*` sibling files.
   - Keep all temporary writable paths inside the current worktree or inside test-managed temporary directories; do not depend on sibling worktrees or user-home state.
   - Reuse existing runtime test patterns instead of inventing a new harness.
3. Add CLI-visible installation verification for the new `review_worktree_imp` preset.
   - Verify the preset can be installed through the normal command path, not only loaded as a raw template.
   - Assert the written prompt file retains the key origin-review contract:
     - current repo is the unedited baseline
     - target worktree comes from `$ARGUMENTS`
     - review is read-only by default
     - output is findings-first
4. Run the authoritative focused pytest lane that the prior task required.
   - Use the exact focused scope from the previous task unless additional tests are needed because of new integration coverage.
   - If the new integration test lands in another existing runtime test module, include that module in the same focused pytest invocation.
5. Perform a repo-local smoke validation for the overwrite flow.
   - Use a HOME directory located under the current repo root so the worktree boundary is respected.
   - Validate that repeated installs do not create `.bak-*` files.
   - If interactive prompt-on-second-run validation is hard to automate cleanly, encode that behavior in test coverage and use smoke validation for the non-interactive approved overwrite path.
6. Fix any production code, tests, or docs required to make the full verification set pass.
   - Do not assume the current code is final.
   - If verification exposes defects in `prompt_install_support.py`, the prompt template, CLI routing, or docs, resolve them in this iteration.
7. Append the completed verification/fix summary to `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`.
   - Record the exact `.venv` bootstrap command(s), pytest command(s), smoke command(s), results, and any follow-up fixes made during this iteration.

## Gaps from prior iteration (mapped to evidence)
- The previous task required `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py tests/python/runtime/test_engine_runtime_dispatch.py -q`, but this worktree currently has no repo-local virtualenv.
  - Evidence: `./.venv/bin/python` was absent during audit.
- The system interpreter in this worktree does not currently have pytest installed.
  - Evidence: `python3 -m pytest --version` failed with `No module named pytest`.
- The existing tree-specific changelog entry only records `python3 -m unittest ...` runs, not the required pytest lane or a CLI-visible smoke/integration verification pass.
  - Evidence: `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md`
- Current coverage is strong at the unit/command level, but there is still no dedicated CLI-visible integration regression proving the full repeated-install path end-to-end.
  - Evidence: the changed tests are in `tests/python/runtime/test_prompt_install_support.py` and `tests/python/runtime/test_command_exit_codes.py`; neither currently performs a true command-path double-install smoke/assertion beyond direct `cli.run(...)` exit-code behavior.

## Acceptance criteria (requirement-by-requirement)
1. Repo-local validation environment exists and is usable.
   - `.venv/bin/python` exists inside this worktree.
   - Dev dependencies are installed successfully enough to run pytest.
2. CLI-visible overwrite integration coverage exists and passes.
   - Repeated install coverage proves there is no `.bak-*` creation on overwrite.
   - Coverage proves the command path still distinguishes `written` vs `overwritten`.
3. CLI-visible `review_worktree_imp` installation coverage exists and passes.
   - The installed file lands in the expected target directory.
   - The installed body contains the required baseline/worktree/read-only/findings-first guidance.
4. The focused pytest lane passes under `.venv`.
   - At minimum:
     - `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_command_exit_codes.py tests/python/runtime/test_engine_runtime_dispatch.py -q`
   - If new integration coverage lands elsewhere, the final command must include that test module too.
5. Repo-local smoke validation passes.
   - Repeated prompt installs using a repo-local HOME do not leave any `.bak-*` files behind.
6. Changelog is updated with this iteration’s actual verification evidence.
   - The entry names commands and results precisely, not generically.

## Required implementation scope (frontend/backend/data/integration)
- Backend/runtime:
  - Extend runtime test coverage around `install-prompts` CLI-visible behavior.
  - Fix runtime code only if the stronger verification surface reveals defects.
- Docs:
  - Update user/reference docs only if verification uncovers incorrect instructions or examples.
  - Append the verification summary to the tree-specific changelog.
- Frontend:
  - None unless verification unexpectedly reveals a frontend-facing dependency.
- Data/config/migrations:
  - No database or persisted data migrations are expected.
  - Repo-local `.venv` bootstrap is allowed and expected inside this worktree.

## Required tests and quality gates
- Read `docs/developer/testing-and-validation.md` before changing the verification approach.
- Add or extend existing runtime tests instead of creating an ad hoc script-only check.
- Run the focused pytest command under `.venv`.
- Run any new integration/smoke command(s) needed to prove the command path.
- If verification changes test placement or adds a new runtime test module, keep the final validation command list explicit in the changelog.

## Edge cases and failure handling
- Repeated install into an already-populated prompt directory must not create `.bak-*` files.
- Verification must respect the worktree boundary:
  - use repo-local HOME paths for smoke checks
  - do not write to user-home prompt directories during validation
  - do not depend on writes to sibling worktrees
- If `.venv` bootstrap fails, fix the bootstrap issue or record the exact blocker with evidence before stopping.
- If stronger CLI-visible coverage reveals mismatches between docs and behavior, update both in the same iteration.
- If the installed `review_worktree_imp` prompt text differs from the intended review contract, fix the template and extend the assertion set so the regression cannot recur.

## Definition of done
- All remaining verification work is complete, not partially attempted.
- Repo-local `.venv` exists and the focused pytest lane passes inside it.
- CLI-visible overwrite integration coverage exists and is green.
- CLI-visible `review_worktree_imp` installation coverage exists and is green.
- Repo-local smoke validation confirms repeated installs leave no `.bak-*` files.
- Any defects found during verification are fixed in the same iteration.
- `docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md` is appended with exact commands, results, and any follow-up fixes.
