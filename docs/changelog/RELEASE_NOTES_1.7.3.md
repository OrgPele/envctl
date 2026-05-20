# envctl 1.7.3

`envctl` 1.7.3 is a hotfix release on top of `1.7.2`. It keeps the dynamic DB/Redis dependency inference from 1.7.2 and fixes the next exposed issue: Main-mode managed dependency containers should not default to the well-known PostgreSQL/Redis host ports on every run.

## Why This Hotfix Matters

Supportopia-shaped repos can omit explicit dependency toggles while still requesting `DATABASE_URL` and `REDIS_URL` through active backend launch env templates. Version 1.7.2 correctly inferred that PostgreSQL and Redis should start, but Main-mode dependency port planning still began at the default base ports (`5432` and `6379`). That made the Docker launch look like static manual DB/Redis wiring instead of per-run dynamic dependency wiring.

## Highlights

### Session-scoped Main dependency ports

- Main-mode managed PostgreSQL, Redis, and n8n dependency ports now use a session-scoped offset when the dependency port bases are the built-in defaults.
- Backend/frontend app ports remain stable at their configured bases, so normal app URLs do not move just because dependency containers are dynamic.
- PostgreSQL, Redis, and n8n keep the same offset within a run, preserving the existing non-overlapping service bands.
- Custom dependency port bases remain honored as fixed Main-mode ports for backwards compatibility.
- Operators can opt out explicitly with `ENVCTL_DYNAMIC_MAIN_DEPENDENCY_PORTS=false`.

### Supportopia behavior

With Supportopia's current `.envctl` shape, envctl now plans dynamic Main dependency ports such as:

```text
backend=8000 frontend=9000 db=<5432+session_offset> redis=<6379+session_offset>
```

The generated `DATABASE_URL`, `SQLALCHEMY_DATABASE_URL`, `ASYNC_DATABASE_URL`, and `REDIS_URL` point at those dynamically planned ports.

## Docker Host Note

If Docker reports `iptables: No chain/target/match by that name` while adding a DNAT rule, Docker's bridge/NAT tables on the host are broken. Dynamic envctl ports avoid static `5432`/`6379` bindings, but that host-level Docker networking problem still requires repairing or restarting Docker.

## Verification

Validated in the implementation worktree with:

- `./.venv/bin/python -m pytest tests/python/shared/test_port_plan.py tests/python/runtime/test_engine_runtime_command_parity.py::EngineRuntimeCommandParityTests::test_runtime_uses_session_scoped_main_dependency_ports_by_default tests/python/runtime/test_engine_runtime_command_parity.py::EngineRuntimeCommandParityTests::test_runtime_can_disable_session_scoped_main_dependency_ports tests/python/runtime/test_engine_runtime_real_startup.py::EngineRuntimeRealStartupTests::test_main_backend_launch_env_templates_enable_dynamic_database_and_redis_requirements -q` ✅

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

## Upgrade Notes

- No manual `.envctl` edit is required for default Supportopia-shaped dynamic DB/Redis launch env templates.
- Set `ENVCTL_DYNAMIC_MAIN_DEPENDENCY_PORTS=false` only if Main-mode managed dependencies must bind exactly to `DB_PORT`, `REDIS_PORT`, and `N8N_PORT_BASE`.
- If Docker fails with a missing `DOCKER` iptables chain, restart/repair Docker before retrying; that is independent of envctl's port choice.
