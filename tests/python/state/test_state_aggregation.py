from __future__ import annotations

from pathlib import Path

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state.run_index import RunIndexCandidate
from envctl_engine.state.state_aggregation import (
    IndexedState,
    select_indexed_owners,
    state_from_indexed_owners,
)


def _candidate(
    run_id: str,
    *projects: str,
    sequence: int,
    activation_sequence: int,
) -> RunIndexCandidate:
    return RunIndexCandidate(
        state_path=Path("/runtime") / run_id / "run_state.json",
        run_id=run_id,
        mode="trees",
        project_names=tuple(project.casefold() for project in projects),
        sequence=sequence,
        activation_sequence=activation_sequence,
    )


def _service_project_name(_name: str, service: ServiceRecord) -> str:
    return str(service.project or "")


def _project_names(state: RunState) -> list[str]:
    raw = state.metadata.get("project_names")
    return [str(name) for name in raw] if isinstance(raw, list) else []


def _source_run_ids(state: RunState) -> list[str]:
    raw = state.metadata.get("state_source_run_ids")
    return [str(run_id) for run_id in raw] if isinstance(raw, list) else []


def test_owner_selection_is_total_for_an_empty_inventory() -> None:
    assert (
        select_indexed_owners(
            [],
            selected_projects=(),
            service_project_name=_service_project_name,
        )
        == []
    )


def test_owner_selection_filters_shadowed_run_to_projects_it_still_owns() -> None:
    newest = IndexedState(
        candidate=_candidate("new", "alpha", sequence=2, activation_sequence=3),
        state=RunState(
            run_id="new",
            mode="trees",
            services={
                "alpha backend": ServiceRecord(
                    name="alpha backend",
                    type="backend",
                    cwd="/alpha",
                    project="alpha",
                )
            },
            metadata={"project_names": ["alpha"]},
        ),
    )
    previous = IndexedState(
        candidate=_candidate("old", "alpha", "beta", sequence=1, activation_sequence=1),
        state=RunState(
            run_id="old",
            mode="trees",
            services={
                project: ServiceRecord(
                    name=project,
                    type="backend",
                    cwd=f"/{project}",
                    project=project,
                )
                for project in ("alpha", "beta")
            },
            metadata={"project_names": ["alpha", "beta"]},
        ),
    )

    selected = select_indexed_owners(
        [newest, previous],
        selected_projects=(),
        service_project_name=_service_project_name,
    )

    assert [indexed.candidate.run_id for indexed in selected] == ["new", "old"]
    assert set(selected[0].state.services) == {"alpha backend"}
    assert set(selected[1].state.services) == {"beta"}
    assert selected[1].state.metadata["project_names"] == ["beta"]


def test_merged_state_uses_activation_owner_for_global_identity() -> None:
    activated = IndexedState(
        candidate=_candidate("activated", "alpha", sequence=1, activation_sequence=5),
        state=RunState(
            run_id="activated",
            mode="trees",
            metadata={
                "project_names": ["alpha"],
                "project_roots": {"alpha": "/alpha"},
                "global_marker": "activated",
                "state_source_run_ids": ["ancestor"],
            },
        ),
    )
    later_sequence = IndexedState(
        candidate=_candidate("stable", "beta", sequence=2, activation_sequence=2),
        state=RunState(
            run_id="stable",
            mode="trees",
            metadata={
                "project_names": ["beta"],
                "project_roots": {"beta": "/beta"},
                "global_marker": "stable",
            },
        ),
    )

    merged = state_from_indexed_owners(
        [activated, later_sequence],
        project_names_from_state=_project_names,
        source_run_ids=_source_run_ids,
    )

    assert merged is not None
    assert merged.run_id == "activated"
    assert merged.metadata["global_marker"] == "activated"
    assert merged.metadata["project_names"] == ["alpha", "beta"]
    assert merged.metadata["state_source_run_ids"] == ["activated", "ancestor", "stable"]
