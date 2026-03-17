## 2026-03-17 - Launcher-owned `--version` for installed command and repo wrapper

### Scope
Implemented a supported `envctl --version` surface end-to-end so the package-installed command and the explicit source wrapper both print the current version immediately, without repo detection, `.envctl`, or runtime bootstrap.

### Key behavior changes
- `python/envctl_engine/runtime/launcher_support.py`
  - added `resolve_envctl_version(...)` with metadata-first lookup and source `pyproject.toml` fallback
  - keeps failure handling launcher-level and concise when version metadata is unavailable or malformed
- `python/envctl_engine/runtime/launcher_cli.py`
  - recognizes `--version` before repo-root resolution and runtime forwarding
  - ignores `--repo` for version reporting
  - rejects trailing arguments for `--version`
- `python/envctl_engine/runtime/cli.py`
  - added matching early `--version` handling for the installed console-script entrypoint while leaving runtime command inventory unchanged
- `tests/python/runtime/test_launcher_version.py`
  - covers metadata resolution, `pyproject.toml` fallback, missing-fallback error handling, launcher semantics, and installed-entrypoint semantics
- `tests/python/runtime/test_cli_packaging.py`
  - adds subprocess smoke coverage for editable install, regular install, and explicit `./bin/envctl --version`
- Docs updated to treat `--version` as the normal install/troubleshooting verification step:
  - `README.md`
  - `docs/user/getting-started.md`
  - `docs/user/faq.md`
  - `docs/operations/troubleshooting.md`
  - `docs/reference/commands.md`
  - `docs/reference/important-flags.md`
  - `docs/developer/command-surface.md`
  - `docs/developer/python-runtime-guide.md`

### File paths / modules touched
- `python/envctl_engine/runtime/launcher_support.py`
- `python/envctl_engine/runtime/launcher_cli.py`
- `python/envctl_engine/runtime/cli.py`
- `tests/python/runtime/test_launcher_version.py`
- `tests/python/runtime/test_cli_packaging.py`
- `README.md`
- `docs/user/getting-started.md`
- `docs/user/faq.md`
- `docs/operations/troubleshooting.md`
- `docs/reference/commands.md`
- `docs/reference/important-flags.md`
- `docs/developer/command-surface.md`
- `docs/developer/python-runtime-guide.md`
- `docs/changelog/main_changelog.md`

### Tests run + results
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_launcher_version tests.python.runtime.test_cli_packaging`
  - result: `Ran 35 tests`, `OK`
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_command_exit_codes tests.python.runtime.test_cli_router_parity tests.python.runtime.test_command_dispatch_matrix tests.python.runtime.test_engine_runtime_command_parity tests.python.runtime.test_launcher_version tests.python.runtime.test_cli_packaging`
  - result: `Ran 125 tests`, `OK`

### Config / env / migrations
- No config or persistence changes.
- No migrations.
- No new environment variables.

### Risks / notes
- Installed metadata remains the primary source of truth; the source-checkout `pyproject.toml` fallback exists only for wrapper execution without installed package metadata.
- Runtime command inventory intentionally remains at 33 commands; `--version` is not added to `SUPPORTED_COMMANDS` or `list-commands`.
