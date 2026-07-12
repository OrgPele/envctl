from __future__ import annotations

from pathlib import Path

import pytest

from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.run_index import RunIndexCandidate
from envctl_engine.state.state_aggregation import (
    IndexedState,
    filter_state_to_owned_projects,
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


def test_shadowed_multi_project_owner_does_not_relabel_opaque_services_as_remaining_project() -> None:
    newest = IndexedState(
        candidate=_candidate("new", "alpha", sequence=2, activation_sequence=3),
        state=RunState(
            run_id="new",
            mode="trees",
            services={
                "New Alpha": ServiceRecord(
                    name="New Alpha",
                    type="worker",
                    cwd="/new-alpha",
                    pid=3,
                    project="Alpha",
                )
            },
            metadata={"project_names": ["Alpha"]},
        ),
    )
    previous = IndexedState(
        candidate=_candidate("old", "alpha", "beta", sequence=1, activation_sequence=1),
        state=RunState(
            run_id="old",
            mode="trees",
            services={
                "Opaque Old Alpha": ServiceRecord(
                    name="Opaque Old Alpha",
                    type="worker",
                    cwd="/old-alpha",
                    pid=1,
                ),
                "Opaque Beta": ServiceRecord(
                    name="Opaque Beta",
                    type="worker",
                    cwd="/beta",
                    pid=2,
                ),
            },
            metadata={
                "project_names": ["Alpha", "Beta"],
                "project_roots": {"Alpha": "/old-alpha", "Beta": "/beta"},
            },
        ),
    )

    selected = select_indexed_owners(
        [newest, previous],
        selected_projects=(),
        service_project_name=_service_project_name,
    )

    old = next(item.state for item in selected if item.candidate.run_id == "old")
    assert {service.pid for service in old.services.values()} == {2}
    assert {service.project for service in old.services.values()} == {"Beta"}


def test_multi_project_opaque_service_without_root_evidence_fails_closed() -> None:
    ambiguous = IndexedState(
        candidate=_candidate("ambiguous", "alpha", "beta", sequence=1, activation_sequence=1),
        state=RunState(
            run_id="ambiguous",
            mode="trees",
            services={
                "Opaque Shared Runtime": ServiceRecord(
                    name="Opaque Shared Runtime",
                    type="worker",
                    cwd="/unknown",
                    pid=101,
                )
            },
            metadata={"project_names": ["Alpha", "Beta"]},
        ),
    )

    with pytest.raises(RuntimeError, match="Cannot safely determine project ownership"):
        select_indexed_owners(
            [ambiguous],
            selected_projects=(),
            service_project_name=_service_project_name,
        )


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


def test_owned_project_filter_keeps_every_authoritative_requirement_storage_row() -> None:
    state = RunState(
        run_id="collision",
        mode="trees",
        requirements={
            "Main": RequirementsResult(project="Main", redis={"enabled": True, "final": 6380}),
            "Main Restart Collision": RequirementsResult(
                project="Main",
                redis={"enabled": True, "final": 6381},
            ),
            "Other": RequirementsResult(project="Other", redis={"enabled": True, "final": 6390}),
        },
    )

    filtered = filter_state_to_owned_projects(
        state,
        frozenset({"main"}),
        service_project_name=_service_project_name,
    )

    assert set(filtered.requirements) == {"Main", "Main Restart Collision"}


def test_indexed_merge_disambiguates_opaque_legacy_names_using_single_owner_context() -> None:
    alpha = IndexedState(
        candidate=_candidate("alpha-run", "Alpha", sequence=1, activation_sequence=1),
        state=RunState(
            run_id="alpha-run",
            mode="trees",
            services={
                "Opaque Shared Runtime": ServiceRecord(
                    name="Opaque Shared Runtime",
                    type="worker",
                    cwd="/alpha",
                    pid=101,
                )
            },
            metadata={"project_names": ["Alpha"]},
        ),
    )
    beta = IndexedState(
        candidate=_candidate("beta-run", "Beta", sequence=2, activation_sequence=2),
        state=RunState(
            run_id="beta-run",
            mode="trees",
            services={
                "Opaque Shared Runtime": ServiceRecord(
                    name="Opaque Shared Runtime",
                    type="worker",
                    cwd="/beta",
                    pid=202,
                )
            },
            metadata={"project_names": ["Beta"]},
        ),
    )

    merged = state_from_indexed_owners(
        [alpha, beta],
        project_names_from_state=_project_names,
        source_run_ids=_source_run_ids,
    )

    assert merged is not None
    assert {service.pid for service in merged.services.values()} == {101, 202}
    assert {service.project for service in merged.services.values()} == {"Alpha", "Beta"}
    assert len(merged.services) == 2

    selected = select_indexed_owners(
        [alpha, beta],
        selected_projects=(),
        service_project_name=_service_project_name,
    )
    operational = state_from_indexed_owners(
        selected,
        project_names_from_state=_project_names,
        source_run_ids=_source_run_ids,
    )

    assert operational is not None
    assert {service.pid for service in operational.services.values()} == {101, 202}
    assert {service.project for service in operational.services.values()} == {"Alpha", "Beta"}
