from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class DependencyAdapter(Protocol):
    def project_env(
        self, *, runtime: Any, context: Any, requirements: Any, route: Any | None = None
    ) -> dict[str, str]: ...

    def cleanup(self, *, runtime: Any, project_name: str, project_root: Any) -> list[str] | None: ...


@dataclass(frozen=True, slots=True)
class DependencyResourceSpec:
    name: str
    legacy_port_key: str
    config_port_keys: tuple[str, ...]
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class DependencyDefinition:
    id: str
    display_name: str
    order: int
    resources: tuple[DependencyResourceSpec, ...]
    mode_enable_keys: dict[str, tuple[str, ...]]
    default_enabled: dict[str, bool]
    env_projector: Callable[..., dict[str, str]] | None = None
    native_starter: Callable[..., object] | None = None
    cleanup_handler: Callable[..., list[str] | None] | None = None
    dashboard_enabled: bool = True
    health_label: str | None = None

    def enabled_by_default(self, mode: str) -> bool:
        return bool(self.default_enabled.get(str(mode).strip().lower(), False))

    def enable_keys_for_mode(self, mode: str) -> tuple[str, ...]:
        return tuple(self.mode_enable_keys.get(str(mode).strip().lower(), ()))


@dataclass(slots=True)
class RequirementComponentResult:
    id: str
    enabled: bool = False
    success: bool = False
    simulated: bool = False
    health: str = "unknown"
    resources: dict[str, int] = field(default_factory=dict)
    retries: int = 0
    reason_code: str | None = None
    failure_class: str | None = None
    error: str | None = None
    runtime_status: str | None = None
    container_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "enabled": self.enabled,
            "success": self.success,
            "simulated": self.simulated,
            "health": self.health,
            "resources": dict(self.resources),
            "retries": self.retries,
        }
        if self.reason_code is not None:
            payload["reason_code"] = self.reason_code
        if self.failure_class is not None:
            payload["failure_class"] = self.failure_class
        if self.error is not None:
            payload["error"] = self.error
        if self.runtime_status is not None:
            payload["runtime_status"] = self.runtime_status
        if self.container_name is not None:
            payload["container_name"] = self.container_name
        for key, value in self.resources.items():
            if key == "primary" and "final" not in payload:
                payload["final"] = value
            elif key == "requested" and "requested" not in payload:
                payload["requested"] = value
        return payload

    @classmethod
    def from_payload(cls, component_id: str, payload: dict[str, Any] | None) -> "RequirementComponentResult":
        data = payload or {}
        resources = data.get("resources") if isinstance(data.get("resources"), dict) else {}
        normalized_resources = {
            str(key): int(value) for key, value in resources.items() if isinstance(value, int) and value > 0
        }
        requested = data.get("requested")
        final = data.get("final")
        if isinstance(requested, int) and requested > 0:
            normalized_resources.setdefault("requested", requested)
        if isinstance(final, int) and final > 0:
            normalized_resources.setdefault("primary", final)
        return cls(
            id=component_id,
            enabled=bool(data.get("enabled", False)),
            success=bool(data.get("success", False)),
            simulated=bool(data.get("simulated", False)),
            health=str(data.get("health", "unknown") or "unknown"),
            resources=normalized_resources,
            retries=int(data.get("retries", 0) or 0),
            reason_code=str(data.get("reason_code")) if data.get("reason_code") is not None else None,
            failure_class=str(data.get("failure_class")) if data.get("failure_class") is not None else None,
            error=str(data.get("error")) if data.get("error") is not None else None,
            runtime_status=str(data.get("runtime_status")) if data.get("runtime_status") is not None else None,
            container_name=str(data.get("container_name")) if data.get("container_name") is not None else None,
        )
