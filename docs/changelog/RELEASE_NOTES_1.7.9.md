# envctl 1.7.9

`envctl` 1.7.9 is a hotfix release on top of `1.7.8`. It publishes the follow-up usability fixes for explicit non-interactive actions, comprehensive CLI help, and AI-session launch guidance in the worktree dashboard.

## Fixed

- Explicit action commands such as `kill-all`, `stop`, and `pr` now default to headless/non-interactive execution when the requested action is specific enough to run without another prompt.
- The worktree dashboard again shows a `Run AI:` create-session command for worktrees that do not already have an active AI session. Existing active sessions continue to show the attach command instead.

## Added

- `envctl --help` now explains the CLI surface much more thoroughly, including common workflows, runtime scopes, action commands, configuration, release/support commands, and examples.
- Command-specific help is available through focused forms such as `envctl help pr`, `envctl help kill-all`, and other command names, so operators can discover behavior without digging through source or docs.
- Launcher help includes a runtime command map that makes wrapper usage and common entry points easier to understand.

## Changed

- Help output is organized around what an operator is trying to do instead of only listing terse parser options.
- Dashboard AI rows now use a mutually exclusive contract: show attach guidance for active AI sessions, or show create-session guidance when no AI session is active.

## Why This Release Matters

This hotfix makes `envctl` safer and easier to operate from the terminal. Specific commands do the specific thing requested without unexpected interactive branching, help output is now useful as an onboarding/reference surface, and the dashboard gives a clear next command for starting AI work in a worktree that does not yet have a session.

## Validation

Release-candidate validation for this version ran:

- `./.venv/bin/python -m pytest tests/python/runtime/test_launcher_version.py tests/python/runtime/test_cli_packaging.py tests/python/runtime/test_release_shipability_gate.py tests/python/runtime/test_release_shipability_gate_cli.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_command_policy_contract.py tests/python/ui/test_dashboard_rendering_parity.py -q` → 167 passed, 12 skipped, 43 subtests passed
- `PYTHONPATH=python python3 -m compileall -q python tests` → passed
- `git diff --check` → passed
- `./.venv/bin/python scripts/release_shipability_gate.py --repo . --skip-tests` → `shipability.passed: true`
- `./.venv/bin/python -m build` → built `dist/envctl-1.7.9-py3-none-any.whl` and `dist/envctl-1.7.9.tar.gz`

## Artifacts

This release publishes:

- wheel distribution: `envctl-1.7.9-py3-none-any.whl`
- source distribution: `envctl-1.7.9.tar.gz`
- release notes markdown asset: `RELEASE_NOTES_1.7.9.md`

## Upgrade Notes

- No `.envctl` changes are required.
- Existing `1.7.8` dashboard visual-host behavior remains unchanged.
- Scripts that depended on prompts from explicit actions should pass interactive flags intentionally; the default for specific action commands is now automation-friendly.
