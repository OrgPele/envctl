## 2026-03-16 - Explicit-path repo wrapper selection

### Scope
Implemented the wrapper-selection change from `MAIN_TASK.md` so explicitly executed repo wrappers keep control even when another installed `envctl` exists on `PATH`, while preserving the existing bare-command safety behavior.

### Key behavior changes
- `bin/envctl`
  - now preserves the original wrapper invocation token in `ENVCTL_WRAPPER_ORIGINAL_ARGV0` before Python-version re-exec
  - routes redirect decisions through launcher support and only re-execs a shadowed installed binary when policy allows it
- `python/envctl_engine/runtime/launcher_support.py`
  - added `ORIGINAL_WRAPPER_ARGV0_ENVVAR`
  - added `is_explicit_wrapper_path(...)` for wrapper-intent classification
  - added `select_envctl_reexec_target(...)` for redirect policy
  - kept `find_shadowed_installed_envctl(...)` focused on PATH discovery
- `tests/python/runtime/test_cli_packaging.py`
  - added helper-level coverage for explicit absolute paths, relative paths, symlinked paths, bare-name behavior, `ENVCTL_USE_REPO_WRAPPER=1`, and preserved invocation intent after Python re-exec
  - added subprocess smoke coverage for explicit wrapper execution, bare-name redirect to a shadowed installed binary, and forced-wrapper override behavior
- Docs updated to reflect the new contract:
  - `docs/reference/commands.md`
  - `docs/operations/troubleshooting.md`
  - `docs/developer/python-runtime-guide.md`
  - `docs/developer/runtime-lifecycle.md`

### Files / modules touched
- `bin/envctl`
- `python/envctl_engine/runtime/launcher_support.py`
- `tests/python/runtime/test_cli_packaging.py`
- `docs/reference/commands.md`
- `docs/operations/troubleshooting.md`
- `docs/developer/python-runtime-guide.md`
- `docs/developer/runtime-lifecycle.md`
- `docs/changelog/main_changelog.md`

### Tests run + results
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_cli_packaging`
  - result: `Ran 15 tests`, `OK`

### Config / env / migrations
- No migrations.
- `ENVCTL_USE_REPO_WRAPPER=1` remains supported and unchanged.
- Added internal wrapper-intent preservation via `ENVCTL_WRAPPER_ORIGINAL_ARGV0` for Python-version re-exec continuity.

### Risks / notes
- Shebang-launched scripts on macOS can normalize bare PATH execution into a path-bearing `argv[0]`. The implementation explicitly covers relative explicit paths, explicit symlink paths, and PATH-resolved shim paths, but a bare invocation that resolves directly to the real wrapper file remains an inherent ambiguity in that platform behavior.
