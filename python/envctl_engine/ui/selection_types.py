from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TargetSelection:
    all_selected: bool = False
    untested_selected: bool = False
    project_names: list[str] = field(default_factory=list)
    service_names: list[str] = field(default_factory=list)
    cancelled: bool = False

    def apply_to_route(self, route) -> None:  # noqa: ANN001
        if self.cancelled:
            return
        if self.all_selected:
            route.flags["all"] = True
        if self.untested_selected:
            route.flags["untested"] = True
        if self.project_names:
            route.projects.extend(self.project_names)
        if self.service_names:
            existing = route.flags.get("services")
            if isinstance(existing, list):
                existing.extend(self.service_names)
            else:
                route.flags["services"] = list(self.service_names)

    def empty(self) -> bool:
        return not (self.all_selected or self.untested_selected or self.project_names or self.service_names or self.cancelled)
