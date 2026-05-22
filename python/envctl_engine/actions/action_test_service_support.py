from __future__ import annotations

from pathlib import Path
from typing import Callable

from envctl_engine.actions.action_command_support import service_types_from_route_services
from envctl_engine.actions.action_test_support import TestCommandSpec, TestExecutionSpec, TestTargetContext
from envctl_engine.runtime.command_router import Route


def additional_service_test_execution_specs(
    *,
    route: Route,
    targets: list[object],
    target_contexts: list[TestTargetContext],
    config: object,
    split_command: Callable[[str, dict[str, str]], list[str]],
    action_replacements_builder: Callable[..., dict[str, str]],
) -> list[TestExecutionSpec]:
    service_types = service_types_from_route_services(route) - {"backend", "frontend"}
    if not service_types:
        return []
    specs: list[TestExecutionSpec] = []
    for service_name in sorted(service_types):
        service = config.app_service_by_name(service_name) if hasattr(config, "app_service_by_name") else None
        if service is None:
            raise RuntimeError(f"Unknown additional service {service_name!r} for envctl test --service")
        raw_command = str(getattr(service, "test_cmd", "") or "").strip()
        if not raw_command:
            env_suffix = str(getattr(service, "env_suffix", "") or service_name.upper().replace("-", "_"))
            raise RuntimeError(
                f"No test command configured for additional service {service_name!r}. "
                f"Set ENVCTL_SERVICE_{env_suffix}_TEST_CMD to use envctl test --service {service_name}."
            )
        dir_name = str(getattr(service, "dir_name", "") or "").strip()
        for target in target_contexts:
            replacements = dict(action_replacements_builder(targets, target=target.target_obj))
            command = split_command(raw_command, replacements)
            cwd = target.project_root / dir_name if dir_name and dir_name != "." else target.project_root
            specs.append(
                TestExecutionSpec(
                    index=0,
                    spec=TestCommandSpec(command=command, cwd=Path(cwd), source=f"configured_service:{service_name}"),
                    args=[],
                    resolved_source=f"configured_service:{service_name}",
                    project_name=target.project_name,
                    project_root=target.project_root,
                    target_obj=target.target_obj,
                )
            )
    return [
        TestExecutionSpec(
            index=index,
            spec=spec.spec,
            args=spec.args,
            resolved_source=spec.resolved_source,
            project_name=spec.project_name,
            project_root=spec.project_root,
            target_obj=spec.target_obj,
        )
        for index, spec in enumerate(specs, start=1)
    ]
