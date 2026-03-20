# Envctl Runtime Requirements Bootstrap Before Use

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make `envctl` treat its own runtime dependencies as mandatory before operational use, instead of discovering gaps piecemeal after dispatch begins.
  - Align the two existing dependency manifests so source-wrapper/bootstrap flows and package-installed (`pipx`/`pip`) flows resolve the same runtime package set.
  - Replace the current contributor-only remediation hint on runtime prereq failure with operator-appropriate guidance for the actual invocation path.
- Non-goals:
  - Changing downstream target-repo dependency bootstrap (`backend/requirements.txt`, Poetry installs, frontend package-manager installs).
  - Adding hidden runtime `pip install` side effects to normal `envctl` commands.
  - Reworking launcher-only commands such as `--version`, `--help`, `doctor --repo`, `install`, or `uninstall` so they require the full interactive runtime stack.
- Assumptions:
  - The user note refers to `envctl`'s own runtime prerequisites (`python/requirements.txt`), not project-under-test dependencies.
  - `python/requirements.txt` should remain the human-readable/source-checkout bootstrap manifest, while `pyproject.toml` must remain an exact install-time mirror for `pipx` and normal package installs.
  - Runtime commands should fail fast with clear remediation instead of auto-installing packages at execution time.

## Goal (user experience)
Someone using `envctl` through either `./bin/envctl` from a source checkout or an installed command from `pipx` should get one predictable result before any operational command runs: either the interpreter already has the full `envctl` runtime dependency set, or `envctl` stops immediately with a path-appropriate remediation message. Operators should no longer hit a mix of `rich`-only prereq checks, later `textual`/`prompt_toolkit`/`psutil` gaps, or contributor-oriented `.[dev]` guidance when they only need runtime prerequisites.

## Business logic and data model mapping
- Runtime dependency manifests:
  - `pyproject.toml:[project.dependencies]`
  - `python/requirements.txt`
- Launcher and runtime call path:
  - `bin/envctl:main`
  - `python/envctl_engine/runtime/launcher_cli.py:run`
  - `python/envctl_engine/runtime/launcher_cli.py:_forward_to_engine`
  - `python/envctl_engine/runtime/cli.py:run`
  - `python/envctl_engine/runtime/cli.py:check_prereqs`
- Current per-module dependency probes:
  - `python/envctl_engine/config/wizard_domain.py:_require_interactive_config_bootstrap`
  - `python/envctl_engine/config/wizard_domain.py:_textual_stack_available`
  - `python/envctl_engine/ui/capabilities.py:textual_importable`
  - `python/envctl_engine/ui/capabilities.py:prompt_toolkit_available`
  - `python/envctl_engine/ui/terminal_session.py:prompt_toolkit_available`
  - `python/envctl_engine/shared/process_probe.py:psutil_available`
- Existing bootstrap/release contract surfaces:
  - `python/envctl_engine/runtime/release_gate.py:CANONICAL_BOOTSTRAP_COMMANDS`
  - `docs/developer/contributing.md`
  - `docs/developer/testing-and-validation.md`
- Existing test coverage around packaging and prereqs:
  - `tests/python/runtime/test_prereq_policy.py`
  - `tests/python/runtime/test_command_exit_codes.py`
  - `tests/python/runtime/test_cli_packaging.py`
  - `tests/python/shared/test_validation_workflow_contract.py`
  - `tests/python/ui/test_ui_dependency_contract.py`

## Current behavior (verified in code)
- `envctl` has two runtime dependency manifests today, and they currently happen to match:
  - `pyproject.toml` declares `prompt_toolkit`, `psutil`, `rich`, and `textual` in `[project.dependencies]`.
  - `python/requirements.txt` lists the same four packages.
- Package-installed flows and source-checkout flows do not share one enforced dependency contract:
  - `README.md`, `docs/user/getting-started.md`, `docs/user/faq.md`, and `docs/operations/troubleshooting.md` position `pipx install "git+https://github.com/kfiramar/envctl.git"` as the primary end-user install path.
  - `docs/developer/contributing.md` and `docs/developer/testing-and-validation.md` position `.venv/bin/python -m pip install -e '.[dev]'` as the contributor bootstrap path.
- The launcher path is stable and centralized:
  - `bin/envctl:main` delegates to `python/envctl_engine/runtime/launcher_cli.py:main`.
  - `launcher_cli.run(...)` resolves launcher-owned commands first, then forwards operational commands into `runtime.cli.run(...)`.
- Runtime prereq enforcement is incomplete and inconsistent:
  - `python/envctl_engine/runtime/cli.py:check_prereqs` currently checks required executables plus only one Python module: `rich`.
  - The same function emits contributor/bootstrap guidance from `python/envctl_engine/runtime/release_gate.py:CANONICAL_BOOTSTRAP_COMMANDS`, which currently resolves to repo-local `.venv` creation and `pip install -e '.[dev]'`.
  - `python/envctl_engine/config/wizard_domain.py:_require_interactive_config_bootstrap` separately checks `textual` and `rich` and tells users to run `python -m pip install -r python/requirements.txt`.
  - `python/envctl_engine/ui/capabilities.py` and `python/envctl_engine/shared/process_probe.py` expose availability checks for `prompt_toolkit`, `textual`, and `psutil`, but `runtime.cli.check_prereqs(...)` does not require them up front.
- Existing tests lock in the fragmented behavior instead of a full-runtime contract:
  - `tests/python/runtime/test_prereq_policy.py:test_start_fails_when_rich_missing` asserts the current `rich`-only failure path and expects the contributor `.venv` / `.[dev]` hint.
  - `tests/python/runtime/test_command_exit_codes.py:test_start_command_fails_when_rich_dependency_missing` covers the same behavior at CLI level.
  - `tests/python/runtime/test_cli_packaging.py` verifies installability and runtime-dependency availability only when `_installed_env(..., install_deps=True)` is requested; there is no contract test asserting that `python/requirements.txt` and `pyproject.toml` stay in sync or that all runtime packages are checked before operational dispatch.

## Root cause(s) / gaps
- The runtime dependency contract is split across packaging metadata, a source-checkout requirements file, CLI prereq policy, config bootstrap checks, and UI capability helpers, with no shared authority module.
- `runtime.cli.check_prereqs(...)` under-enforces the supported runtime by checking only `rich`, even though repo evidence shows `textual`, `prompt_toolkit`, and `psutil` are also first-class runtime dependencies.
- Remediation messaging is invocation-agnostic:
  - installed-command users are told to bootstrap a repo-local contributor venv,
  - source-checkout/bootstrap code sometimes points at `python/requirements.txt`,
  - docs tell end users that `pipx` installs the package dependencies already.
- There is no automated parity check preventing `python/requirements.txt` from drifting away from `[project.dependencies]`, so the source bootstrap story and the `pipx` install story can silently diverge.
- Packaging smoke proves installability and can prove dependency-complete imports when asked, but it does not currently lock the behavior that operational commands must reject incomplete runtime environments before use.

## Plan
### 1) Define one authoritative runtime-dependency policy shared by packaging, prereq checks, and messaging
- Introduce a dedicated runtime-dependency contract helper under the runtime/bootstrap area, owned by the launcher/runtime layer rather than by UI modules.
- The helper should:
  - parse and normalize `python/requirements.txt`,
  - parse and normalize `pyproject.toml:[project.dependencies]`,
  - expose the required import/module map for prereq enforcement (`prompt_toolkit`, `psutil`, `rich`, `textual`),
  - expose path-appropriate remediation text for:
    - source-checkout / repo-wrapper usage,
    - contributor repo-local bootstrap,
    - installed-package usage where package metadata should already have installed the runtime deps.
- Keep launcher-safe commands exempt:
  - `--version`
  - `--help`
  - launcher `doctor`
  - `install`
  - `uninstall`
- Treat operational runtime commands as dependency-complete only when the full runtime module set is present, not just `rich`.

### 2) Fail fast before operational use when any required runtime package is missing
- Refactor `python/envctl_engine/runtime/cli.py:check_prereqs` to consume the new shared dependency contract instead of the current hard-coded `{"rich"}` set.
- Apply the full-runtime check consistently to the existing prereq-gated command family:
  - `start`
  - `plan`
  - `restart`
- Review whether the same enforcement should also cover other interactive/runtime-owned commands that can reach Textual or prompt-toolkit surfaces without startup, and document the chosen boundary in code comments and docs.
- Unify config-bootstrap behavior so `python/envctl_engine/config/wizard_domain.py:_require_interactive_config_bootstrap` reuses the same dependency contract and remediation copy instead of maintaining a second partial rule.
- Preserve the current product stance of explicit failure rather than background package installation.

### 3) Make the remediation copy match the actual install path
- Replace the current contributor-only missing-package hint from `CANONICAL_BOOTSTRAP_COMMANDS` in end-user runtime prereq failures.
- Define explicit remediation variants:
  - Source checkout / `./bin/envctl`:
    - install runtime deps from `python/requirements.txt` into the interpreter that will run `envctl`.
  - Contributor validation lane:
    - keep `.venv/bin/python -m pip install -e '.[dev]'` in contributor docs and release/readiness tooling.
  - Installed command (`pipx` / `pip`):
    - point users at reinstall/repair of the installed package instead of a repo-relative `python/requirements.txt` path that may not exist locally.
- Thread that copy through:
  - `python/envctl_engine/runtime/cli.py`
  - `python/envctl_engine/config/wizard_domain.py`
  - any related troubleshooting/help text that currently mixes runtime-prereq remediation with contributor bootstrap guidance.

### 4) Add machine-checked parity so `python/requirements.txt` and package metadata cannot drift
- Extend packaging/contract coverage so normalized `python/requirements.txt` entries must match normalized `pyproject.toml:[project.dependencies]`.
- Put this in a fast Python test lane and, if practical, the shipability gate, because drift would break the exact user requirement in scope:
  - source-checkout users would install one set of packages,
  - `pipx` would install another.
- Keep the parity check narrow:
  - compare runtime dependencies only,
  - do not conflate them with `[project.optional-dependencies.dev]`.

### 5) Update user and developer docs so the install story is explicit instead of implied
- Update end-user docs to distinguish three paths cleanly:
  - `pipx` install: package metadata installs runtime dependencies automatically.
  - source wrapper / local checkout usage: install `python/requirements.txt` before using `./bin/envctl`.
  - contributor workflow: use `.venv/bin/python -m pip install -e '.[dev]'`.
- Update the files that currently encode conflicting expectations:
  - `README.md`
  - `docs/user/getting-started.md`
  - `docs/user/faq.md`
  - `docs/operations/troubleshooting.md`
  - `docs/developer/contributing.md`
  - `docs/developer/testing-and-validation.md`
  - `docs/developer/config-and-bootstrap.md`
- Ensure docs no longer imply that a missing runtime package in an installed `pipx` env should be fixed through repo-local editable-install commands.

### 6) Expand packaging and prereq coverage around incomplete environments
- Extend packaging smoke to prove the new contract, not just metadata installability.
- Add or update scenarios for:
  - no-runtime-deps install: operational command fails before dispatch with the new path-appropriate message,
  - dependency-complete install: operational prereq gate passes and safe runtime command paths proceed,
  - source-wrapper/remediation copy: error text points at `python/requirements.txt` rather than contributor-only `.[dev]` guidance,
  - installed-package/remediation copy: error text points at reinstall/repair instead of repo-local paths.
- Reuse the existing `tests/python/runtime/test_cli_packaging.py` wheelhouse pattern for dependency-complete isolated envs instead of adding a second packaging harness.

## Tests (add these)
### Backend tests
- Extend `tests/python/runtime/test_prereq_policy.py`:
  - runtime prereq failures enumerate all missing runtime modules, not just `rich`,
  - source-checkout/runtime remediation points at `python/requirements.txt`,
  - installed-package remediation does not point at repo-local `.[dev]` bootstrap unless the invocation is explicitly repo-contributor scoped.
- Extend `tests/python/runtime/test_command_exit_codes.py`:
  - CLI exit path for missing runtime dependencies remains `1`,
  - stderr contains the new invocation-appropriate remediation copy.
- Extend `tests/python/runtime/test_cli_packaging.py`:
  - normalized `pyproject.toml:[project.dependencies]` exactly matches `python/requirements.txt`,
  - isolated no-deps install fails on an operational command before runtime dispatch with the new message,
  - dependency-complete install still supports an operational smoke command such as `doctor --repo` or `start` with infra disabled.
- Add or extend a release/contract test (either `tests/python/shared/test_validation_workflow_contract.py` or a new focused module) so runtime bootstrap docs cannot drift from the chosen source-wrapper guidance.

### Frontend tests
- Extend `tests/python/ui/test_ui_dependency_contract.py` if the shared runtime-dependency helper becomes the owner of `textual` / `prompt_toolkit` availability semantics.
- Keep frontend coverage narrow:
  - assert UI capability helpers remain consistent with the centralized runtime dependency map,
  - avoid duplicating prereq-policy assertions already covered in runtime tests.

### Integration/E2E tests
- Add an isolated-environment subprocess smoke covering:
  1. install package without dependencies,
  2. run an operational command,
  3. assert deterministic prereq failure before dispatch,
  4. assert remediation matches invocation type.
- Add a source-checkout smoke lane that executes `./bin/envctl` with missing runtime packages and verifies the stderr points at `python/requirements.txt`.
- If shipability coverage is expanded, add a requirements-manifest parity assertion there so release readiness fails when `pyproject.toml` and `python/requirements.txt` diverge.

## Observability / logging (if relevant)
- No new runtime telemetry is required for this slice.
- The stderr contract should become more explicit:
  - list the missing runtime modules,
  - identify whether the failure is a source-checkout/bootstrap issue or an installed-package repair issue,
  - avoid contributor-only remediation in end-user contexts.

## Rollout / verification
- Phase A: centralize the runtime dependency contract and remediation text.
- Phase B: tighten prereq enforcement to the full runtime package set.
- Phase C: add packaging/parity coverage so both manifests and both install paths stay aligned.
- Phase D: update docs together so source, contributor, and `pipx` stories no longer conflict.
- Verification checklist:
  1. `pyproject.toml` runtime dependencies and `python/requirements.txt` are machine-checked as identical.
  2. `./bin/envctl` with missing runtime packages fails before operational dispatch and points at `python/requirements.txt`.
  3. Installed-command no-deps/incomplete-runtime smoke fails before operational dispatch with installed-package repair guidance.
  4. Contributor docs still preserve the repo-local `.venv` + `.[dev]` validation lane without being reused as the end-user runtime-fix message.
  5. Dependency-complete packaging smoke remains green.

## Definition of done
- `envctl` treats its runtime prerequisites as mandatory before operational use, not just `rich`.
- The source-checkout bootstrap path and the package-install path are aligned by test, not by convention.
- Missing-runtime-package failures are clear, deterministic, and specific to the way `envctl` was invoked.
- Docs explicitly distinguish source-wrapper bootstrap, contributor bootstrap, and `pipx` install behavior.
- Regression tests cover both missing-dependency and dependency-complete environments.

## Risk register (trade-offs or missing tests)
- Risk: enforcing the full runtime package set may block commands that currently limp along with only a subset of dependencies installed.
  - Mitigation: keep launcher-safe commands exempt and document the runtime-command boundary explicitly.
- Risk: invocation-aware remediation text can become brittle if wrapper/install detection relies on ambient env vars or cwd heuristics.
  - Mitigation: centralize detection in one helper and cover repo-wrapper vs installed-command subprocess cases in packaging tests.
- Risk: treating `python/requirements.txt` as an operator-facing bootstrap manifest adds another contract to maintain alongside `pyproject.toml`.
  - Mitigation: add a strict normalized parity test and, if practical, a shipability-gate check.
- Risk: installed-package repair guidance may still be imperfect across `pipx`, `pip`, and editable installs.
  - Mitigation: keep the first implementation narrow around the supported `pipx` path documented in `README.md` and `docs/user/getting-started.md`, then widen if new install paths become first-class.

## Open questions (only if unavoidable)
- None. The plan resolves the scope from repo evidence and assumes the requested prerequisite enforcement is about `envctl`'s own runtime dependencies, not downstream repo bootstrap.
