from __future__ import annotations

from pathlib import Path

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_debug_support import (
    debug_doctor_snapshot_text as runtime_debug_doctor_snapshot_text,
    debug_last as runtime_debug_last,
    debug_pack as runtime_debug_pack,
    debug_report as runtime_debug_report,
    latest_debug_scope_session as runtime_latest_debug_scope_session,
    latest_scope_session_id as runtime_latest_scope_session_id,
    scope_latest_run_id as runtime_scope_latest_run_id,
)


class RuntimeDebugFacadeMixin:
    def _debug_pack(self, route: Route) -> int:
        return runtime_debug_pack(self, route)

    def _latest_debug_scope_session(self) -> tuple[str, Path, str] | None:
        return runtime_latest_debug_scope_session(self)

    @staticmethod
    def _latest_scope_session_id(scope_dir: Path) -> str | None:
        return runtime_latest_scope_session_id(scope_dir)

    @staticmethod
    def _scope_latest_run_id(scope_dir: Path) -> str | None:
        return runtime_scope_latest_run_id(scope_dir)

    def _debug_doctor_snapshot_text(self) -> str:
        return runtime_debug_doctor_snapshot_text(self)

    def _debug_last(self, route: Route) -> int:
        return runtime_debug_last(self, route)

    def _debug_report(self, route: Route) -> int:
        return runtime_debug_report(self, route)
