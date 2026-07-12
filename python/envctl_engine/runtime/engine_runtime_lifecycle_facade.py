from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from envctl_engine.runtime.engine_runtime_lifecycle_support import (
    blast_worktree_before_delete as runtime_blast_worktree_before_delete,
    release_requirement_ports as runtime_release_requirement_ports,
    service_port as runtime_service_port,
    terminate_service_record as runtime_terminate_service_record,
    terminate_services_from_state as runtime_terminate_services_from_state,
    terminate_started_services as runtime_terminate_started_services,
)
from envctl_engine.runtime.engine_runtime_misc_support import (
    release_port_session as runtime_release_port_session,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, RunState

if TYPE_CHECKING:
    from envctl_engine.runtime.lifecycle_cleanup_orchestrator import LifecycleCleanupOrchestrator


class RuntimeLifecycleFacadeMixin:
    lifecycle_cleanup_orchestrator: "LifecycleCleanupOrchestrator" = cast("LifecycleCleanupOrchestrator", object())

    def _release_port_session(self) -> None:
        runtime_release_port_session(self)

    def _clear_runtime_state(self, *, command: str, aggressive: bool = False, route: Route | None = None) -> bool:
        return self.lifecycle_cleanup_orchestrator.clear_runtime_state(
            command=command,
            aggressive=aggressive,
            route=route,
        )

    def _blast_all_print_and_kill_listener_maps(
        self,
        *,
        kill_pid_ports: dict[int, set[int]],
        docker_pid_ports: dict[int, set[int]],
    ) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_print_and_kill_listener_maps(
            kill_pid_ports=kill_pid_ports,
            docker_pid_ports=docker_pid_ports,
        )

    def _blast_all_port_range(self) -> list[int]:
        return self.lifecycle_cleanup_orchestrator.blast_all_port_range()

    def _blast_all_kill_orchestrator_processes(self) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_kill_orchestrator_processes()

    def _blast_all_docker_cleanup(self, *, route: Route | None) -> int:
        return self.lifecycle_cleanup_orchestrator.blast_all_docker_cleanup(route=route)

    def _terminate_started_services(self, services: dict[str, object]) -> set[str]:
        return runtime_terminate_started_services(self, services)

    def _terminate_services_from_state(
        self,
        state: RunState,
        *,
        selected_services: set[str] | None,
        aggressive: bool,
        verify_ownership: bool,
    ) -> set[str]:
        return runtime_terminate_services_from_state(
            self,
            state,
            selected_services=selected_services,
            aggressive=aggressive,
            verify_ownership=verify_ownership,
        )

    def _terminate_service_record(self, service: object, *, aggressive: bool, verify_ownership: bool) -> bool:
        return runtime_terminate_service_record(
            self,
            service,
            aggressive=aggressive,
            verify_ownership=verify_ownership,
        )

    @staticmethod
    def _service_port(service: object) -> int | None:
        return runtime_service_port(service)

    def _release_requirement_ports(self, requirements: RequirementsResult) -> None:
        runtime_release_requirement_ports(self, requirements)

    def _blast_worktree_before_delete(
        self,
        *,
        project_name: str,
        project_root: Path,
        source_command: str = "delete-worktree",
    ) -> list[str]:
        return runtime_blast_worktree_before_delete(
            self,
            project_name=project_name,
            project_root=project_root,
            source_command=source_command,
        )
