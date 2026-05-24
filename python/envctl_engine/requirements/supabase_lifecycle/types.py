from __future__ import annotations

import time
from collections.abc import Mapping

from .config import _supabase_startup_budget_seconds

class _SupabaseStartupBudget:
    def __init__(self, timeout_seconds: float, started_at: float, clock: object):
        self.timeout_seconds = timeout_seconds
        self.started_at = started_at
        self.clock = clock

    @classmethod
    def start(cls, env: Mapping[str, str] | None, *, clock=time.monotonic) -> '_SupabaseStartupBudget':
        return cls(timeout_seconds=_supabase_startup_budget_seconds(env), started_at=float(clock()), clock=clock)

    def elapsed_seconds(self) -> float:
        return max(0.0, float(self.clock()) - self.started_at)

    def elapsed_ms(self) -> float:
        return round(self.elapsed_seconds() * 1000.0, 2)

    def remaining_seconds(self) -> float:
        return max(0.0, self.timeout_seconds - self.elapsed_seconds())

class SupabaseAuthHealthProbeResult:
    def __init__(
        self,
        ready: bool,
        phase: str,
        health_url: str,
        attempts: list[dict[str, object]],
        last_error: str | None = None,
        listener_ready: bool = False,
    ):
        self.ready = ready
        self.phase = phase
        self.health_url = health_url
        self.attempts = attempts
        self.last_error = last_error
        self.listener_ready = listener_ready
