from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from envctl_engine.requirements.common_contracts import ContainerStartResult
from envctl_engine.shared.protocols import CommandResult, ProcessRuntime
from envctl_engine.startup.protocols import ProjectContextLike


class CommandTimingRunnerProxy:
    """Proxy process runner that records command timing and return codes."""

    def __init__(self, base_runner: ProcessRuntime, *, sink: list[dict[str, object]]) -> None:
        self._base_runner = base_runner
        self._sink = sink

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        command = [str(part) for part in cmd]
        started = time.monotonic()
        result = self._base_runner.run(cmd, cwd=cwd, env=env, timeout=timeout)
        duration_ms = round((time.monotonic() - started) * 1000.0, 2)
        stderr = str(result.stderr or "")
        stdout = str(result.stdout or "")
        returncode = int(result.returncode)
        timed_out = bool(returncode == 124 or "timed out" in stderr.lower() or "timed out" in stdout.lower())
        self._sink.append(
            {
                "command": command,
                "duration_ms": duration_ms,
                "timeout_s": timeout,
                "returncode": returncode,
                "timed_out": timed_out,
            }
        )
        return result

    def __getattr__(self, name: str) -> object:
        return getattr(self._base_runner, name)


@dataclass(frozen=True, slots=True)
class NativeAdapterTelemetrySummary:
    effective_port: int
    port_adopted: bool
    probe_attempts: list[dict[str, object]]
    listener_wait_ms: float


@dataclass(slots=True)
class NativeAdapterTelemetryEmitter:
    runtime: Any
    context: ProjectContextLike
    service_name: str
    port: int
    result: ContainerStartResult
    trace_enabled: bool
    command_timing_enabled: bool
    command_timings: list[dict[str, object]]

    def emit(self) -> NativeAdapterTelemetrySummary:
        stage_events = self._stage_events()
        stage_durations_ms = self.result.stage_durations_ms if isinstance(self.result.stage_durations_ms, dict) else {}
        listener_wait_ms = float(self.result.listener_wait_ms or 0.0)
        probe_attempts = self._probe_attempts()
        effective_port = self._effective_port()
        port_adopted = bool(self.result.port_adopted)
        mismatch_requested_port = self._mismatch_requested_port()
        mismatch_existing_port = self._mismatch_existing_port()
        mismatch_action = str(self.result.port_mismatch_action or "").strip().lower() or None

        if self.trace_enabled:
            self._emit_trace_events(
                stage_events=stage_events,
                listener_wait_ms=listener_wait_ms,
                probe_attempts=probe_attempts,
                mismatch_action=mismatch_action,
                mismatch_requested_port=mismatch_requested_port,
                mismatch_existing_port=mismatch_existing_port,
                effective_port=effective_port,
                port_adopted=port_adopted,
            )
        if self.command_timing_enabled:
            self._emit_command_timing_events()

        self.runtime._emit(
            "requirements.adapter",
            project=self.context.name,
            service=self.service_name,
            container=self.result.container_name,
            success=self.result.success,
            port=self.port,
            effective_port=effective_port,
            port_adopted=port_adopted,
            reason=self.result.reason_code,
            reason_code=self.result.reason_code,
            failure_class=self.result.failure_class,
            stage_durations_ms=stage_durations_ms,
            docker_command_count=len(self.command_timings),
            probe_attempt_count=len(probe_attempts),
            listener_wait_ms=round(listener_wait_ms, 2),
            container_reused=bool(self.result.container_reused),
            container_recreated=bool(self.result.container_recreated),
        )
        return NativeAdapterTelemetrySummary(
            effective_port=effective_port,
            port_adopted=port_adopted,
            probe_attempts=probe_attempts,
            listener_wait_ms=listener_wait_ms,
        )

    def _stage_events(self) -> list[dict[str, object]]:
        raw = self.result.stage_events if isinstance(self.result.stage_events, list) else []
        return [item for item in raw if isinstance(item, dict)]

    def _probe_attempts(self) -> list[dict[str, object]]:
        raw = self.result.probe_attempts if isinstance(self.result.probe_attempts, list) else []
        result_probe_attempts = [item for item in raw if isinstance(item, dict)]
        return result_probe_attempts or extract_probe_attempts(self.command_timings, service_name=self.service_name)

    def _effective_port(self) -> int:
        if isinstance(self.result.effective_port, int) and self.result.effective_port > 0:
            return int(self.result.effective_port)
        return int(self.port)

    def _mismatch_requested_port(self) -> int:
        if (
            isinstance(self.result.port_mismatch_requested_port, int)
            and self.result.port_mismatch_requested_port > 0
        ):
            return int(self.result.port_mismatch_requested_port)
        return int(self.port)

    def _mismatch_existing_port(self) -> int | None:
        if (
            isinstance(self.result.port_mismatch_existing_port, int)
            and self.result.port_mismatch_existing_port > 0
        ):
            return int(self.result.port_mismatch_existing_port)
        return None

    def _emit_trace_events(
        self,
        *,
        stage_events: list[dict[str, object]],
        listener_wait_ms: float,
        probe_attempts: list[dict[str, object]],
        mismatch_action: str | None,
        mismatch_requested_port: int,
        mismatch_existing_port: int | None,
        effective_port: int,
        port_adopted: bool,
    ) -> None:
        for index, stage_item in enumerate(stage_events, start=1):
            self.runtime._emit(
                "requirements.adapter.stage",
                project=self.context.name,
                service=self.service_name,
                port=self.port,
                order=index,
                stage=str(stage_item.get("stage", "")),
                reason=stage_item.get("reason"),
                detail=stage_item.get("detail"),
                elapsed_ms=stage_item.get("elapsed_ms"),
            )
        self.runtime._emit(
            "requirements.adapter.listener_wait",
            project=self.context.name,
            service=self.service_name,
            port=self.port,
            listener_wait_ms=round(listener_wait_ms, 2),
        )
        self.runtime._emit(
            "requirements.adapter.retry_path",
            project=self.context.name,
            service=self.service_name,
            port=self.port,
            restart_used=self._restart_used(stage_events),
            recreate_used=self._recreate_used(stage_events),
            stage_count=len(stage_events),
        )
        for attempt in probe_attempts:
            self.runtime._emit(
                "requirements.adapter.probe_attempt",
                project=self.context.name,
                service=self.service_name,
                port=self.port,
                attempt=_coerce_returncode(attempt.get("attempt", 0)),
                phase=attempt.get("phase"),
                action=attempt.get("action"),
                duration_ms=round(_coerce_float(attempt.get("duration_ms", 0.0)), 2),
                returncode=_coerce_returncode(attempt.get("returncode", 1)),
                timed_out=bool(attempt.get("timed_out", False)),
                error=attempt.get("error"),
            )
        if mismatch_action is not None:
            self.runtime._emit(
                "requirements.adapter.port_mismatch",
                project=self.context.name,
                service=self.service_name,
                requested_port=mismatch_requested_port,
                existing_port=mismatch_existing_port,
                action=mismatch_action,
                adopted=port_adopted,
                effective_port=effective_port,
            )

    def _emit_command_timing_events(self) -> None:
        for index, command_item in enumerate(self.command_timings, start=1):
            raw_command = command_item.get("command")
            command_tokens = [str(part) for part in raw_command] if isinstance(raw_command, list) else []
            self.runtime._emit(
                "requirements.adapter.command_timing",
                project=self.context.name,
                service=self.service_name,
                port=self.port,
                order=index,
                stage=classify_docker_stage(command_tokens),
                command=command_tokens,
                duration_ms=round(_coerce_float(command_item.get("duration_ms", 0.0)), 2),
                timeout_s=command_item.get("timeout_s"),
                returncode=_coerce_returncode(command_item.get("returncode", 1)),
                timed_out=bool(command_item.get("timed_out", False)),
            )

    @staticmethod
    def _restart_used(stage_events: list[dict[str, object]]) -> bool:
        return any(
            str(item.get("stage", "")).startswith(("probe.retry.restart", "supabase.auth.restart"))
            for item in stage_events
        )

    def _recreate_used(self, stage_events: list[dict[str, object]]) -> bool:
        return bool(self.result.container_recreated) or any(
            str(item.get("stage", "")).startswith(("probe.retry.recreate", "supabase.auth.recreate"))
            for item in stage_events
        )


def classify_docker_stage(command: list[str]) -> str:
    if len(command) < 2 or command[0] != "docker":
        return "other"
    sub = command[1].strip().lower()
    if sub in {"ps", "inspect", "port"}:
        return "discover"
    if sub == "run":
        return "create"
    if sub == "start":
        return "start"
    if sub == "restart":
        return "restart"
    if sub == "exec":
        return "probe"
    if sub in {"stop", "rm"}:
        return "recreate"
    return "other"


def extract_probe_attempts(command_timings: list[dict[str, object]], *, service_name: str) -> list[dict[str, object]]:
    attempts: list[dict[str, object]] = []
    for item in command_timings:
        command = item.get("command")
        if not isinstance(command, list):
            continue
        tokens = [str(part).strip().lower() for part in command]
        if len(tokens) < 3 or tokens[0] != "docker" or tokens[1] != "exec":
            continue
        is_probe = False
        if service_name == "postgres":
            is_probe = "pg_isready" in tokens
        elif service_name == "redis":
            is_probe = "redis-cli" in tokens and "ping" in tokens
        elif service_name == "n8n":
            is_probe = "curl" in tokens or "wget" in tokens
        if not is_probe:
            continue
        attempts.append(
            {
                "duration_ms": float(item.get("duration_ms", 0.0) or 0.0),
                "returncode": _coerce_returncode(item.get("returncode", 1)),
                "timed_out": bool(item.get("timed_out", False)),
                "command": command,
            }
        )
    for index, attempt in enumerate(attempts, start=1):
        attempt["attempt"] = index
    return attempts


def _coerce_returncode(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _coerce_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
