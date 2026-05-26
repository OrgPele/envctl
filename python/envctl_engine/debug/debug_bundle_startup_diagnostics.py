from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from envctl_engine.shared.parsing import parse_float, parse_int


@dataclass(slots=True)
class StartupDiagnostics:
    startup_breakdown: dict[str, object]
    slowest_components: list[dict[str, object]]
    resume_skip_reasons: dict[str, int]
    requirements_stage_hotspots: list[dict[str, object]]
    service_bootstrap_hotspots: list[dict[str, object]]
    service_attach_hotspots: list[dict[str, object]]
    known_total_ms: float
    requirements_total_ms: float
    has_adapter_stage_detail: bool
    has_command_timing_detail: bool


def _payload_float(payload: Mapping[str, object], key: str) -> float:
    return parse_float(payload.get(key), 0.0)


def _payload_int(payload: Mapping[str, object], key: str, default: int = 0) -> int:
    return parse_int(payload.get(key), default)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def analyze_startup_diagnostics(timeline: Sequence[Mapping[str, object]]) -> StartupDiagnostics:
    startup_timeline = [item for item in timeline if str(item.get("source", "")).strip().lower() == "debug"]
    state = _StartupAccumulator()
    for item in startup_timeline:
        state.observe(item)
    return state.result()


class _StartupAccumulator:
    def __init__(self) -> None:
        self.startup_window_first: int | None = None
        self.startup_window_last: int | None = None
        self.startup_execution_mode = "unknown"
        self.startup_workers = 0
        self.startup_projects: list[str] = []
        self.requirements_total_ms = 0.0
        self.service_total_ms = 0.0
        self.resume_restore_total_ms = 0.0
        self.project_breakdown: dict[str, dict[str, object]] = {}
        self.slowest_components: list[dict[str, object]] = []
        self.resume_skip_reasons: dict[str, int] = {}
        self.requirements_stage_totals: dict[str, float] = {}
        self.service_bootstrap_totals: dict[str, float] = {}
        self.service_attach_totals: dict[str, float] = {}
        self.has_adapter_stage_detail = False
        self.has_command_timing_detail = False
        self.phase_totals: dict[str, float] = {}

    def observe(self, item: Mapping[str, object]) -> None:
        event_name = str(item.get("event", "")).strip()
        self._observe_window(event_name, item)
        if event_name == "startup.execution":
            self._observe_startup_execution(item)
        elif event_name in {"state.auto_resume.skipped", "state.run_reuse.skipped"}:
            self._observe_resume_skip(item)
        elif event_name == "requirements.timing.summary":
            self._observe_requirements_summary(item)
        elif event_name in {"startup.phase", "resume.phase"}:
            self._observe_phase(event_name, item)
        elif event_name in {"artifacts.write", "artifacts.runtime_readiness_report"}:
            self._observe_artifact_timing(event_name, item)
        elif event_name in {"service.bootstrap.phase", "service.attach.phase"}:
            self._observe_service_phase(event_name, item)
        elif event_name == "service.timing.summary":
            self._observe_service_summary(item)
        elif event_name == "resume.restore.project_timing":
            self._observe_resume_restore_project(item)
        elif event_name == "requirements.timing.component":
            self._observe_requirements_component(item)
        elif event_name == "service.timing.component":
            self._observe_service_component(item)
        elif event_name == "requirements.adapter.command_timing":
            self._observe_adapter_command_timing(item)
        elif event_name == "requirements.adapter.stage":
            self.has_adapter_stage_detail = True
        elif event_name == "requirements.adapter":
            self._observe_adapter_stage_map(item)

    def result(self) -> StartupDiagnostics:
        self._complete_project_totals()
        if not self.slowest_components:
            self._fill_slowest_from_project_summaries()
        project_rows = sorted(
            self.project_breakdown.values(),
            key=lambda row: _payload_float(row, "total_ms"),
            reverse=True,
        )
        self.slowest_components.sort(key=lambda item: _payload_float(item, "duration_ms"), reverse=True)
        requirements_stage_hotspots = _hotspots("stage", self.requirements_stage_totals)
        service_bootstrap_hotspots = _hotspots("target", self.service_bootstrap_totals)
        service_attach_hotspots = _hotspots("target", self.service_attach_totals)

        measured_window_ms = 0.0
        if (
            self.startup_window_first is not None
            and self.startup_window_last is not None
            and self.startup_window_last >= self.startup_window_first
        ):
            measured_window_ms = round((self.startup_window_last - self.startup_window_first) / 1_000_000.0, 2)
        known_total_ms = round(self.requirements_total_ms + self.service_total_ms + self.resume_restore_total_ms, 2)
        unknown_ms = round(max(0.0, measured_window_ms - known_total_ms), 2)
        unknown_ratio = round((unknown_ms / measured_window_ms), 4) if measured_window_ms > 0 else 0.0
        startup_breakdown: dict[str, object] = {
            "execution_mode": self.startup_execution_mode,
            "workers": self.startup_workers,
            "projects": self.startup_projects,
            "measured_window_ms": measured_window_ms,
            "known_total_ms": known_total_ms,
            "unknown_ms": unknown_ms,
            "unknown_ratio": unknown_ratio,
            "requirements_total_ms": round(self.requirements_total_ms, 2),
            "service_total_ms": round(self.service_total_ms, 2),
            "resume_restore_total_ms": round(self.resume_restore_total_ms, 2),
            "phase_breakdown": [
                {"phase": phase, "total_ms": round(total, 2)}
                for phase, total in sorted(self.phase_totals.items(), key=lambda item: item[1], reverse=True)
            ],
            "project_breakdown": project_rows[:20],
        }
        return StartupDiagnostics(
            startup_breakdown=startup_breakdown,
            slowest_components=self.slowest_components,
            resume_skip_reasons=self.resume_skip_reasons,
            requirements_stage_hotspots=requirements_stage_hotspots,
            service_bootstrap_hotspots=service_bootstrap_hotspots,
            service_attach_hotspots=service_attach_hotspots,
            known_total_ms=known_total_ms,
            requirements_total_ms=self.requirements_total_ms,
            has_adapter_stage_detail=self.has_adapter_stage_detail,
            has_command_timing_detail=self.has_command_timing_detail,
        )

    def _observe_window(self, event_name: str, item: Mapping[str, object]) -> None:
        ts_value = item.get("ts_mono_ns")
        ts_mono_ns = parse_int(ts_value, -1) if isinstance(ts_value, int) else None
        if event_name not in _STARTUP_EVENTS or ts_mono_ns is None:
            return
        self.startup_window_first = (
            ts_mono_ns if self.startup_window_first is None else min(self.startup_window_first, ts_mono_ns)
        )
        self.startup_window_last = (
            ts_mono_ns if self.startup_window_last is None else max(self.startup_window_last, ts_mono_ns)
        )

    def _observe_startup_execution(self, item: Mapping[str, object]) -> None:
        self.startup_execution_mode = str(item.get("mode", "")).strip() or self.startup_execution_mode
        self.startup_workers = _payload_int(item, "workers", self.startup_workers)
        raw_projects = item.get("projects")
        if isinstance(raw_projects, list):
            self.startup_projects = [str(project).strip() for project in raw_projects if str(project).strip()]

    def _observe_resume_skip(self, item: Mapping[str, object]) -> None:
        reason = str(item.get("reason", "")).strip() or "unknown"
        self.resume_skip_reasons[reason] = self.resume_skip_reasons.get(reason, 0) + 1

    def _observe_requirements_summary(self, item: Mapping[str, object]) -> None:
        project = str(item.get("project", "")).strip() or "unknown"
        duration_ms = _payload_float(item, "duration_ms")
        self.requirements_total_ms += duration_ms
        entry = self._project_entry(project)
        entry["requirements_ms"] = round(_payload_float(entry, "requirements_ms") + duration_ms, 2)

    def _observe_phase(self, event_name: str, item: Mapping[str, object]) -> None:
        phase = str(item.get("phase", "")).strip() or "unknown"
        duration_ms = round(_payload_float(item, "duration_ms"), 2)
        self.phase_totals[phase] = round(self.phase_totals.get(phase, 0.0) + duration_ms, 2)
        self.slowest_components.append(
            {
                "kind": "startup_phase" if event_name == "startup.phase" else "resume_phase",
                "project": str(item.get("project", "")).strip() or "",
                "name": phase,
                "duration_ms": duration_ms,
                "success": str(item.get("status", "ok")).strip().lower() not in {"error", "blocked", "degraded"},
            }
        )

    def _observe_artifact_timing(self, event_name: str, item: Mapping[str, object]) -> None:
        duration_ms = round(_payload_float(item, "duration_ms"), 2)
        self.slowest_components.append(
            {
                "kind": "artifacts",
                "project": "",
                "name": "write_total" if event_name == "artifacts.write" else "runtime_readiness_report",
                "duration_ms": duration_ms,
                "success": True,
            }
        )

    def _observe_service_phase(self, event_name: str, item: Mapping[str, object]) -> None:
        phase = str(item.get("phase", "")).strip() or "unknown"
        component = str(item.get("component", "")).strip() or "unknown"
        project = str(item.get("project", "")).strip() or "unknown"
        duration_ms = round(_payload_float(item, "duration_ms"), 2)
        key = f"{project}:{component}:{phase}"
        target_totals = (
            self.service_bootstrap_totals
            if event_name == "service.bootstrap.phase"
            else self.service_attach_totals
        )
        target_totals[key] = round(target_totals.get(key, 0.0) + duration_ms, 2)
        kind = "service_bootstrap_phase" if event_name == "service.bootstrap.phase" else "service_attach_phase"
        self.slowest_components.append(
            {
                "kind": kind,
                "project": project,
                "name": f"{component}:{phase}",
                "duration_ms": duration_ms,
                "success": str(item.get("status", "ok")).strip().lower() not in {"error", "blocked", "degraded"},
            }
        )

    def _observe_service_summary(self, item: Mapping[str, object]) -> None:
        project = str(item.get("project", "")).strip() or "unknown"
        duration_ms = _payload_float(item, "duration_ms")
        self.service_total_ms += duration_ms
        entry = self._project_entry(project)
        entry["service_ms"] = round(_payload_float(entry, "service_ms") + duration_ms, 2)

    def _observe_resume_restore_project(self, item: Mapping[str, object]) -> None:
        project = str(item.get("project", "")).strip() or "unknown"
        duration_ms = _payload_float(item, "total_ms")
        self.resume_restore_total_ms += duration_ms
        entry = self._project_entry(project)
        entry["resume_restore_ms"] = round(_payload_float(entry, "resume_restore_ms") + duration_ms, 2)

    def _observe_requirements_component(self, item: Mapping[str, object]) -> None:
        self.slowest_components.append(
            {
                "kind": "requirement",
                "project": str(item.get("project", "")).strip() or "unknown",
                "name": str(item.get("requirement", "")).strip() or "unknown",
                "duration_ms": round(_payload_float(item, "duration_ms"), 2),
                "success": bool(item.get("success", False)),
            }
        )

    def _observe_service_component(self, item: Mapping[str, object]) -> None:
        self.slowest_components.append(
            {
                "kind": "service",
                "project": str(item.get("project", "")).strip() or "unknown",
                "name": str(item.get("component", "")).strip() or "unknown",
                "duration_ms": round(_payload_float(item, "duration_ms"), 2),
                "success": True,
            }
        )

    def _observe_adapter_command_timing(self, item: Mapping[str, object]) -> None:
        self.has_command_timing_detail = True
        command_returncode = _payload_int(item, "returncode", 1)
        self.slowest_components.append(
            {
                "kind": "adapter_command",
                "project": str(item.get("project", "")).strip() or "unknown",
                "name": str(item.get("stage", "")).strip() or "command",
                "duration_ms": round(_payload_float(item, "duration_ms"), 2),
                "success": command_returncode == 0,
            }
        )

    def _observe_adapter_stage_map(self, item: Mapping[str, object]) -> None:
        stage_map = item.get("stage_durations_ms")
        if not isinstance(stage_map, Mapping):
            return
        for stage_name, raw_duration in stage_map.items():
            stage_key = str(stage_name).strip().lower()
            if not stage_key:
                continue
            duration = _optional_float(raw_duration)
            if duration is None:
                continue
            self.requirements_stage_totals[stage_key] = round(
                self.requirements_stage_totals.get(stage_key, 0.0) + duration,
                2,
            )

    def _project_entry(self, project: str) -> dict[str, object]:
        return self.project_breakdown.setdefault(
            project,
            {
                "project": project,
                "requirements_ms": 0.0,
                "service_ms": 0.0,
                "resume_restore_ms": 0.0,
                "total_ms": 0.0,
            },
        )

    def _complete_project_totals(self) -> None:
        for entry in self.project_breakdown.values():
            requirements_ms = _payload_float(entry, "requirements_ms")
            service_ms = _payload_float(entry, "service_ms")
            resume_ms = _payload_float(entry, "resume_restore_ms")
            entry["total_ms"] = round(requirements_ms + service_ms + resume_ms, 2)

    def _fill_slowest_from_project_summaries(self) -> None:
        for entry in self.project_breakdown.values():
            project = str(entry.get("project", "")).strip() or "unknown"
            requirements_ms = round(_payload_float(entry, "requirements_ms"), 2)
            service_ms = round(_payload_float(entry, "service_ms"), 2)
            resume_ms = round(_payload_float(entry, "resume_restore_ms"), 2)
            if requirements_ms > 0:
                self.slowest_components.append(
                    {
                        "kind": "requirements_summary",
                        "project": project,
                        "name": "requirements_total",
                        "duration_ms": requirements_ms,
                        "success": True,
                    }
                )
            if service_ms > 0:
                self.slowest_components.append(
                    {
                        "kind": "service_summary",
                        "project": project,
                        "name": "service_total",
                        "duration_ms": service_ms,
                        "success": True,
                    }
                )
            if resume_ms > 0:
                self.slowest_components.append(
                    {
                        "kind": "resume_summary",
                        "project": project,
                        "name": "resume_restore_total",
                        "duration_ms": resume_ms,
                        "success": True,
                    }
                )


def _hotspots(label: str, totals: Mapping[str, float]) -> list[dict[str, object]]:
    return [
        {label: key, "total_ms": round(total, 2)}
        for key, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


_STARTUP_EVENTS = {
    "startup.execution",
    "startup.phase",
    "resume.phase",
    "state.auto_resume",
    "state.auto_resume.skipped",
    "state.run_reuse.evaluate",
    "state.run_reuse.applied",
    "state.run_reuse.skipped",
    "state.dashboard_resume",
    "state.resume",
    "requirements.timing.component",
    "requirements.timing.summary",
    "service.timing.component",
    "service.timing.summary",
    "resume.restore.project_timing",
    "resume.restore.timing",
    "artifacts.write",
    "artifacts.runtime_readiness_report",
    "requirements.adapter",
    "requirements.adapter.stage",
    "requirements.adapter.command_timing",
    "service.bootstrap.phase",
    "service.attach.phase",
}
