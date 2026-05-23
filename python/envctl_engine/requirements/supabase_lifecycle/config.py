from __future__ import annotations

from collections.abc import Mapping

from ..adapter_base import env_bool, env_float, env_int


def _auth_probe_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS", 5.0, minimum=0.5)
    return parsed if parsed > 0 else 5.0


def _auth_restart_probe_attempts(env: Mapping[str, str] | None) -> int:
    return env_int(env, "ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS", 2, minimum=1)


def _auth_recreate_probe_attempts(env: Mapping[str, str] | None) -> int:
    return env_int(env, "ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS", 3, minimum=1)


def _auth_restart_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_AUTH_RESTART_ON_PROBE_FAILURE", True)


def _auth_recreate_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_AUTH_RECREATE_ON_PROBE_FAILURE", True)


def _db_probe_attempts(env: Mapping[str, str] | None) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_PROBE_ATTEMPTS", 2, minimum=1)


def _db_probe_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_PROBE_TIMEOUT_SECONDS", 10.0)
    if parsed <= 0:
        return 30.0
    return parsed


def _db_restart_probe_attempts(env: Mapping[str, str] | None, *, default: int) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_RESTART_PROBE_ATTEMPTS", default, minimum=1)


def _db_recreate_probe_attempts(env: Mapping[str, str] | None, *, default: int) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_RECREATE_PROBE_ATTEMPTS", default, minimum=1)


def _db_restart_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE", True)


def _db_recreate_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_RECREATE_ON_PROBE_FAILURE", True)


def _native_db_start_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_START_NATIVE", False)



def _supabase_startup_budget_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS", 120.0, minimum=0.5)
    return parsed if parsed > 0 else 120.0


