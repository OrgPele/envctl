from __future__ import annotations

from pathlib import Path

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.dashboard.snapshot_support import build_dashboard_snapshot_model


def test_snapshot_model_uses_project_roots_when_runtime_map_has_no_projection(tmp_path: Path) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []
    state = RunState(
        run_id="run-1",
        mode="trees",
        metadata={
            "project_roots": {"feature-a-1": str(tmp_path)},
            "dashboard_configured_service_types": ["backend"],
            "dashboard_runs_disabled": True,
        },
    )

    model = build_dashboard_snapshot_model(
        state,
        visual_host="localhost",
        reconcile_fn=lambda _state: ["missing-backend"],
        emit_fn=lambda event, **payload: emitted.append((event, payload)),
    )

    assert model.failing_services == ["missing-backend"]
    assert model.projection == {"feature-a-1": {}}
    assert model.ordered_projects == ["feature-a-1"]
    assert model.runs_disabled_dashboard is True
    assert model.configured_service_types == {"backend"}
    assert model.configured_service_total == 1
    assert model.total_services == 0
    assert model.running_services == 0
    assert model.issue_services == 0
    assert emitted == [
        (
            "state.reconcile",
            {
                "run_id": "run-1",
                "source": "dashboard.snapshot",
                "missing_count": 1,
                "missing_services": ["missing-backend"],
            },
        )
    ]


def test_snapshot_model_merges_stopped_and_configured_missing_projects() -> None:
    emitted: list[tuple[str, dict[str, object]]] = []
    state = RunState(
        run_id="run-1",
        mode="main",
        services={
            "Main Frontend": ServiceRecord(
                name="Main Frontend",
                type="frontend",
                status="running",
                cwd=Path("/repo/frontend"),
            )
        },
        metadata={
            "project_roots": {"Main": "/repo"},
            "dashboard_project_configured_services": {"Main": ["backend", "frontend"]},
            "dashboard_stopped_services": [
                {"project": "Other", "type": "worker", "name": "Other Worker"},
            ],
        },
    )

    model = build_dashboard_snapshot_model(
        state,
        visual_host="localhost",
        reconcile_fn=lambda _state: [],
        emit_fn=lambda event, **payload: emitted.append((event, payload)),
    )

    assert set(model.projection) == {"Main", "Other"}
    assert model.project_configured_services == {"Main": {"backend", "frontend"}}
    assert model.configured_missing_services == {"Main": {"backend"}}
    assert model.stopped_service_count == 2
    assert model.total_services == 3
    assert model.running_services == 1
    assert model.starting_services == 0
    assert emitted[-1] == (
        "dashboard.configured_missing_services",
        {
            "run_id": "run-1",
            "services": {"Main": ["backend"]},
            "metadata_key": "dashboard_project_configured_services",
        },
    )
