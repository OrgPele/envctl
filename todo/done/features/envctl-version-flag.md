# Envctl `--version` Flag Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Add a supported `--version` flag that prints the current `envctl` version and exits successfully.
  - Make version reporting work consistently for the package-installed command (`envctl`) and the clone-compatibility wrapper (`./bin/envctl`).
  - Keep the implementation aligned with the existing launcher/runtime command boundary so version reporting does not depend on repo detection, config bootstrap, or runtime startup.
  - Document the new version surface anywhere installation, command usage, or troubleshooting docs currently describe the launcher contract.
- Non-goals:
  - Adding a new runtime command family unrelated to the user request.
  - Changing release/versioning policy or the current package versioning source of truth.
  - Reworking help output, command inventory, or direct inspection commands beyond what is required for `--version`.
- Assumptions:
  - The required user-facing behavior is `envctl --version`; no additional `version` subcommand is required unless a clear compatibility need is discovered during implementation.
  - `--version` should be launcher-owned rather than runtime-owned because version reporting should work outside a repo and before any runtime bootstrap or prereq checks.
  - The canonical version source should remain the package metadata in `pyproject.toml`, with a source-checkout fallback only if installed metadata is unavailable.

## Goal (user experience)
Users can run `envctl --version` from an installed pipx environment, from an editable install, or from an explicit repo wrapper path and get a single clear version string immediately, without needing to be inside a git repo or have `.envctl` configured. The docs should treat this as a normal verification step after installation and during troubleshooting.

## Business logic and data model mapping
- Wrapper/launcher entrypoints:
  - `bin/envctl:main`
  - `python/envctl_engine/runtime/launcher_cli.py:run`
  - `python/envctl_engine/runtime/launcher_support.py:launcher_usage_text`
- Runtime boundary and command-surface rules:
  - `docs/developer/command-surface.md`
  - `docs/developer/python-runtime-guide.md`
- Runtime command inventory and help behavior:
  - `python/envctl_engine/runtime/command_router.py`
    - `COMMAND_ALIASES`
    - `SUPPORTED_COMMANDS`
    - `list_supported_commands()`
  - `python/envctl_engine/runtime/engine_runtime.py:_print_help`
  - `python/envctl_engine/runtime/inspection_support.py:dispatch_direct_inspection`
- Packaging/version metadata:
  - `pyproject.toml`
  - `tests/python/runtime/test_cli_packaging.py`
- Existing launcher/runtime behavior tests:
  - `tests/python/runtime/test_command_exit_codes.py`
  - `tests/python/runtime/test_cli_router_parity.py`
  - `tests/python/runtime/test_command_dispatch_matrix.py`
  - `tests/python/runtime/test_engine_runtime_command_parity.py`

## Current behavior (verified in code)
- The top-level wrapper (`bin/envctl`) does Python-version re-exec, installed-command shadow detection, and then hands off to `envctl_engine.runtime.launcher_cli:main`.
- `python/envctl_engine/runtime/launcher_cli.py:run` currently handles:
  - `--help` / `-h`
  - `install`
  - `uninstall`
  - launcher-level `doctor`
  - `--repo` extraction and forwarding to runtime
- `python/envctl_engine/runtime/launcher_support.py:launcher_usage_text` documents `--help` but does not mention `--version`.
- The runtime parser in `python/envctl_engine/runtime/command_router.py` knows `help` but has no `--version` alias, no `version` command, and `SUPPORTED_COMMANDS` currently contains exactly 33 commands without a version surface.
- Runtime help output in `python/envctl_engine/runtime/engine_runtime.py:_print_help` prints the runtime banner and supported commands, but not the package version.
- The command-dispatch and parity tests hard-code the current command inventory:
  - `tests/python/runtime/test_command_dispatch_matrix.py` asserts there are 33 supported commands.
  - `tests/python/runtime/test_engine_runtime_command_parity.py` asserts the same inventory and checks help output against `list_supported_commands()`.
- Packaging tests already lock the package version in one place:
  - `tests/python/runtime/test_cli_packaging.py:test_release_version_metadata_is_aligned_for_1_3_0`
  - it asserts `pyproject.toml` version and README release badge alignment, but does not test a user-facing `--version` command.
- User docs currently recommend install verification via `envctl --help` and `envctl doctor --repo ...`, but do not expose a version command:
  - `README.md`
  - `docs/user/getting-started.md`
  - `docs/user/faq.md`
  - `docs/operations/troubleshooting.md`

## Root cause(s) / gaps
- There is no launcher-owned version-reporting path today.
- The existing command-surface split has a clear place for launcher-only functionality, but version reporting was never added there.
- Adding `--version` incorrectly as a runtime command would create unnecessary churn:
  - it would affect `SUPPORTED_COMMANDS`,
  - expand dispatch/inventory tests,
  - and make version reporting depend on repo/runtime bootstrap even though it should not.
- There is no shared helper that resolves the package version for both installed and source-checkout contexts.
- Documentation currently lacks a simple version verification step after installation and during troubleshooting.

## Plan
### 1) Add a launcher-owned version resolution helper
- Introduce a dedicated helper in `python/envctl_engine/runtime/launcher_support.py` to resolve the user-facing envctl version.
- Preferred lookup order:
  1. installed package metadata (`importlib.metadata.version("envctl")`)
  2. source-checkout fallback from `pyproject.toml` when running from the repo wrapper
- Keep the helper small and deterministic:
  - no repo detection
  - no runtime/config/bootstrap dependency
  - no network calls
- Return a plain string version value only; formatting stays in the launcher layer.
- Edge cases to handle explicitly:
  - editable install where package metadata exists
  - source wrapper execution where metadata may not exist yet
  - malformed or missing fallback metadata should fail with a clear actionable launcher error rather than an unhandled exception

### 2) Wire `--version` into the launcher contract, not the runtime command inventory
- Update `python/envctl_engine/runtime/launcher_cli.py:run` to recognize `--version` before repo-root resolution and runtime forwarding.
- Keep this behavior aligned with existing launcher-owned handling of `--help`:
  - print version
  - exit `0`
  - do not require `--repo`
  - do not call `runtime_cli.run(...)`
- Update `python/envctl_engine/runtime/launcher_support.py:launcher_usage_text` to include `--version`.
- Keep `python/envctl_engine/runtime/command_router.py` unchanged unless implementation discovers a concrete need for runtime awareness.
  - Specifically, do not add `version` to `SUPPORTED_COMMANDS` or `COMMAND_ALIASES` unless the design intentionally expands the runtime command surface.
- Decide and document behavior for mixed arguments:
  - `envctl --version` should print version and exit.
  - `envctl --repo /path --version` should either:
    - print version and ignore `--repo`, or
    - fail with a concise launcher usage error.
  - Recommendation: allow `--repo` syntactically but ignore it for version reporting, because version is repo-independent and `--repo` is already stripped at launcher level.
  - `envctl --version extra` should fail with a clear usage error rather than silently ignoring trailing arguments.

### 3) Keep runtime help and command inventory semantics stable
- Because `--version` is launcher-owned, preserve the current runtime `list_supported_commands()` contract and help inventory semantics.
- Verify that:
  - `list-supported` style outputs remain command-only,
  - `runtime.dispatch(parse_route(["--help"], ...))` behavior stays unchanged,
  - command parity manifests and dispatch matrix tests do not need version added as a runtime command.
- If the team decides runtime help should mention that launcher-level `--version` exists, make that a doc/help copy change only, not a new runtime command.

### 4) Add packaging and launcher smoke coverage for `--version`
- Extend `tests/python/runtime/test_cli_packaging.py` with user-facing version smoke tests for:
  - editable install: installed `envctl --version` prints the package version
  - non-editable install: installed `envctl --version` prints the package version
  - explicit repo wrapper invocation: `./bin/envctl --version` reports the same version without redirect confusion
- Add launcher-level unit tests covering:
  - `python/envctl_engine/runtime/launcher_cli.py:run(["--version"])`
  - invalid trailing args behavior
  - `--repo` coexistence policy if supported
- Avoid brittle tests that hard-code formatted prose beyond the essential version contract; assert the presence of the exact current package version and stable exit code.

### 5) Update command-surface and user docs
- Update the docs that currently define launcher-owned behavior and install verification:
  - `README.md`
  - `docs/user/getting-started.md`
  - `docs/user/faq.md`
  - `docs/operations/troubleshooting.md`
  - `docs/reference/commands.md`
  - `docs/reference/important-flags.md`
  - `docs/developer/command-surface.md`
  - `docs/developer/python-runtime-guide.md` if needed for launcher/runtime boundary clarity
- Documentation changes should make these points explicit:
  - `--version` is a launcher-level flag
  - it works without repo resolution or config bootstrap
  - it is a valid post-install verification command
  - it does not expand the runtime command inventory

### 6) Add release/changelog coverage
- Append a changelog entry to `docs/changelog/main_changelog.md` when implementation lands.
- The entry should note:
  - new `--version` launcher flag
  - source/install parity for version reporting
  - any docs updates to install verification and troubleshooting guidance

## Tests (add these)
### Backend tests
- Extend `tests/python/runtime/test_cli_packaging.py`:
  - editable install exposes `envctl --version`
  - regular install exposes `envctl --version`
  - explicit repo-wrapper `--version` path reports the same version
- Add or extend launcher-specific tests, likely in `tests/python/runtime/test_command_exit_codes.py` or a new focused launcher test module:
  - `--version` returns exit code `0`
  - `--version` does not require repo bootstrap
  - invalid trailing args fail cleanly if that policy is chosen
- Add a focused helper test for version resolution fallback:
  - package metadata path
  - `pyproject.toml` fallback path
  - clear failure when neither source is available

### Frontend tests
- No frontend/UI tests are required for the first implementation because `--version` is launcher/CLI-only and does not touch dashboard or selector behavior.

### Integration/E2E tests
- Add installed-command subprocess smoke in `tests/python/runtime/test_cli_packaging.py` for:
  - editable install `envctl --version`
  - wheel/non-editable install `envctl --version`
- Add repo-wrapper subprocess smoke:
  - `bin/envctl --version` from the source checkout
  - confirm it does not depend on being inside a repo and does not emit wrapper-shadow noise for explicit path invocation

## Observability / logging (if relevant)
- No new runtime observability is required.
- Keep launcher behavior simple:
  - version prints to stdout
  - usage/argument errors print to stderr
- If a dedicated launcher helper raises an error while resolving version, surface a concise launcher-level message rather than a traceback.

## Rollout / verification
- Implementation sequence:
  1. add version-resolution helper
  2. wire launcher `--version`
  3. add unit and packaging smoke coverage
  4. update docs
  5. append changelog entry
- Verification checklist:
  1. `envctl --version` works from an installed environment.
  2. `./bin/envctl --version` works from the source checkout.
  3. `envctl --version` works outside a git repo.
  4. `envctl --help` behavior remains unchanged except for usage text mentioning `--version`.
  5. `list_supported_commands()` and runtime help command inventory remain stable unless intentionally updated.
  6. Packaging tests confirm the printed version matches `pyproject.toml`.

## Definition of done
- `envctl --version` prints the current package version and exits `0`.
- The flag works for installed commands and explicit repo wrapper paths.
- Version reporting does not require repo detection, `.envctl`, or runtime bootstrap.
- Launcher usage text and user/docs surfaces document `--version`.
- Automated tests cover launcher, packaging, and source-wrapper version reporting.
- `docs/changelog/main_changelog.md` includes the new behavior when implementation lands.

## Risk register (trade-offs or missing tests)
- Risk: sourcing version from more than one place can drift if fallback logic is careless.
  - Mitigation: prefer package metadata first and keep `pyproject.toml` fallback narrow, tested, and centralized.
- Risk: implementing `--version` as a runtime command would create unnecessary parity/test churn.
  - Mitigation: keep it launcher-owned and avoid changing `SUPPORTED_COMMANDS` unless there is a deliberate product decision to add a runtime `version` command.
- Risk: packaging smoke tests that assert exact formatting can become brittle across minor copy changes.
  - Mitigation: assert the exact version value and exit code, but keep surrounding format expectations minimal.

## Open questions (only if unavoidable)
- None. Repo evidence is sufficient to resolve the plan without blocking input.
