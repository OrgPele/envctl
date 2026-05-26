from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from envctl_engine.actions.action_command_support import service_types_from_route_services
from envctl_engine.actions.action_test_support import TestCommandSpec, TestExecutionSpec, TestTargetContext
from envctl_engine.runtime.command_router import Route


class AdditionalServiceConfig(Protocol):
    def app_service_by_name(self, name: str) -> object | None: ...


@dataclass(frozen=True, slots=True)
class AdditionalServiceTestPlanner:
    route: Route
    targets: list[object]
    target_contexts: list[TestTargetContext]
    config: AdditionalServiceConfig
    split_command: Callable[[str, dict[str, str]], list[str]]
    action_replacements_builder: Callable[..., dict[str, str]]

    def build(self) -> list[TestExecutionSpec]:
        specs: list[TestExecutionSpec] = []
        for service_name in self._selected_service_names():
            service = self._service(service_name)
            raw_command = self._raw_test_command(service, service_name)
            dir_name = str(getattr(service, "dir_name", "") or "").strip()
            for target in self.target_contexts:
                replacements = dict(self.action_replacements_builder(self.targets, target=target.target_obj))
                command = self.split_command(raw_command, replacements)
                cwd = self._service_cwd(target.project_root, dir_name)
                specs.append(
                    TestExecutionSpec(
                        index=0,
                        spec=TestCommandSpec(
                            command=command,
                            cwd=cwd,
                            source=f"configured_service:{service_name}",
                        ),
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

    def _selected_service_names(self) -> list[str]:
        return sorted(service_types_from_route_services(self.route) - {"backend", "frontend"})

    def _service(self, service_name: str) -> object:
        service = self.config.app_service_by_name(service_name)
        if service is None:
            raise RuntimeError(f"Unknown additional service {service_name!r} for envctl test --service")
        return service

    def _raw_test_command(self, service: object, service_name: str) -> str:
        raw_command = str(getattr(service, "test_cmd", "") or "").strip()
        if raw_command:
            return raw_command
        env_suffix = str(getattr(service, "env_suffix", "") or service_name.upper().replace("-", "_"))
        raise RuntimeError(
            f"No test command configured for additional service {service_name!r}. "
            f"Set ENVCTL_SERVICE_{env_suffix}_TEST_CMD to use envctl test --service {service_name}."
        )

    @staticmethod
    def _service_cwd(project_root: Path, dir_name: str) -> Path:
        return project_root / dir_name if dir_name and dir_name != "." else project_root


def additional_service_test_execution_specs(
    *,
    route: Route,
    targets: list[object],
    target_contexts: list[TestTargetContext],
    config: AdditionalServiceConfig,
    split_command: Callable[[str, dict[str, str]], list[str]],
    action_replacements_builder: Callable[..., dict[str, str]],
) -> list[TestExecutionSpec]:
    return AdditionalServiceTestPlanner(
        route=route,
        targets=targets,
        target_contexts=target_contexts,
        config=config,
        split_command=split_command,
        action_replacements_builder=action_replacements_builder,
    ).build()
