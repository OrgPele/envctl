from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.startup import lifecycle


def test_execute_startup_lifecycle_holds_repo_scope_lock(monkeypatch, tmp_path: Path) -> None:
    seen: list[object] = []

    @contextmanager
    def recording_lock(path: Path, *, timeout: float):
        seen.extend((path, timeout, "entered"))
        yield
        seen.append("exited")

    runtime = SimpleNamespace(
        runtime_root=tmp_path,
        env={},
        config=SimpleNamespace(raw={}),
    )
    orchestrator = SimpleNamespace(runtime=runtime)
    monkeypatch.setattr(lifecycle, "file_lock", recording_lock)
    monkeypatch.setattr(
        lifecycle,
        "_execute_startup_lifecycle_locked",
        lambda received_orchestrator, route, **_kwargs: seen.append((received_orchestrator, route)) or 7,
    )

    assert lifecycle.execute_startup_lifecycle(orchestrator, "route") == 7
    assert seen == [tmp_path / "locks" / "startup.lock", 3600.0, "entered", (orchestrator, "route"), "exited"]


def test_execute_startup_lifecycle_releases_lock_before_dashboard(monkeypatch, tmp_path: Path) -> None:
    seen: list[str] = []
    state = SimpleNamespace(run_id="run-1")

    @contextmanager
    def recording_lock(_path: Path, *, timeout: float):
        _ = timeout
        seen.append("lock-entered")
        yield
        seen.append("lock-exited")

    def execute_locked(_orchestrator, _route, *, run_interactive_dashboard_loop):  # noqa: ANN001
        seen.append("startup-finalized")
        return run_interactive_dashboard_loop(state)

    def dashboard(received_state: object) -> int:
        assert received_state is state
        seen.append("dashboard-entered")
        return 0

    runtime = SimpleNamespace(
        runtime_root=tmp_path,
        env={},
        config=SimpleNamespace(raw={}),
        _run_interactive_dashboard_loop=dashboard,
    )
    monkeypatch.setattr(lifecycle, "file_lock", recording_lock)
    monkeypatch.setattr(lifecycle, "_execute_startup_lifecycle_locked", execute_locked)

    assert lifecycle.execute_startup_lifecycle(SimpleNamespace(runtime=runtime), "route") == 0
    assert seen == ["lock-entered", "startup-finalized", "lock-exited", "dashboard-entered"]


def test_execute_startup_lifecycle_reports_lock_timeout(monkeypatch, tmp_path: Path, capsys) -> None:
    @contextmanager
    def timing_out_lock(path: Path, *, timeout: float):
        raise TimeoutError(f"Timed out acquiring lock: {path}")
        yield

    events: list[tuple[str, dict[str, object]]] = []
    runtime = SimpleNamespace(
        runtime_root=tmp_path,
        env={"ENVCTL_STARTUP_LOCK_TIMEOUT_SECONDS": "2.5"},
        config=SimpleNamespace(raw={}),
        _emit=lambda event, **payload: events.append((event, payload)),
    )
    monkeypatch.setattr(lifecycle, "file_lock", timing_out_lock)

    assert lifecycle.execute_startup_lifecycle(SimpleNamespace(runtime=runtime), "route") == 1
    assert "repository lifecycle lock" in capsys.readouterr().out
    assert events == [
        (
            "startup.lock.timeout",
            {"lock_path": str(tmp_path / "locks" / "startup.lock"), "timeout_seconds": 2.5},
        )
    ]
