from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_cleanup_orchestrator import LifecycleCleanupOrchestrator
from envctl_engine.runtime.lifecycle_service_termination import (
    terminate_service_record,
    terminate_services_from_state,
)
from envctl_engine.shared.ports import PortPlanner
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.repository import RuntimeStateRepository
from envctl_engine.state.run_index import StateSelector
from envctl_engine.ui.spinner_service import SpinnerPolicy
from envctl_engine.ui.target_selector import TargetSelection


class _StateRepoStub:
    def __init__(self) -> None:
        self.saved_states: list[RunState] = []
        self.saved_authoritative_project_names: list[list[str] | None] = []
        self.purge_calls: list[bool] = []
        self.active_states: list[RunState] = []
        self.deactivated_run_ids: list[str] = []

    def save_selected_stop_state(  # noqa: ANN001
        self,
        *,
        state,
        emit,
        runtime_map_builder,
        authoritative_project_names=None,
    ):
        _ = emit, runtime_map_builder
        self.saved_states.append(state)
        self.saved_authoritative_project_names.append(authoritative_project_names)
        self.active_states = [
            state if active_state.run_id == state.run_id else active_state for active_state in self.active_states
        ]
        return {}

    def purge(self, *, aggressive: bool = False) -> None:
        self.purge_calls.append(aggressive)

    def load_all(self, *, mode: str | None = None) -> list[RunState]:
        return [state for state in self.active_states if mode is None or state.mode == mode]

    def deactivate_runs(self, run_ids: list[str]) -> bool:
        selected = set(run_ids)
        removed = [state for state in self.active_states if state.run_id in selected]
        self.active_states = [state for state in self.active_states if state.run_id not in selected]
        self.deactivated_run_ids.extend(state.run_id for state in removed)
        return bool(removed)

    def has_active_runs(self) -> bool:
        return bool(self.active_states)


class _RuntimeStub:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(raw={}, base_dir=Path("/tmp"))
        self.events: list[dict[str, object]] = []
        self.state_repository = _StateRepoStub()
        self.selection_calls: list[dict[str, object]] = []
        self.port_planner: object | None = None

    def _emit(self, event: str, **payload: object) -> None:
        entry: dict[str, object] = {"event": event}
        entry.update(payload)
        self.events.append(entry)

    def _try_load_existing_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return None

    @staticmethod
    def _state_lookup_strict_mode_match(_route):  # noqa: ANN001
        return False

    def _terminate_services_from_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return set()

    def _release_port_session(self) -> None:
        return None

    @staticmethod
    def _project_name_from_service(name: str) -> str:
        return name.split(" ", 1)[0] if " " in name else ""

    def _select_grouped_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        services: list[str],
        allow_all: bool,
        multi: bool,
    ) -> TargetSelection:
        self.selection_calls.append(
            {
                "prompt": prompt,
                "projects": [str(getattr(project, "name", "")) for project in projects],
                "services": list(services),
                "allow_all": allow_all,
                "multi": multi,
            }
        )
        return TargetSelection(project_names=["Main"])


class _RuntimeWithoutPortSessionHook:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(raw={}, base_dir=Path("/tmp"))
        self.events: list[dict[str, object]] = []
        self.state_repository = _StateRepoStub()

    def _emit(self, event: str, **payload: object) -> None:
        entry: dict[str, object] = {"event": event}
        entry.update(payload)
        self.events.append(entry)

    def _try_load_existing_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return None

    @staticmethod
    def _state_lookup_strict_mode_match(_route):  # noqa: ANN001
        return False

    def _terminate_services_from_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        raise AssertionError("stop-all with no runtime state should not terminate services")


class LifecycleCleanupSpinnerIntegrationTests(unittest.TestCase):
    def test_full_cleanup_retains_dependency_state_after_container_cleanup_failure(self) -> None:
        for command, aggressive in (("stop-all", False), ("blast-all", True)):
            with self.subTest(command=command):
                runtime = _RuntimeStub()
                state = RunState(
                    run_id="run-1",
                    mode="main",
                    requirements={
                        "Main": RequirementsResult(
                            project="Main",
                            redis={
                                "id": "redis",
                                "enabled": True,
                                "container_name": "envctl-redis-main",
                            },
                        )
                    },
                )
                runtime.state_repository.active_states = [state]
                released_requirements: list[str] = []
                runtime._release_requirement_ports = (  # type: ignore[attr-defined]
                    lambda requirements: released_requirements.append(requirements.project)
                )
                orchestrator = LifecycleCleanupOrchestrator(runtime)
                orchestrator.blast_all_ecosystem_enabled = lambda: False  # type: ignore[method-assign]
                orchestrator.blast_all_purge_legacy_state_artifacts = lambda: None  # type: ignore[method-assign]
                output = StringIO()

                with (
                    patch(
                        "envctl_engine.runtime.lifecycle_cleanup_orchestrator.stop_requirement_component_containers",
                        side_effect=RuntimeError("Docker daemon is unavailable"),
                    ),
                    redirect_stdout(output),
                ):
                    code = orchestrator.execute(Route(command=command, mode="main"))

                self.assertEqual(code, 1)
                self.assertEqual(runtime.state_repository.purge_calls, [])
                self.assertEqual(runtime.state_repository.deactivated_run_ids, [])
                self.assertEqual(runtime.state_repository.active_states, [state])
                self.assertEqual(runtime.state_repository.saved_states, [state])
                self.assertEqual(set(state.requirements), {"Main"})
                self.assertEqual(released_requirements, [])
                self.assertIn("could not stop redis container", output.getvalue())
                warnings = [
                    event
                    for event in runtime.events
                    if event.get("event") == "cleanup.dependency_container.warning"
                ]
                self.assertEqual(
                    warnings,
                    [
                        {
                            "event": "cleanup.dependency_container.warning",
                            "component": "redis",
                            "detail": "Docker daemon is unavailable",
                        }
                    ],
                )
                incomplete = [event for event in runtime.events if event.get("event") == "cleanup.incomplete"]
                self.assertEqual(incomplete[-1].get("failed_services"), {})
                self.assertEqual(incomplete[-1].get("failed_requirements"), {"run-1": ["Main"]})

                retry_code = orchestrator.execute(Route(command=command, mode="main"))

                self.assertEqual(retry_code, 0)
                self.assertEqual(runtime.state_repository.deactivated_run_ids, ["run-1"])
                self.assertEqual(runtime.state_repository.active_states, [])
                self.assertEqual(released_requirements, ["Main"])
                self.assertEqual(runtime.state_repository.purge_calls, [aggressive])

    def test_targeted_runtime_cleanup_remains_fail_closed(self) -> None:
        runtime = _RuntimeStub()
        runtime._try_load_existing_state = lambda *args, **kwargs: RunState(  # type: ignore[method-assign]
            run_id="run-1",
            mode="main",
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    redis={
                        "id": "redis",
                        "enabled": True,
                        "container_name": "envctl-redis-main",
                    },
                )
            },
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)

        with (
            patch(
                "envctl_engine.runtime.lifecycle_cleanup_orchestrator.stop_requirement_component_containers",
                side_effect=RuntimeError("Docker daemon is unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "Docker daemon is unavailable"),
        ):
            orchestrator.clear_runtime_state(command="stop", aggressive=False)

        self.assertEqual(runtime.state_repository.purge_calls, [])

    def test_full_cleanup_retains_state_when_requirement_port_release_fails(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-port-release",
            mode="main",
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    redis={"id": "redis", "enabled": True, "external": True, "final": 6379},
                )
            },
        )
        runtime.state_repository.active_states = [state]
        release_attempts = 0

        def release_ports(_requirements: RequirementsResult) -> None:
            nonlocal release_attempts
            release_attempts += 1
            if release_attempts == 1:
                raise OSError("lock unlink failed")

        runtime._release_requirement_ports = release_ports  # type: ignore[attr-defined]
        orchestrator = LifecycleCleanupOrchestrator(runtime)

        first_code = orchestrator.execute(Route(command="stop-all", mode="main"))

        self.assertEqual(first_code, 1)
        self.assertEqual(runtime.state_repository.active_states, [state])
        self.assertEqual(runtime.state_repository.deactivated_run_ids, [])
        self.assertEqual(runtime.state_repository.purge_calls, [])
        self.assertEqual(set(state.requirements), {"Main"})
        warning = next(event for event in runtime.events if event.get("event") == "cleanup.requirement_ports.warning")
        self.assertEqual(warning.get("detail"), "lock unlink failed")

        retry_code = orchestrator.execute(Route(command="stop-all", mode="main"))

        self.assertEqual(retry_code, 0)
        self.assertEqual(release_attempts, 2)
        self.assertEqual(runtime.state_repository.active_states, [])
        self.assertEqual(runtime.state_repository.deactivated_run_ids, ["run-port-release"])
        self.assertEqual(runtime.state_repository.purge_calls, [False])

    def test_stop_all_emits_spinner_policy_and_lifecycle(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop-all", mode="main")
        spinner_calls: list[tuple[str, bool]] = []

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append((message, enabled))

            class _SpinnerStub:
                def start(self) -> None:
                    return None

                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            yield _SpinnerStub()

        with (
            patch("envctl_engine.runtime.lifecycle_cleanup_orchestrator.spinner", side_effect=fake_spinner),
            patch(
                "envctl_engine.runtime.lifecycle_cleanup_orchestrator.resolve_spinner_policy",
                return_value=SpinnerPolicy(
                    mode="auto",
                    enabled=True,
                    reason="",
                    backend="rich",
                    min_ms=0,
                    verbose_events=False,
                ),
            ),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(spinner_calls, [("Stopping all services and runtime state...", True)])
        self.assertTrue(any(item.get("event") == "ui.spinner.policy" for item in runtime.events))
        lifecycle = [item for item in runtime.events if item.get("event") == "ui.spinner.lifecycle"]
        self.assertTrue(any(item.get("state") == "success" for item in lifecycle))

    def test_stop_all_tolerates_runtime_without_port_session_hook(self) -> None:
        runtime = _RuntimeWithoutPortSessionHook()
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop-all", mode="main")

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(runtime.state_repository.purge_calls, [False])
        self.assertTrue(any(item.get("event") == "cleanup.stop_all" for item in runtime.events))

    def test_stop_all_releases_every_scoped_port_lock_after_last_run_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _RuntimeStub()
            scoped_planner = PortPlanner(
                lock_dir=str(Path(tmpdir) / "scope-a"),
                availability_checker=lambda _port: True,
            )
            foreign_planner = PortPlanner(
                lock_dir=str(Path(tmpdir) / "scope-b"),
                availability_checker=lambda _port: True,
            )
            scoped_planner.reserve_next(8100, owner="old-startup")
            foreign_planner.reserve_next(8200, owner="other-repository")
            runtime.port_planner = scoped_planner

            code = LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="main"))

            self.assertEqual(code, 0)
            self.assertEqual(list(scoped_planner.lock_dir.glob("*.lock")), [])
            self.assertEqual(
                [path.name for path in foreign_planner.lock_dir.glob("*.lock")],
                ["8200.lock"],
            )
            self.assertEqual(runtime.state_repository.purge_calls, [False])

    def test_stop_all_purge_failure_preserves_scoped_port_locks(self) -> None:
        runtime = _RuntimeStub()
        releases: list[str] = []
        runtime.port_planner = SimpleNamespace(release_all=lambda: releases.append("all"))

        with (
            patch.object(runtime.state_repository, "purge", side_effect=OSError("registry unavailable")),
            self.assertRaisesRegex(OSError, "registry unavailable"),
        ):
            LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="main"))

        self.assertEqual(releases, [])

    def test_stop_all_terminates_every_independent_active_run_once(self) -> None:
        runtime = _RuntimeStub()
        runtime.state_repository.active_states = [
            RunState(run_id="run-a", mode="trees"),
            RunState(run_id="run-b", mode="trees"),
            RunState(run_id="run-a", mode="trees"),
        ]
        terminated: list[str] = []
        runtime._terminate_services_from_state = (  # type: ignore[method-assign]
            lambda state, **_kwargs: terminated.append(state.run_id) or set()
        )

        code = LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="trees"))

        self.assertEqual(code, 0)
        self.assertEqual(terminated, ["run-a", "run-b"])
        self.assertEqual(runtime.state_repository.purge_calls, [False])

    def test_plain_stop_all_terminates_active_runs_across_modes(self) -> None:
        runtime = _RuntimeStub()
        runtime.state_repository.active_states = [
            RunState(run_id="run-main", mode="main"),
            RunState(run_id="run-tree", mode="trees"),
        ]
        terminated: list[str] = []
        runtime._terminate_services_from_state = (  # type: ignore[method-assign]
            lambda state, **_kwargs: terminated.append(state.run_id) or set()
        )

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(command="stop-all", mode="main")
        )

        self.assertEqual(code, 0)
        self.assertEqual(terminated, ["run-main", "run-tree"])
        self.assertEqual(runtime.state_repository.active_states, [])

    def test_stop_all_trees_preserves_main_registry_alias_and_port_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repository = RuntimeStateRepository(
                runtime_root=runtime_dir / "scope",
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            for run_id, mode, project in (
                ("run-main", "main", "Main"),
                ("run-alpha", "trees", "FeatureA"),
                ("run-beta", "trees", "FeatureB"),
            ):
                repository.save_resume_state(
                    state=RunState(
                        run_id=run_id,
                        mode=mode,
                        services={
                            f"{project} Backend": ServiceRecord(
                                name=f"{project} Backend",
                                type="backend",
                                cwd=str(root / project / "backend"),
                                project=project,
                                pid=100 + len(project),
                            )
                        },
                        metadata={
                            "project_names": [project],
                            "project_roots": {project: str(root / project)},
                        },
                    ),
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda state: {"run_id": state.run_id},
                )

            planner = PortPlanner(
                lock_dir=str(repository.runtime_root / "locks"),
                session_id="main-owner",
                availability_checker=lambda _port: True,
            )
            main_port = planner.reserve_next(8111, owner="Main:backend")
            runtime = _RuntimeStub()
            runtime.state_repository = repository  # type: ignore[assignment]
            runtime._state_lookup_strict_mode_match = lambda _route: True  # type: ignore[method-assign]
            runtime.port_planner = planner
            terminated: list[str] = []
            runtime._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, **_kwargs: terminated.append(state.run_id) or set()
            )

            with patch.object(repository, "purge", wraps=repository.purge) as purge:
                code = LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="trees"))

            self.assertEqual(code, 0)
            self.assertEqual(terminated, ["run-beta", "run-alpha"])
            purge.assert_not_called()
            remaining = repository.load_all()
            self.assertEqual([state.run_id for state in remaining], ["run-main"])
            self.assertEqual(repository.load_latest(mode="main", strict_mode_match=True).run_id, "run-main")
            current = json.loads(repository.run_state_path().read_text(encoding="utf-8"))
            self.assertEqual((current["run_id"], current["mode"]), ("run-main", "main"))
            self.assertTrue((planner.lock_dir / f"{main_port}.lock").exists())

    def test_mode_scoped_stop_all_ignores_tampered_other_mode_and_preserves_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            repository = RuntimeStateRepository(
                runtime_root=runtime_dir / "scope",
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            for run_id, mode, project, pid in (
                ("run-valid", "main", "Main", 101),
                ("run-tampered", "trees", "FeatureA", 202),
            ):
                service_name = f"{project} Backend"
                repository.save_resume_state(
                    state=RunState(
                        run_id=run_id,
                        mode=mode,
                        services={
                            service_name: ServiceRecord(
                                name=service_name,
                                type="backend",
                                cwd=f"/tmp/{project}/backend",
                                project=project,
                                pid=pid,
                            )
                        },
                        metadata={"project_names": [project]},
                    ),
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda state: {"run_id": state.run_id},
                )

            candidates = repository.run_index.candidates(StateSelector(mode=None, project_names=()))
            tampered = next(candidate for candidate in candidates if candidate.run_id == "run-tampered")
            tampered.state_path.write_text('{"broken":', encoding="utf-8")

            runtime = _RuntimeStub()
            runtime.state_repository = repository  # type: ignore[assignment]
            runtime._state_lookup_strict_mode_match = lambda _route: True  # type: ignore[method-assign]
            termination_calls: list[str] = []
            runtime._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, **_kwargs: termination_calls.append(state.run_id) or set()
            )

            with patch.object(repository, "purge", wraps=repository.purge) as purge:
                code = LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="main"))

            self.assertEqual(code, 0)
            self.assertEqual(termination_calls, ["run-valid"])
            purge.assert_not_called()
            remaining = repository.run_index.candidates(StateSelector(mode=None, project_names=()))
            self.assertEqual({candidate.run_id for candidate in remaining}, {"run-tampered"})
            self.assertTrue(all(candidate.state_path.exists() for candidate in remaining))

    def test_targeted_stop_deactivates_no_infra_state_with_only_disabled_requirements(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-no-infra",
            mode="trees",
            services={},
            requirements={"FeatureA": RequirementsResult(project="FeatureA")},
            metadata={
                "project_names": ["FeatureA"],
                "project_roots": {"FeatureA": "/tmp/FeatureA"},
            },
        )
        runtime.state_repository.active_states = [state]

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(
                command="stop",
                mode="trees",
                projects=["FeatureA"],
                flags={"batch": True, "runtime_scope": "entire-system"},
            )
        )

        self.assertEqual(code, 0)
        self.assertEqual(runtime.state_repository.deactivated_run_ids, ["run-no-infra"])
        self.assertEqual(runtime.state_repository.active_states, [])

    def test_targeted_stop_removes_only_selected_project_from_shared_no_infra_state(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-no-infra-ab",
            mode="trees",
            services={},
            requirements={project: RequirementsResult(project=project) for project in ("FeatureA", "FeatureB")},
            metadata={
                "project_names": ["FeatureA", "FeatureB"],
                "project_roots": {
                    "FeatureA": "/tmp/FeatureA",
                    "FeatureB": "/tmp/FeatureB",
                },
            },
        )
        runtime.state_repository.active_states = [state]

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(
                command="stop",
                mode="trees",
                projects=["FeatureA"],
                flags={"batch": True, "runtime_scope": "entire-system"},
            )
        )

        self.assertEqual(code, 0)
        self.assertEqual(runtime.state_repository.deactivated_run_ids, [])
        self.assertEqual(len(runtime.state_repository.saved_states), 1)
        saved = runtime.state_repository.saved_states[0]
        self.assertEqual(set(saved.requirements), {"FeatureB"})
        self.assertEqual(saved.metadata["project_names"], ["FeatureB"])
        self.assertEqual(saved.metadata["project_roots"], {"FeatureB": "/tmp/FeatureB"})
        self.assertEqual(runtime.state_repository.saved_authoritative_project_names, [["FeatureB"]])
        self.assertEqual(runtime.state_repository.active_states, [saved])

    def test_targeted_service_stop_preserves_unselected_owner_and_shared_main_requirements(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-services-ab",
            mode="trees",
            services={
                f"{project} Backend": ServiceRecord(
                    name=f"{project} Backend",
                    type="backend",
                    cwd=f"/tmp/{project}",
                    project=project,
                    pid=pid,
                )
                for project, pid in (("FeatureA", 101), ("FeatureB", 202))
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    components={
                        "postgres": {
                            "enabled": True,
                            "success": True,
                            "final": 5432,
                        }
                    },
                )
            },
            metadata={
                "project_names": ["FeatureA", "FeatureB"],
                "project_roots": {
                    "FeatureA": "/tmp/FeatureA",
                    "FeatureB": "/tmp/FeatureB",
                },
                "shared_dependencies": True,
            },
        )
        runtime.state_repository.active_states = [state]

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(
                command="stop",
                mode="trees",
                projects=["FeatureA"],
                flags={"batch": True, "runtime_scope": "backend"},
            )
        )

        self.assertEqual(code, 0)
        saved = runtime.state_repository.saved_states[0]
        self.assertEqual(set(saved.services), {"FeatureB Backend"})
        self.assertEqual(set(saved.requirements), {"Main"})
        self.assertTrue(saved.metadata["shared_dependencies"])
        self.assertEqual(saved.metadata["project_names"], ["FeatureB"])
        self.assertEqual(saved.metadata["project_roots"], {"FeatureB": "/tmp/FeatureB"})
        self.assertEqual(runtime.state_repository.saved_authoritative_project_names, [["FeatureB"]])

    def test_targeted_stop_terminates_and_deactivates_every_shadowed_run_for_project(self) -> None:
        runtime = _RuntimeStub()
        release_snapshots: list[list[str]] = []
        runtime.port_planner = SimpleNamespace(
            release_all=lambda: release_snapshots.append(
                [state.run_id for state in runtime.state_repository.active_states]
            )
        )
        runtime.state_repository.active_states = [
            RunState(
                run_id=run_id,
                mode="trees",
                services={
                    f"FeatureA Backend {run_id}": ServiceRecord(
                        name=f"FeatureA Backend {run_id}",
                        type="backend",
                        cwd=f"/tmp/{run_id}/backend",
                        project="FeatureA",
                        pid=pid,
                    )
                },
                metadata={"project_names": ["FeatureA"]},
            )
            for run_id, pid in (("run-new", 202), ("run-old", 101))
        ]
        terminated: list[str] = []
        runtime._terminate_services_from_state = (  # type: ignore[method-assign]
            lambda state, **_kwargs: terminated.append(state.run_id) or set()
        )

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(
                command="stop",
                mode="trees",
                projects=["FeatureA"],
                flags={"batch": True},
            )
        )

        self.assertEqual(code, 0)
        self.assertEqual(terminated, ["run-new", "run-old"])
        self.assertEqual(runtime.state_repository.deactivated_run_ids, ["run-new", "run-old"])
        self.assertEqual(runtime.state_repository.active_states, [])
        self.assertEqual(runtime.state_repository.purge_calls, [])
        self.assertEqual(release_snapshots, [[]])

    def test_targeted_stop_failure_preserves_service_and_run_tracking(self) -> None:
        runtime = _RuntimeStub()
        runtime.port_planner = SimpleNamespace(
            release_all=lambda: self.fail("incomplete termination must retain scoped locks")
        )
        state = RunState(
            run_id="run-a",
            mode="trees",
            services={
                "FeatureA Backend": ServiceRecord(
                    name="FeatureA Backend",
                    type="backend",
                    cwd="/tmp/FeatureA/backend",
                    project="FeatureA",
                    pid=101,
                )
            },
            metadata={"project_names": ["FeatureA"]},
        )
        runtime.state_repository.active_states = [state]
        runtime._terminate_services_from_state = (  # type: ignore[method-assign]
            lambda _state, *, selected_services, **_kwargs: set(selected_services or ())
        )

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(
                command="stop",
                mode="trees",
                projects=["FeatureA"],
                flags={"batch": True},
            )
        )

        self.assertEqual(code, 1)
        self.assertEqual(set(state.services), {"FeatureA Backend"})
        self.assertEqual(runtime.state_repository.saved_states, [state])
        self.assertEqual(runtime.state_repository.deactivated_run_ids, [])
        self.assertEqual(runtime.state_repository.purge_calls, [])

    def test_targeted_stop_missing_termination_result_preserves_service_and_requirements(self) -> None:
        runtime = _RuntimeStub()
        service = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd="/tmp/main/backend",
            project="Main",
            pid=101,
        )
        requirements = RequirementsResult(project="Main", redis={"enabled": True, "final": 6379})
        state = RunState(
            run_id="run-main",
            mode="main",
            services={service.name: service},
            requirements={"Main": requirements},
        )
        runtime._try_load_existing_state = lambda *_args, **_kwargs: state  # type: ignore[method-assign]
        runtime._terminate_services_from_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
        runtime._release_requirement_ports = lambda _requirements: self.fail(  # type: ignore[attr-defined]
            "unconfirmed service must retain requirements"
        )

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(
                command="stop",
                mode="main",
                flags={"services": [service.name], "batch": True},
            )
        )

        self.assertEqual(code, 1)
        self.assertIs(state.services[service.name], service)
        self.assertIs(state.requirements["Main"], requirements)

    def test_stop_all_missing_termination_result_retains_active_run(self) -> None:
        runtime = _RuntimeStub()
        service = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd="/tmp/main/backend",
            project="Main",
            pid=101,
        )
        state = RunState(run_id="run-main", mode="main", services={service.name: service})
        runtime.state_repository.active_states = [state]
        runtime._terminate_services_from_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        code = LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="main"))

        self.assertEqual(code, 1)
        self.assertEqual(runtime.state_repository.active_states, [state])
        self.assertEqual(set(state.services), {service.name})
        self.assertEqual(runtime.state_repository.saved_states, [state])
        self.assertEqual(runtime.state_repository.deactivated_run_ids, [])
        self.assertEqual(runtime.state_repository.purge_calls, [])

    def test_implicit_mode_targeted_stop_cleans_every_tree_shadow_with_duplicate_pid(self) -> None:
        runtime = _RuntimeStub()
        main_state = RunState(
            run_id="run-main",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main/backend",
                    project="Main",
                    pid=303,
                )
            },
            metadata={"project_names": ["Main"]},
        )
        shadow_states = [
            RunState(
                run_id=run_id,
                mode="trees",
                services={
                    f"FeatureA Backend {run_id}": ServiceRecord(
                        name=f"FeatureA Backend {run_id}",
                        type="backend",
                        cwd=f"/tmp/{run_id}/backend",
                        project="FeatureA",
                        pid=404,
                        actual_port=8404,
                    )
                },
                metadata={"project_names": ["FeatureA"]},
            )
            for run_id in ("run-tree-new", "run-tree-old")
        ]
        runtime.state_repository.active_states = [main_state, *shadow_states]
        runtime._try_load_existing_state = (  # type: ignore[method-assign]
            lambda *, mode=None, strict_mode_match=False, project_names=None: (
                shadow_states[0] if mode == "main" and not strict_mode_match and project_names == ["FeatureA"] else None
            )
        )
        live_pids = {404}
        termination_calls: list[int] = []
        released_ports: list[int] = []
        runtime.port_planner = SimpleNamespace(release=lambda port: released_ports.append(port))
        runtime.process_runner = SimpleNamespace(
            is_pid_running=lambda pid: pid in live_pids,
            pid_owns_port=lambda pid, port: pid in live_pids and pid == 404 and port == 8404,
            terminate_process_group=lambda pid, **_kwargs: termination_calls.append(pid) or not live_pids.discard(pid),
        )
        runtime._terminate_service_record = (  # type: ignore[attr-defined]
            lambda service, *, aggressive, verify_ownership: terminate_service_record(
                runtime,
                service,
                aggressive=aggressive,
                verify_ownership=verify_ownership,
            )
        )
        runtime._terminate_services_from_state = (  # type: ignore[method-assign]
            lambda state, *, selected_services, aggressive, verify_ownership: terminate_services_from_state(
                runtime,
                state,
                selected_services=selected_services,
                aggressive=aggressive,
                verify_ownership=verify_ownership,
            )
        )

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(
                command="stop",
                mode="main",
                projects=["FeatureA"],
                flags={"batch": True},
            )
        )

        self.assertEqual(code, 0)
        self.assertEqual(termination_calls, [404])
        self.assertEqual(released_ports, [8404, 8404])
        self.assertEqual(runtime.state_repository.deactivated_run_ids, ["run-tree-new", "run-tree-old"])
        self.assertEqual(runtime.state_repository.active_states, [main_state])

    def test_stop_all_failure_preserves_failed_run_and_never_purges_registry(self) -> None:
        runtime = _RuntimeStub()
        failed_state = RunState(
            run_id="run-failed",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/backend",
                    project="Main",
                    pid=101,
                ),
                "FeatureC Backend": ServiceRecord(
                    name="FeatureC Backend",
                    type="backend",
                    cwd="/tmp/FeatureC/backend",
                    project="FeatureC",
                    pid=102,
                ),
            },
            requirements={
                "shared-main": RequirementsResult(project="Main", db={"enabled": True, "final": 5432}),
                "FeatureC": RequirementsResult(project="FeatureC", redis={"enabled": True, "final": 6379}),
            },
        )
        successful_state = RunState(
            run_id="run-success",
            mode="trees",
            services={
                "FeatureB Backend": ServiceRecord(
                    name="FeatureB Backend",
                    type="backend",
                    cwd="/tmp/FeatureB/backend",
                    project="FeatureB",
                    pid=202,
                )
            },
            requirements={
                "FeatureB": RequirementsResult(project="FeatureB", db={"enabled": True, "final": 5433}),
            },
        )
        runtime.state_repository.active_states = [failed_state, successful_state]
        released_requirements: list[str] = []
        runtime._release_requirement_ports = (  # type: ignore[attr-defined]
            lambda requirements: released_requirements.append(requirements.project)
        )
        runtime._terminate_services_from_state = (  # type: ignore[method-assign]
            lambda state, **_kwargs: {"Main Backend"} if state.run_id == "run-failed" else set()
        )

        runtime._state_lookup_strict_mode_match = lambda _route: True  # type: ignore[method-assign]
        code = LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="main"))

        self.assertEqual(code, 1)
        self.assertEqual(runtime.state_repository.saved_states, [failed_state])
        self.assertEqual(set(failed_state.services), {"Main Backend"})
        self.assertEqual(set(failed_state.requirements), {"shared-main"})
        self.assertEqual(set(released_requirements), {"FeatureC"})
        self.assertEqual(runtime.state_repository.deactivated_run_ids, [])
        self.assertEqual(runtime.state_repository.active_states, [failed_state, successful_state])
        self.assertEqual(runtime.state_repository.purge_calls, [])
        self.assertTrue(any(event.get("event") == "cleanup.incomplete" for event in runtime.events))

        runtime._terminate_services_from_state = lambda _state, **_kwargs: set()  # type: ignore[method-assign]
        retry_code = LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="main"))

        self.assertEqual(retry_code, 0)
        self.assertEqual(released_requirements.count("Main"), 1)
        self.assertEqual(runtime.state_repository.deactivated_run_ids, ["run-failed"])
        self.assertEqual(runtime.state_repository.active_states, [successful_state])
        self.assertEqual(runtime.state_repository.purge_calls, [])

        trees_code = LifecycleCleanupOrchestrator(runtime).execute(Route(command="stop-all", mode="trees"))

        self.assertEqual(trees_code, 0)
        self.assertEqual(released_requirements.count("FeatureB"), 1)
        self.assertEqual(runtime.state_repository.deactivated_run_ids, ["run-failed", "run-success"])
        self.assertEqual(runtime.state_repository.active_states, [])
        self.assertEqual(runtime.state_repository.purge_calls, [False])

    def test_stop_selector_miss_does_not_start_spinner(self) -> None:
        runtime = _RuntimeStub()
        runtime._try_load_existing_state = lambda *args, **kwargs: RunState(  # type: ignore[method-assign]
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main/backend",
                    requested_port=8000,
                    actual_port=8000,
                    pid=123,
                    status="running",
                )
            },
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop", mode="main")

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = message, enabled, start_immediately
            raise AssertionError("spinner should not start when stop target resolution fails")

        with (
            patch("envctl_engine.runtime.lifecycle_cleanup_orchestrator.spinner", side_effect=fake_spinner),
            patch.object(orchestrator, "_select_services_for_stop", return_value=set()),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 1)

    def test_stop_runtime_scope_backend_selects_backend_services_without_prompt(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd=".", pid=2),
                "Other Backend": ServiceRecord(name="Other Backend", type="backend", cwd=".", pid=3),
            },
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop", mode="main", flags={"runtime_scope": "backend", "batch": True})

        selected = orchestrator._select_services_for_stop(state, route)

        self.assertEqual(selected, {"Main Backend", "Other Backend"})
        self.assertEqual(runtime.selection_calls, [])

    def test_stop_service_selector_accepts_additional_service_slug_and_display_forms(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/repo/voice-runtime",
                    pid=2,
                    project="Main",
                    service_slug="voice-runtime",
                ),
            },
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)

        for selector in ("voice-runtime", "service:voice-runtime", "Voice Runtime", "Main Voice Runtime"):
            with self.subTest(selector=selector):
                route = Route(command="stop", mode="main", flags={"services": [selector], "batch": True})
                selected = orchestrator._select_services_for_stop(state, route)
                self.assertEqual(selected, {"Main Voice Runtime"})

    def test_stopped_dashboard_metadata_preserves_additional_service_slug(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/repo/voice-runtime",
                    pid=2,
                    project="Main",
                    service_slug="voice-runtime",
                ),
            },
            metadata={"project_roots": {"Main": "/repo"}},
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)

        orchestrator._remember_dashboard_stopped_services(state, {"Main Voice Runtime"})

        self.assertEqual(
            state.metadata.get("dashboard_stopped_services"),
            [{"name": "Main Voice Runtime", "project": "Main", "type": "voice-runtime"}],
        )
        self.assertIn("voice-runtime", state.metadata.get("dashboard_configured_service_types", []))

    def test_stop_dependencies_scope_releases_requirements_without_terminating_services(self) -> None:
        runtime = _RuntimeStub()
        released: list[int] = []
        terminated: list[set[str] | None] = []
        runtime.port_planner = SimpleNamespace(release=lambda port: released.append(port))
        runtime._terminate_services_from_state = lambda _state, **kwargs: terminated.append(  # type: ignore[method-assign]
            kwargs.get("selected_services")
        ) or set()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
            },
            requirements={
                "Main": RequirementsResult(project="Main", db={"enabled": True, "final": 5432}),
            },
        )
        runtime._try_load_existing_state = lambda *args, **kwargs: state  # type: ignore[method-assign]
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop", mode="main", flags={"runtime_scope": "dependencies", "batch": True})

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(terminated, [])
        self.assertEqual(released, [5432])
        self.assertEqual(state.services.keys(), {"Main Backend"})
        self.assertEqual(state.requirements, {})
        self.assertEqual(runtime.state_repository.saved_states[0].services.keys(), {"Main Backend"})

    def test_targeted_dependencies_scope_preserves_other_project_requirements_and_state(self) -> None:
        runtime = _RuntimeStub()
        released: list[str] = []
        alpha = RequirementsResult(project="Alpha", redis={"enabled": True, "final": 6379})
        beta = RequirementsResult(project="Beta", redis={"enabled": True, "final": 6389})
        state = RunState(
            run_id="run-multi",
            mode="trees",
            services={
                "Beta Backend": ServiceRecord(
                    name="Beta Backend",
                    type="backend",
                    cwd="/beta",
                    project="Beta",
                    pid=2,
                )
            },
            requirements={"Alpha": alpha, "Beta": beta},
            metadata={"project_names": ["Alpha", "Beta"]},
        )
        runtime.state_repository.active_states = [state]
        runtime._try_load_existing_state = lambda *_args, **_kwargs: state  # type: ignore[method-assign]
        runtime._release_requirement_ports = (  # type: ignore[attr-defined]
            lambda requirements: released.append(requirements.project)
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)

        code = orchestrator.execute(
            Route(
                command="stop",
                mode="trees",
                projects=["Alpha"],
                flags={"runtime_scope": "dependencies", "batch": True},
            )
        )

        self.assertEqual(code, 0)
        self.assertEqual(released, ["Alpha"])
        self.assertEqual(set(state.requirements), {"Beta"})
        self.assertIn("Beta Backend", state.services)
        self.assertEqual(runtime.state_repository.deactivated_run_ids, [])
        self.assertEqual(runtime.state_repository.saved_states[-1].metadata["project_names"], ["Beta"])

    def test_dependency_scope_normalizes_positional_and_service_selectors(self) -> None:
        routes = (
            Route(
                command="stop",
                mode="trees",
                passthrough_args=["Alpha"],
                flags={"runtime_scope": "dependencies", "batch": True},
            ),
            Route(
                command="stop",
                mode="trees",
                flags={
                    "runtime_scope": "dependencies",
                    "services": ["Alpha Backend"],
                    "batch": True,
                },
            ),
        )
        for route in routes:
            with self.subTest(route=route):
                runtime = _RuntimeStub()
                state = RunState(
                    run_id="run-selector",
                    mode="trees",
                    services={
                        "Alpha Backend": ServiceRecord(
                            name="Alpha Backend", type="backend", project="Alpha", cwd="/alpha", pid=1
                        ),
                        "Beta Backend": ServiceRecord(
                            name="Beta Backend", type="backend", project="Beta", cwd="/beta", pid=2
                        ),
                    },
                    requirements={
                        "alpha-alias": RequirementsResult(project="Alpha", redis={"enabled": True}),
                        "beta-alias": RequirementsResult(project="Beta", redis={"enabled": True}),
                    },
                    metadata={"project_names": ["Alpha", "Beta"]},
                )
                runtime.state_repository.active_states = [state]
                runtime._try_load_existing_state = lambda *_args, **_kwargs: state  # type: ignore[method-assign]
                released: list[str] = []
                runtime._release_requirement_ports = (  # type: ignore[attr-defined]
                    lambda requirements: released.append(requirements.project)
                )

                code = LifecycleCleanupOrchestrator(runtime).execute(route)

                self.assertEqual(code, 0)
                self.assertEqual(released, ["Alpha"])
                self.assertEqual(set(state.requirements), {"beta-alias"})
                self.assertEqual(set(state.services), {"Alpha Backend", "Beta Backend"})

    def test_unmatched_dependency_service_selector_fails_without_broadening_scope(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-selector-miss",
            mode="trees",
            services={
                "Alpha Backend": ServiceRecord(
                    name="Alpha Backend", type="backend", project="Alpha", cwd="/alpha", pid=1
                )
            },
            requirements={"Alpha": RequirementsResult(project="Alpha", redis={"enabled": True})},
        )
        runtime.state_repository.active_states = [state]
        runtime._try_load_existing_state = lambda *_args, **_kwargs: state  # type: ignore[method-assign]
        runtime._release_requirement_ports = lambda _requirements: self.fail("selector miss released ports")  # type: ignore[attr-defined]

        code = LifecycleCleanupOrchestrator(runtime).execute(
            Route(
                command="stop",
                mode="trees",
                flags={"runtime_scope": "dependencies", "services": ["Missing Worker"], "batch": True},
            )
        )

        self.assertEqual(code, 1)
        self.assertEqual(set(state.requirements), {"Alpha"})
        self.assertEqual(runtime.state_repository.saved_states, [])
        self.assertEqual(runtime.state_repository.deactivated_run_ids, [])

    def test_entire_system_selector_does_not_remove_sibling_project_dependencies(self) -> None:
        routes = (
            Route(
                command="stop",
                mode="trees",
                passthrough_args=["Alpha"],
                flags={"runtime_scope": "entire-system", "batch": True},
            ),
            Route(
                command="stop",
                mode="trees",
                flags={
                    "runtime_scope": "entire-system",
                    "services": ["Alpha Backend"],
                    "batch": True,
                },
            ),
        )
        for route in routes:
            with self.subTest(route=route):
                runtime = _RuntimeStub()
                released: list[int] = []
                runtime.port_planner = SimpleNamespace(release=lambda port: released.append(port))
                state = RunState(
                    run_id="run-entire-selector",
                    mode="trees",
                    services={
                        "Alpha Backend": ServiceRecord(
                            name="Alpha Backend", type="backend", project="Alpha", cwd="/alpha", pid=1
                        ),
                        "Beta Backend": ServiceRecord(
                            name="Beta Backend", type="backend", project="Beta", cwd="/beta", pid=2
                        ),
                    },
                    requirements={
                        "alpha-alias": RequirementsResult(
                            project="Alpha", redis={"id": "redis", "enabled": True, "final": 6379}
                        ),
                        "beta-alias": RequirementsResult(
                            project="Beta", redis={"id": "redis", "enabled": True, "final": 6389}
                        ),
                    },
                    metadata={"project_names": ["Alpha", "Beta"]},
                )
                runtime.state_repository.active_states = [state]
                runtime._try_load_existing_state = lambda *_args, **_kwargs: state  # type: ignore[method-assign]

                code = LifecycleCleanupOrchestrator(runtime).execute(route)

                self.assertEqual(code, 0)
                self.assertEqual(released, [6379])
                self.assertEqual(set(state.services), {"Beta Backend"})
                self.assertEqual(set(state.requirements), {"beta-alias"})

    def test_stop_selected_dependency_component_preserves_services_and_other_dependencies(self) -> None:
        runtime = _RuntimeStub()
        released: list[int] = []
        terminated: list[set[str] | None] = []
        runtime.port_planner = SimpleNamespace(release=lambda port: released.append(port))
        runtime._terminate_services_from_state = lambda _state, **kwargs: terminated.append(  # type: ignore[method-assign]
            kwargs.get("selected_services")
        ) or set()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    db={"enabled": True, "final": 5432},
                    redis={"enabled": True, "final": 6379},
                ),
            },
        )
        runtime._try_load_existing_state = lambda *args, **kwargs: state  # type: ignore[method-assign]
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(
            command="stop",
            mode="main",
            flags={
                "stop_dependency_components": ["Main:redis"],
                "stop_preserve_requirements": True,
                "batch": True,
            },
        )

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(terminated, [])
        self.assertEqual(released, [6379])
        self.assertIn("Main Backend", state.services)
        self.assertIn("Main", state.requirements)
        self.assertFalse(getattr(state.requirements["Main"], "redis").get("enabled", False))
        self.assertTrue(getattr(state.requirements["Main"], "db").get("enabled", False))
        self.assertEqual(runtime.state_repository.saved_states[0].services.keys(), {"Main Backend"})

    def test_stop_selected_services_can_leave_dependencies_running(self) -> None:
        runtime = _RuntimeStub()
        released: list[int] = []
        terminated: list[set[str] | None] = []
        runtime.port_planner = SimpleNamespace(release=lambda port: released.append(port))
        runtime._terminate_services_from_state = lambda _state, **kwargs: terminated.append(  # type: ignore[method-assign]
            kwargs.get("selected_services")
        ) or set()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
            },
            requirements={
                "Main": RequirementsResult(project="Main", db={"enabled": True, "final": 5432}),
            },
        )
        runtime._try_load_existing_state = lambda *args, **kwargs: state  # type: ignore[method-assign]
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(
            command="stop",
            mode="main",
            flags={
                "services": ["Main Backend"],
                "stop_preserve_requirements": True,
                "batch": True,
            },
        )

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(terminated, [{"Main Backend"}])
        self.assertEqual(released, [])
        self.assertEqual(state.services, {})
        self.assertIn("Main", state.requirements)
        self.assertEqual(runtime.state_repository.saved_states[0].requirements.keys(), {"Main"})
        stopped_services = runtime.state_repository.saved_states[0].metadata.get("dashboard_stopped_services")
        self.assertEqual(
            stopped_services,
            [{"name": "Main Backend", "project": "Main", "type": "backend"}],
        )

    def test_interactive_stop_all_services_preserves_stopped_dashboard_state(self) -> None:
        runtime = _RuntimeStub()
        terminated: list[set[str] | None] = []
        runtime._terminate_services_from_state = lambda _state, **kwargs: terminated.append(  # type: ignore[method-assign]
            kwargs.get("selected_services")
        ) or set()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd="/repo/backend", pid=1),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd="/repo/frontend", pid=2),
            },
            metadata={"project_roots": {"Main": "/repo"}},
        )
        runtime._try_load_existing_state = lambda *args, **kwargs: state  # type: ignore[method-assign]
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(
            command="stop",
            mode="main",
            flags={
                "services": ["Main Backend", "Main Frontend"],
                "stop_preserve_requirements": True,
                "interactive_command": True,
                "batch": True,
            },
        )

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(terminated, [{"Main Backend", "Main Frontend"}])
        self.assertEqual(state.services, {})
        self.assertEqual(runtime.state_repository.purge_calls, [])
        self.assertEqual(len(runtime.state_repository.saved_states), 1)
        saved = runtime.state_repository.saved_states[0]
        self.assertEqual(saved.services, {})
        self.assertEqual(
            saved.metadata.get("dashboard_stopped_services"),
            [
                {"name": "Main Backend", "project": "Main", "type": "backend"},
                {"name": "Main Frontend", "project": "Main", "type": "frontend"},
            ],
        )

    def test_stop_selection_routes_through_runtime_backend_selector(self) -> None:
        runtime = _RuntimeStub()
        runtime._try_load_existing_state = lambda *args, **kwargs: RunState(  # type: ignore[method-assign]
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main/backend",
                    requested_port=8000,
                    actual_port=8000,
                    pid=123,
                    status="running",
                )
            },
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop", mode="main", flags={"interactive_command": True})
        state = runtime._try_load_existing_state()
        assert state is not None

        with (
            patch(
                "envctl_engine.runtime.lifecycle_cleanup_orchestrator.RuntimeTerminalUI._can_interactive_tty",
                return_value=True,
            ),
            patch(
                "envctl_engine.runtime.lifecycle_cleanup_orchestrator.RuntimeTerminalUI.flush_pending_interactive_input"
            ) as flush_mock,
        ):
            selected = orchestrator._select_services_for_stop(state, route)

        self.assertEqual(selected, {"Main Backend"})
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Stop services")
        flush_mock.assert_not_called()

    def test_docker_volume_cleanup_uses_warning_glyph_for_nonfatal_volume_removal_miss(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(
            command="blast-all",
            mode="main",
            flags={"blast_keep_worktree_volumes": False, "blast_remove_main_volumes": False},
        )

        def fake_run(command: list[str], *, timeout: float | None = None):  # noqa: ANN001
            _ = timeout
            if command[:3] == ["docker", "ps", "-a"]:
                return 0, "abc123|postgres:16|feature-postgres\n", ""
            if command[:3] == ["docker", "inspect", "-f"]:
                return 0, "envctl_feature_postgres_data\nenvctl_feature_postgres_busy\n", ""
            if command[:3] == ["docker", "rm", "-f"]:
                return 0, "", ""
            if command[:3] == ["docker", "volume", "rm"]:
                if command[-1] == "envctl_feature_postgres_data":
                    return 0, "", ""
                return 1, "", "volume is in use"
            return 127, "", "unexpected"

        output = StringIO()
        with (
            patch.object(orchestrator, "run_best_effort_command", side_effect=fake_run),
            redirect_stdout(output),
        ):
            removed = orchestrator.blast_all_docker_cleanup(route=route)

        self.assertEqual(removed, 1)
        rendered = output.getvalue()
        self.assertIn("✓ removed volume", rendered)
        self.assertIn("⚠ volume not removed (in use or already deleted)", rendered)
        self.assertNotIn("! volume not removed", rendered)


if __name__ == "__main__":
    unittest.main()
