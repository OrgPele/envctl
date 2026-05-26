from __future__ import annotations

from typing import Any

from envctl_engine.requirements.core.models import DependencyDefinition
from envctl_engine.requirements.external_env import external_dependency_resources
from envctl_engine.requirements.external_env import external_dependency_validation_error
from envctl_engine.requirements.external_env import primary_external_port
from envctl_engine.requirements.external_probe import external_dependency_probe_error
from envctl_engine.requirements.orchestrator import FailureClass, RequirementOutcome


def external_dependency_outcome(
    *,
    runtime: Any,
    definition: DependencyDefinition,
    plan: Any,
) -> RequirementOutcome:
    dependency = definition.id
    validation_error = external_dependency_validation_error(runtime, dependency)
    error = validation_error
    if validation_error is None:
        error = external_dependency_probe_error(runtime, dependency)
    resources = external_dependency_resources(runtime, definition)
    final_port = primary_external_port(resources, definition) or int(getattr(plan, "final", 0) or 0)
    requested_port = int(getattr(plan, "requested", final_port) or final_port)
    return RequirementOutcome(
        service_name=dependency,
        success=error is None,
        requested_port=requested_port,
        final_port=final_port,
        retries=0,
        failure_class=(
            FailureClass.HARD_START_FAILURE
            if validation_error
            else (FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE if error else None)
        ),
        error=error,
    )


__all__ = [
    "external_dependency_outcome",
]
