"""Machine-readable reason codes for observability events and gate failures."""

from enum import Enum


class GateFailureReason(Enum):
    """Reason codes for strict gate failures."""

    PARITY_MANIFEST_INCOMPLETE = "parity_manifest_incomplete"
    PARTIAL_COMMANDS_PRESENT = "partial_commands_present"
    SYNTHETIC_STATE_DETECTED = "synthetic_state_detected"
    RUNTIME_TRUTH_FAILED = "runtime_truth_failed"
    REQUIREMENT_ISSUES = "requirement_issues"
    SHELL_MIGRATION_FAILED = "shell_migration_failed"
    SHELL_UNMIGRATED_EXCEEDED = "shell_unmigrated_exceeded"
    SHELL_PARTIAL_KEEP_EXCEEDED = "shell_partial_keep_exceeded"
    SHELL_INTENTIONAL_KEEP_EXCEEDED = "shell_intentional_keep_exceeded"


class ServiceFailureReason(Enum):
    """Reason codes for service startup failures."""

    PORT_BIND_FAILED = "port_bind_failed"
    PORT_UNAVAILABLE = "port_unavailable"
    PROCESS_SPAWN_FAILED = "process_spawn_failed"
    PROCESS_EXITED = "process_exited"
    HEALTH_CHECK_FAILED = "health_check_failed"
    DEPENDENCY_MISSING = "dependency_missing"
    CONFIGURATION_INVALID = "configuration_invalid"


class RequirementFailureReason(Enum):
    """Reason codes for requirement startup failures."""

    DATABASE_CONNECTION_FAILED = "database_connection_failed"
    DATABASE_MIGRATION_FAILED = "database_migration_failed"
    REDIS_CONNECTION_FAILED = "redis_connection_failed"
    SUPABASE_INIT_FAILED = "supabase_init_failed"
    SUPABASE_AUTH_FAILED = "supabase_auth_failed"
    N8N_INIT_FAILED = "n8n_init_failed"
    NETWORK_UNREACHABLE = "network_unreachable"


class RequirementLifecycleReason(Enum):
    BIND_CONFLICT_RETRYABLE = "bind_conflict_retryable"
    TRANSIENT_PROBE_TIMEOUT_RETRYABLE = "transient_probe_timeout_retryable"
    BOOTSTRAP_SOFT_FAILURE = "bootstrap_soft_failure"
    HARD_START_FAILURE = "hard_start_failure"
    ENVCTL_OWNED_STALE_RESOURCE_CLEANED = "envctl_owned_stale_resource_cleaned"
    ENVCTL_OWNED_STALE_RESOURCE_CLEANUP_FAILED = "envctl_owned_stale_resource_cleanup_failed"
    BIND_CONFLICT_UNRESOLVED = "bind_conflict_unresolved"


class PortFailureReason(Enum):
    """Reason codes for port allocation failures."""

    PORT_IN_USE = "port_in_use"
    PORT_PERMISSION_DENIED = "port_permission_denied"
    PORT_RANGE_EXHAUSTED = "port_range_exhausted"
    LOCK_ACQUISITION_FAILED = "lock_acquisition_failed"


class CleanupFailureReason(Enum):
    """Reason codes for cleanup operation failures."""

    PROCESS_KILL_FAILED = "process_kill_failed"
    VOLUME_REMOVAL_FAILED = "volume_removal_failed"
    LOCK_RELEASE_FAILED = "lock_release_failed"
    PARTIAL_CLEANUP = "partial_cleanup"


def reason_code_to_string(reason: Enum) -> str:
    """Convert reason code enum to string value."""
    return reason.value
