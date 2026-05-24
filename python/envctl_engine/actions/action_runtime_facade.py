from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, cast


class ActionRuntimeFacade:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def _resolve_callable(self, *names: str) -> Callable[..., object]:
        for name in names:
            candidate = getattr(self._runtime, name, None)
            if callable(candidate):
                return cast(Callable[..., object], candidate)
        joined = ", ".join(names)
        raise AttributeError(f"{type(self._runtime).__name__} is missing required action collaborator ({joined})")

    @property
    def env(self) -> Mapping[str, str]:
        return cast(Mapping[str, str], getattr(self._runtime, "env", {}))

    @property
    def config(self) -> Any:
        return getattr(self._runtime, "config", None)

    @property
    def process_runner(self) -> Any:
        return getattr(self._runtime, "process_runner", None)

    @property
    def state_repository(self) -> Any:
        return getattr(self._runtime, "state_repository", None)

    def discover_projects(self, *, mode: str) -> list[object]:
        discover = self._resolve_callable("discover_projects", "_discover_projects")
        return cast(list[object], discover(mode=mode))

    def selectors_from_passthrough(self, passthrough_args: list[str]) -> set[str]:
        selectors = self._resolve_callable("selectors_from_passthrough", "_selectors_from_passthrough")
        return cast(set[str], selectors(passthrough_args))

    def load_existing_state(self, *, mode: str) -> object | None:
        load_state = getattr(self._runtime, "load_existing_state", None)
        if callable(load_state):
            return load_state(mode=mode)
        legacy = self._resolve_callable("_try_load_existing_state")
        return legacy(mode=mode)

    def project_name_from_service(self, service_name: str) -> str:
        project_name = self._resolve_callable("project_name_from_service", "_project_name_from_service")
        return str(project_name(service_name))

    def select_project_targets(self, **kwargs: object) -> object:
        select = self._resolve_callable("select_project_targets", "_select_project_targets")
        return select(**kwargs)

    def unsupported_command(self, command: str) -> int:
        unsupported = self._resolve_callable("unsupported_command", "_unsupported_command")
        return int(unsupported(command))

    def emit(self, event: str, **payload: object) -> None:
        emitter = getattr(self._runtime, "_emit", None)
        if callable(emitter):
            emitter(event, **payload)
            return
        emitter = getattr(self._runtime, "emit", None)
        if callable(emitter):
            emitter(event, **payload)

    def _emit(self, event: str, **payload: object) -> None:
        self.emit(event, **payload)

    def split_command(self, raw: str, *, replacements: Mapping[str, str]) -> list[str]:
        splitter = self._resolve_callable("split_command", "_split_command")
        return cast(list[str], splitter(raw, replacements=replacements))

    def _trees_root_for_worktree(self, worktree_root: Path) -> Path:
        resolver = self._resolve_callable("trees_root_for_worktree", "_trees_root_for_worktree")
        return cast(Path, resolver(worktree_root))

    def _blast_worktree_before_delete(
        self,
        *,
        project_name: str,
        project_root: Path,
        source_command: str,
    ) -> list[str]:
        cleanup = getattr(self._runtime, "_blast_worktree_before_delete", None)
        if callable(cleanup):
            return cast(
                list[str],
                cleanup(
                    project_name=project_name,
                    project_root=project_root,
                    source_command=source_command,
                ),
            )
        cleanup = getattr(self._runtime, "blast_worktree_before_delete", None)
        if callable(cleanup):
            return cast(
                list[str],
                cleanup(
                    project_name=project_name,
                    project_root=project_root,
                    source_command=source_command,
                ),
            )
        return []

    @property
    def raw_runtime(self) -> Any:
        return self._runtime
