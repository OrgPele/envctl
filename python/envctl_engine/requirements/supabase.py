from __future__ import annotations

import os

from .common import RetryResult, run_with_retry
from envctl_engine.requirements.supabase_lifecycle.orchestrator import start_supabase_stack

# Re-export config symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.config import (
    _auth_probe_timeout_seconds,
    _auth_restart_probe_attempts,
    _auth_recreate_probe_attempts,
    _auth_restart_on_probe_failure_enabled,
    _auth_recreate_on_probe_failure_enabled,
    _db_probe_attempts,
    _db_probe_timeout_seconds,
    _db_restart_probe_attempts,
    _db_recreate_probe_attempts,
    _db_restart_on_probe_failure_enabled,
    _db_recreate_on_probe_failure_enabled,
    _native_db_start_enabled,
)

# Re-export native DB symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.native_db import (
    _start_supabase_db_native,
)

# Re-export formatting helpers for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.formatting import (
    _format_auth_service_state,
    _format_auth_service_states,
    _supabase_auth_failure_detail,
    _supabase_compose_failure_detail,
    _supabase_db_failure_detail,
    _supabase_auth_health_url,
    _supabase_local_auth_health_url,
)

# Re-export inspect helpers for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.inspect import (
    _inspect_auth_gateway_services,
)

# Re-export types for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.types import (
    _SupabaseStartupBudget,
)

# Re-export compose lifecycle symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.compose import (
    _compose_service_list,
    _resolve_service_name,
    _compose_run,
    _compose_up_timeout_seconds,
    _is_compose_port_publish_stall,
    _compose_timeout_recovered,
    _compose_services_started,
)

# Re-export gateway symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.gateway import (
    _recreate_db_service,
    _gateway_public_port_mismatch,
    _format_gateway_port_mismatch,
    _recreate_auth_gateway_services,
    _remove_auth_gateway_services,
)

# Re-export workspace symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.workspace import (
    _resolve_supabase_compose_workspace,
    build_supabase_project_name,
)

# Re-export probe symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.probe import (
    _auth_services_progressing,
    _wait_for_auth_health_while_progressing,
    _probe_db_listener,
    _record_db_probe_stage,
    _record_compose_network_recovery_stage,
    _is_compose_network_recovery_marker,
    _probe_supabase_auth_health_with_attempts,
    _probe_supabase_auth_health,
    _condense_probe_error,
)

# Re-export reliability contract symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.reliability_contract import (
    evaluate_managed_supabase_reliability_contract,
    evaluate_supabase_reliability_contract,
    read_fingerprint,
    write_fingerprint,
    SupabaseReliabilityContract,
)


__all__ = [
    "os",
    "start_supabase_stack",
    "start_supabase_with_retry",
    "_auth_probe_timeout_seconds",
    "_auth_restart_probe_attempts",
    "_auth_recreate_probe_attempts",
    "_auth_restart_on_probe_failure_enabled",
    "_auth_recreate_on_probe_failure_enabled",
    "_db_probe_attempts",
    "_db_probe_timeout_seconds",
    "_db_restart_probe_attempts",
    "_db_recreate_probe_attempts",
    "_db_restart_on_probe_failure_enabled",
    "_db_recreate_on_probe_failure_enabled",
    "_native_db_start_enabled",
    "_start_supabase_db_native",
    "_format_auth_service_state",
    "_format_auth_service_states",
    "_supabase_auth_failure_detail",
    "_supabase_compose_failure_detail",
    "_supabase_db_failure_detail",
    "_supabase_auth_health_url",
    "_supabase_local_auth_health_url",
    "_inspect_auth_gateway_services",
    "_SupabaseStartupBudget",
    "_compose_service_list",
    "_resolve_service_name",
    "_compose_run",
    "_compose_up_timeout_seconds",
    "_is_compose_port_publish_stall",
    "_compose_timeout_recovered",
    "_compose_services_started",
    "_recreate_db_service",
    "_gateway_public_port_mismatch",
    "_format_gateway_port_mismatch",
    "_recreate_auth_gateway_services",
    "_remove_auth_gateway_services",
    "_resolve_supabase_compose_workspace",
    "build_supabase_project_name",
    "_auth_services_progressing",
    "_wait_for_auth_health_while_progressing",
    "_probe_db_listener",
    "_record_db_probe_stage",
    "_record_compose_network_recovery_stage",
    "_is_compose_network_recovery_marker",
    "_probe_supabase_auth_health_with_attempts",
    "_probe_supabase_auth_health",
    "_condense_probe_error",
    "evaluate_managed_supabase_reliability_contract",
    "evaluate_supabase_reliability_contract",
    "read_fingerprint",
    "write_fingerprint",
    "SupabaseReliabilityContract",
]


def start_supabase_with_retry(
    start,
    reserve_next,
    port: int,
    max_retries: int = 3,  # noqa: ANN001
) -> RetryResult:
    return run_with_retry(initial_port=port, start=start, reserve_next=reserve_next, max_retries=max_retries)
