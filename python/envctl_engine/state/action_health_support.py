from __future__ import annotations

import sys
from typing import Any

from envctl_engine.requirements.component_ports import component_resource_ports, dependency_display_port
from envctl_engine.requirements.core import dependency_definitions as _dependency_definitions
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state.project_runtime import dependency_mode_summary
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.status_symbols import health_status_badge, health_status_severity


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


class StateActionHealthSupport:
    def health_payload(
        self,
        *,
        state: RunState,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        status_counts: dict[str, int],
        recent_failures: list[str],
        failing_services: list[str],
        requirement_issues: list[dict[str, object]],
        total_projects: int,
        strict: bool = False,
        cwd_project: str | None = None,
        warnings: list[dict[str, object]] | None = None,
        runtime_diagnostics: dict[str, object] | None = None,
    ) -> dict[str, object]:
        health_status = self.health_status_summary(
            service_rows=service_rows,
            dependency_rows=dependency_rows,
            failing_services=failing_services,
            requirement_issues=requirement_issues,
            recent_failures=recent_failures,
        )
        dependency_summary = dependency_mode_summary(state)
        return {
            "run_id": state.run_id,
            "mode": state.mode,
            "projects": total_projects,
            "services": service_rows,
            "dependencies": dependency_rows,
            "status_counts": status_counts,
            "healthy": bool(health_status["ok"]),
            "ok": bool(health_status["ok"]),
            "overall": health_status["overall"],
            "blocking": bool(health_status["blocking"]),
            "strict_blocking": bool(strict and health_status["optional_failures"]),
            "critical_services_healthy": bool(health_status["critical_services_healthy"]),
            "optional_failures": health_status["optional_failures"],
            "critical_failures": health_status["critical_failures"],
            "dependency_mode": dependency_summary["dependency_mode"],
            "shared_dependencies": dependency_summary["shared_dependencies"],
            "cwd_project": cwd_project,
            "warnings": list(warnings or []),
            "runtime_diagnostics": runtime_diagnostics or {"projects": {}, "warnings": []},
            "issues": {
                "failing_services": list(failing_services),
                "requirement_issues": requirement_issues,
                "recent_failures": list(recent_failures),
            },
        }

    def health_status_summary(
        self,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        failing_services: list[str],
        requirement_issues: list[dict[str, object]],
        recent_failures: list[str],
    ) -> dict[str, object]:
        optional_failures: list[str] = []
        critical_failures: list[str] = []
        for row in service_rows:
            status = str(row.get("status", "unknown"))
            bad_or_degraded = health_status_severity(status) == "bad" or bool(row.get("degraded"))
            if not bad_or_degraded:
                continue
            identifier = str(row.get("service_slug") or row.get("name") or "service")
            if bool(row.get("critical", True)):
                critical_failures.append(str(row.get("name") or identifier))
            else:
                optional_failures.append(identifier)
        for row in dependency_rows:
            if health_status_severity(str(row.get("status", "unknown"))) == "bad":
                critical_failures.append(str(row.get("component") or "dependency"))
        critical_failures.extend(
            str(issue.get("component") or issue.get("service") or issue) for issue in requirement_issues
        )
        for service_name in failing_services:
            if service_name not in critical_failures and service_name not in optional_failures:
                critical_failures.append(service_name)
        for failure in recent_failures:
            optional_identifier = self.optional_recent_failure_identifier(failure, service_rows)
            if optional_identifier is None:
                critical_failures.append(failure)
            else:
                optional_failures.append(optional_identifier)
        deduped_critical = _dedupe_strings(critical_failures)
        deduped_optional = _dedupe_strings(optional_failures)
        blocking = bool(deduped_critical)
        if blocking:
            overall = "unhealthy"
        elif deduped_optional:
            overall = "degraded"
        else:
            overall = "healthy"
        return {
            "ok": not blocking,
            "overall": overall,
            "blocking": blocking,
            "critical_services_healthy": not any(
                bool(row.get("critical", True)) and health_status_severity(str(row.get("status", "unknown"))) == "bad"
                for row in service_rows
            ),
            "optional_failures": deduped_optional,
            "critical_failures": deduped_critical,
        }

    @staticmethod
    def optional_recent_failure_identifier(failure: str, service_rows: list[dict[str, object]]) -> str | None:
        failure_text = str(failure).casefold()
        matched_optional: str | None = None
        for row in service_rows:
            tokens = {
                str(row.get("name") or "").strip(),
                str(row.get("service_slug") or "").strip(),
                str(row.get("type") or "").strip(),
            }
            tokens = {token for token in tokens if token}
            if not tokens or not any(token.casefold() in failure_text for token in tokens):
                continue
            if bool(row.get("critical", True)):
                return None
            matched_optional = str(row.get("service_slug") or row.get("name") or "service").strip()
        return matched_optional

    def requirement_health_rows(self, state: RunState) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        definitions = tuple(self._dependency_definitions())
        component_order = {definition.id: index for index, definition in enumerate(definitions)}
        for project, requirements in state.requirements.items():
            for definition in definitions:
                component = definition.id
                data = requirements.component(component)
                if not bool(data.get("enabled", False)):
                    continue
                status = str(data.get("runtime_status", "")).strip().lower()
                if not status:
                    if bool(data.get("simulated", False)):
                        status = "simulated"
                    elif bool(data.get("success", False)):
                        status = "healthy"
                    else:
                        status = "unknown"
                rows.append(
                    {
                        "project": project,
                        "component": component,
                        "status": status,
                        "port": dependency_display_port(component, data),
                        "resources": component_resource_ports(data),
                    }
                )
        rows.sort(key=lambda row: (str(row["project"]).lower(), component_order.get(str(row["component"]), 99)))
        return rows

    def health_service_rows(self, state: RunState) -> list[dict[str, object]]:
        def _service_row(service: ServiceRecord) -> dict[str, object]:
            project = str(getattr(service, "project", "") or "").strip()
            if not project:
                project = self.runtime.project_name_from_service(service.name) or "unknown"
            port = service.actual_port if service.actual_port is not None else service.requested_port
            return {
                "project": project,
                "name": service.name,
                "type": service.type,
                "service_slug": str(getattr(service, "service_slug", "") or "").strip() or service.type,
                "status": str(service.status or "unknown").strip().lower() or "unknown",
                "port": port,
                "requested_port": service.requested_port,
                "actual_port": service.actual_port,
                "pid": service.pid,
                "listener_expected": service.listener_expected,
                "cwd": service.cwd,
                "log_path": service.log_path,
                "public_url": getattr(service, "public_url", None),
                "health_url": getattr(service, "health_url", None),
                "failure_detail": getattr(service, "failure_detail", None),
                "critical": getattr(service, "critical", True),
                "degraded": getattr(service, "degraded", False),
                "runtime_kind": getattr(service, "runtime_kind", "process"),
                "container_id": getattr(service, "container_id", None),
                "container_name": getattr(service, "container_name", None),
                "container_image": getattr(service, "container_image", None),
            }

        rows = self._parallel_service_map(
            list(state.services.values()),
            _service_row,
        )
        rows.sort(key=lambda row: (str(row["project"]).lower(), str(row["name"]).lower()))
        return rows

    def _dependency_definitions(self) -> tuple[object, ...]:
        return tuple(_dependency_definitions())

    @staticmethod
    def health_project_order(
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
    ) -> list[str]:
        order: list[str] = []
        seen: set[str] = set()
        for row in [*service_rows, *dependency_rows]:
            project = str(row.get("project", "")).strip() or "unknown"
            lowered = project.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            order.append(project)
        return order

    def print_health_rows(
        self,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        palette: dict[str, str],
    ) -> None:
        reset = palette["reset"]
        bold = palette["bold"]
        blue = palette["blue"]
        magenta = palette["magenta"]
        dim = palette["dim"]
        project_order = self.health_project_order(service_rows=service_rows, dependency_rows=dependency_rows)
        for project in project_order:
            print(f"\n{bold}{blue}{project}{reset}")
            project_services = [
                row for row in service_rows if str(row.get("project", "")).strip().lower() == project.lower()
            ]
            project_dependencies = [
                row for row in dependency_rows if str(row.get("project", "")).strip().lower() == project.lower()
            ]
            if project_services:
                print(f"  {magenta}Services ({len(project_services)}){reset}")
                for row in project_services:
                    status = str(row.get("status", "unknown"))
                    icon = self.health_status_icon(status)
                    icon_color = self.health_status_color(status, palette)
                    service_name = str(row.get("name", "service"))
                    display_name = self.health_service_display_name(project=project, service_name=service_name)
                    port_raw = row.get("port")
                    port_text = str(port_raw) if port_raw is not None else "n/a"
                    print(
                        f"    {icon_color}{icon}{reset} {display_name:<12} "
                        f"{dim}status={status:<10} port={port_text}{reset}"
                    )
            if project_dependencies:
                print(f"  {magenta}Dependencies ({len(project_dependencies)}){reset}")
                for row in project_dependencies:
                    status = str(row.get("status", "unknown"))
                    icon = self.health_status_icon(status)
                    icon_color = self.health_status_color(status, palette)
                    port_text = row.get("port") if row.get("port") is not None else "n/a"
                    component = str(row.get("component", "dependency"))
                    print(
                        f"    {icon_color}{icon}{reset} {component:<12} "
                        f"{dim}status={status:<10} port={port_text}{reset}"
                    )

    @staticmethod
    def health_service_display_name(*, project: str, service_name: str) -> str:
        project_prefix = f"{project} "
        if service_name.startswith(project_prefix):
            trimmed = service_name[len(project_prefix) :].strip()
            if trimmed:
                return trimmed
        return service_name

    @classmethod
    def health_status_counts(
        cls,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
    ) -> dict[str, int]:
        counters = {"ok": 0, "warn": 0, "bad": 0}
        for row in [*service_rows, *dependency_rows]:
            status = str(row.get("status", "unknown"))
            severity = health_status_severity(status)
            counters[severity] += 1
        return counters

    @staticmethod
    def health_status_icon(status: str) -> str:
        return health_status_badge(status).symbol

    @staticmethod
    def health_status_color(status: str, palette: dict[str, str]) -> str:
        severity = health_status_badge(status).severity
        if severity == "success":
            return palette["green"]
        if severity == "warning":
            return palette["yellow"]
        if severity == "neutral":
            return palette["dim"]
        return palette["red"]

    def health_palette(self) -> dict[str, str]:
        env = getattr(self.runtime, "env", {})
        interactive_tty = RuntimeTerminalUI._can_interactive_tty()
        enabled = colors_enabled(env, stream=sys.stdout, interactive_tty=interactive_tty)
        if not enabled:
            return {
                "reset": "",
                "bold": "",
                "dim": "",
                "cyan": "",
                "blue": "",
                "magenta": "",
                "green": "",
                "yellow": "",
                "red": "",
            }
        return {
            "reset": "\033[0m",
            "bold": "\033[1m",
            "dim": "\033[2m",
            "cyan": "\033[36m",
            "blue": "\033[34m",
            "magenta": "\033[35m",
            "green": "\033[32m",
            "yellow": "\033[33m",
            "red": "\033[31m",
        }

    def _health_payload(self, **kwargs: Any) -> dict[str, object]:
        return self.health_payload(**kwargs)

    def _health_status_summary(self, **kwargs: Any) -> dict[str, object]:
        return self.health_status_summary(**kwargs)

    def _optional_recent_failure_identifier(self, failure: str, service_rows: list[dict[str, object]]) -> str | None:
        return self.optional_recent_failure_identifier(failure, service_rows)

    def _requirement_health_rows(self, state: RunState) -> list[dict[str, object]]:
        return self.requirement_health_rows(state)

    def _health_service_rows(self, state: RunState) -> list[dict[str, object]]:
        return self.health_service_rows(state)

    def _health_project_order(
        self,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
    ) -> list[str]:
        return self.health_project_order(service_rows=service_rows, dependency_rows=dependency_rows)

    def _print_health_rows(
        self,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        palette: dict[str, str],
    ) -> None:
        self.print_health_rows(service_rows=service_rows, dependency_rows=dependency_rows, palette=palette)

    def _health_service_display_name(self, *, project: str, service_name: str) -> str:
        return self.health_service_display_name(project=project, service_name=service_name)

    def _health_status_counts(
        self,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
    ) -> dict[str, int]:
        return self.health_status_counts(service_rows=service_rows, dependency_rows=dependency_rows)

    def _health_status_icon(self, status: str) -> str:
        return self.health_status_icon(status)

    def _health_status_color(self, status: str, palette: dict[str, str]) -> str:
        return self.health_status_color(status, palette)

    def _health_palette(self) -> dict[str, str]:
        return self.health_palette()
