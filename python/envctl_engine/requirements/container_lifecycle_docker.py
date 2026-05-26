from __future__ import annotations

from dataclasses import dataclass

from envctl_engine.shared.protocols import CommandResult

from .adapter_lifecycle_models import ContainerLifecycleTemplate
from .container_state_support import (
    container_exists,
    container_host_port,
    container_state_error,
    container_status,
    stop_and_remove_container,
)
from .docker_runtime import docker_port_publish_lock, run_docker


@dataclass(frozen=True, slots=True)
class ContainerLifecycleDockerClient:
    template: ContainerLifecycleTemplate

    def exists(self) -> tuple[bool, str | None]:
        template = self.template
        return container_exists(
            template.process_runner,
            container_name=template.container_name,
            cwd=template.project_root,
            env=template.env,
        )

    def host_port(self) -> tuple[int | None, str | None]:
        template = self.template
        return container_host_port(
            template.process_runner,
            container_name=template.container_name,
            container_port=template.container_port,
            cwd=template.project_root,
            env=template.env,
        )

    def status(self) -> tuple[str | None, str | None]:
        template = self.template
        return container_status(
            template.process_runner,
            container_name=template.container_name,
            cwd=template.project_root,
            env=template.env,
        )

    def state_error(self) -> tuple[str | None, str | None]:
        template = self.template
        return container_state_error(
            template.process_runner,
            container_name=template.container_name,
            cwd=template.project_root,
            env=template.env,
        )

    def stop_and_remove(self) -> str | None:
        template = self.template
        return stop_and_remove_container(
            template.process_runner,
            container_name=template.container_name,
            cwd=template.project_root,
            env=template.env,
        )

    def start(self) -> tuple[CommandResult | None, str | None]:
        return self._run_locked(["start", self.template.container_name], timeout=120.0)

    def restart(self) -> tuple[CommandResult | None, str | None]:
        return self._run_locked(["restart", self.template.container_name], timeout=120.0)

    def _run_locked(self, args: list[str], *, timeout: float) -> tuple[CommandResult | None, str | None]:
        template = self.template
        with docker_port_publish_lock(template.env):
            return run_docker(
                template.process_runner,
                args,
                cwd=template.project_root,
                env=template.env,
                timeout=timeout,
            )


__all__ = tuple(name for name in globals() if not name.startswith("_"))
