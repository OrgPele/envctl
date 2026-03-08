from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import Any

from envctl_engine.requirements.core import RequirementComponentResult, dependency_ids


@dataclass(slots=True)
class PortPlan:
    project: str
    requested: int
    assigned: int
    final: int
    source: str
    retries: int = 0


@dataclass(slots=True)
class ServiceRecord:
    name: str
    type: str
    cwd: str
    pid: int | None = None
    requested_port: int | None = None
    actual_port: int | None = None
    log_path: str | None = None
    status: str = "unknown"
    synthetic: bool = False
    started_at: float | None = None
    listener_pids: list[int] | None = None


@dataclass(slots=True)
class RequirementsResult:
    project: str
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    health: str = "unknown"
    failures: list[str] = field(default_factory=list)
    db: InitVar[dict[str, Any] | None] = None
    redis: InitVar[dict[str, Any] | None] = None
    supabase: InitVar[dict[str, Any] | None] = None
    n8n: InitVar[dict[str, Any] | None] = None

    def __post_init__(
        self,
        db: dict[str, Any] | None,
        redis: dict[str, Any] | None,
        supabase: dict[str, Any] | None,
        n8n: dict[str, Any] | None,
    ) -> None:
        normalized: dict[str, dict[str, Any]] = {}
        for dependency_id in dependency_ids():
            normalized[dependency_id] = {}
        raw = dict(self.components)
        legacy_values = {
            "postgres": db,
            "redis": redis,
            "supabase": supabase,
            "n8n": n8n,
        }
        for key, legacy_value in legacy_values.items():
            if isinstance(legacy_value, dict):
                raw.setdefault(key, legacy_value)
        for component_id, payload in raw.items():
            normalized[component_id] = RequirementComponentResult.from_payload(component_id, payload).to_dict()
        self.components = normalized

    def component(self, component_id: str) -> dict[str, Any]:
        normalized = str(component_id).strip().lower()
        if normalized == "db":
            normalized = "postgres"
        existing = self.components.get(normalized)
        if isinstance(existing, dict):
            return existing
        self.components[normalized] = {}
        return self.components[normalized]

    @property
    def db(self) -> dict[str, Any]:
        return self.component("postgres")

    @db.setter
    def db(self, value: dict[str, Any]) -> None:
        self.components["postgres"] = RequirementComponentResult.from_payload("postgres", value).to_dict()

    @property
    def redis(self) -> dict[str, Any]:
        return self.component("redis")

    @redis.setter
    def redis(self, value: dict[str, Any]) -> None:
        self.components["redis"] = RequirementComponentResult.from_payload("redis", value).to_dict()

    @property
    def supabase(self) -> dict[str, Any]:
        return self.component("supabase")

    @supabase.setter
    def supabase(self, value: dict[str, Any]) -> None:
        self.components["supabase"] = RequirementComponentResult.from_payload("supabase", value).to_dict()

    @property
    def n8n(self) -> dict[str, Any]:
        return self.component("n8n")

    @n8n.setter
    def n8n(self, value: dict[str, Any]) -> None:
        self.components["n8n"] = RequirementComponentResult.from_payload("n8n", value).to_dict()


@dataclass(slots=True)
class RunState:
    run_id: str
    mode: str
    schema_version: str = "1.0"
    backend_mode: str = "python"
    services: dict[str, ServiceRecord] = field(default_factory=dict)
    requirements: dict[str, RequirementsResult] = field(default_factory=dict)
    pointers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
