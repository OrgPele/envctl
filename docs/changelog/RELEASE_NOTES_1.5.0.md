# envctl 1.5.0

`envctl` 1.5.0 is a minor release on top of `1.4.1`. It ships the user-facing workflow additions and runtime hardening that landed after the `1.4.1` tag: clickable local path links across the terminal UI, a dedicated `finalize_task` prompt flow, optional origin-side review launch after dashboard review, stronger target-scoped backend env isolation, and more resilient source-checkout/runtime bootstrap behavior.

This release is a minor instead of a patch because the post-`1.4.1` range adds new operator-facing and prompt-driven workflow surface rather than only correcting previously shipped behavior.

## Why This Release Matters

The `1.4.1` line focused on hotfixes. `1.5.0` turns the work that followed into a broader workflow upgrade:

- AI-assisted implementation loops now have an explicit completion preset and a smoother path into origin-side review
- terminal output can expose clickable local file paths across the main interactive surfaces without changing machine-readable output
- backend env resolution is more trustworthy for both startup and native `migrate` flows in multi-worktree repos
- source-checkout execution is more robust when runtime dependencies or import-path precedence would previously cause confusing failures
- the active runtime/docs/release contract is now fully aligned around the Python engine rather than legacy shell-era behavior

## Highlights

### Workflow completion and origin-side review

Planning and review loops gained new user-facing workflow support.

- `install-prompts` now ships a dedicated `finalize_task` prompt preset for slash-command driven completion flows
- queued plan-agent cycles now reserve `/prompts:finalize_task` for the final queued handoff instead of using the same follow-up prompt throughout
- interactive dashboard review can optionally open one origin-side AI review tab after a successful single-worktree review
- origin-side review launches now carry the original plan/provenance context through the shared launcher path so the follow-up review starts from the right scope
- `continue_task` guidance was clarified for the truly complete case so the prompt does not imply more implementation work remains when the prior iteration is already done

### Clickable local path links across terminal output

Human-facing CLI output can now emit clickable local file links across the main runtime surfaces.

- dashboard, action, runtime, config, doctor, startup-warning, prompt-install, planning/worktree, command-loop, and test-summary output paths now share one hyperlink policy
- trailing punctuation is excluded from link targets and remote URLs such as `https://...` are not misidentified as local paths
- `ENVCTL_UI_HYPERLINK_MODE=auto|on|off` controls hyperlink behavior explicitly
- JSON output and persisted artifacts remain raw text rather than OSC-8 encoded output

### Target-scoped backend env isolation

Backend env selection is now more reliable across startup and native action flows.

- startup bootstrap and native `envctl migrate` now share one backend env-resolution contract
- inherited backend-sensitive shell variables are scrubbed before target-scoped env merge so one worktree does not accidentally pick up another target's database settings
- relative backend and frontend override paths follow the documented target-root / repo-root resolution contract, including ambiguity detection and service-local fallback behavior
- startup migration warnings and migrate failures keep env-source diagnostics so operators can see which env-file path won

### Runtime bootstrap and Python-only contract hardening

Source-checkout execution and contributor validation are more deterministic.

- commands now bootstrap required runtime dependencies before deeper runtime use, improving failure behavior when optional UI/runtime packages are missing
- raw repo-root unittest discovery works without `PYTHONPATH=python`
- repo-local test/bootstrap and `./bin/envctl` source-wrapper execution now prefer this checkout even if a foreign `envctl_engine` package appears earlier on `PYTHONPATH`
- release/readiness ownership, docs, and active plan references now align to the Python runtime contract rather than the retired shell domain
- legacy harness-only TTY env guards were removed in favor of real terminal-state detection

## Included Changes

Major areas covered in this release:

- new `finalize_task` prompt preset and updated queued plan-agent follow-up semantics
- optional post-review origin tab launch for interactive dashboard review
- origin-review provenance/original-plan handling improvements
- clickable local path rendering across human-facing terminal output with `ENVCTL_UI_HYPERLINK_MODE`
- startup and native migrate backend env isolation plus frontend override-path contract documentation
- dependency bootstrap-before-use hardening for source-checkout/runtime entrypoints
- repo-root bootstrap precedence fixes for raw unittest discovery and `./bin/envctl`
- Python-only runtime/release-governance cleanup and validation-contract alignment
- prompt and docs refinements around completion-state and contributor runtime guidance

## Operator Notes

- No data migration or manual config migration is required for this release.
- `ENVCTL_UI_HYPERLINK_MODE` is optional; the default `auto` mode remains conservative and terminal-dependent.
- Teams using worktree-specific backend env files should see `migrate` and startup behave more consistently under conflicting parent-shell env settings.
- Contributors running source-checkout commands should see fewer import-path and bootstrap failures when local or foreign `PYTHONPATH` entries are present.

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the most visible changes in `1.5.0` are:

- a built-in `finalize_task` prompt flow for the last step of queued implementation cycles
- an optional origin-side review tab after successful single-worktree dashboard review
- clickable local file-path links across the main human-facing CLI and dashboard surfaces
- stronger worktree-scoped backend env selection for startup and native `migrate`
- more reliable source-checkout behavior for repo-root unittest discovery and `./bin/envctl`

## Summary

`envctl` 1.5.0 expands the workflow surface while tightening the runtime edges underneath it. The release adds new prompt/review/UI capabilities, makes environment selection and bootstrap behavior more trustworthy, and keeps the contributor/release contract aligned with the Python runtime that the product now ships.
