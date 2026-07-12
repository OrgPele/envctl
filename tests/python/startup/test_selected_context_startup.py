from __future__ import annotations

from contextlib import nullcontext
import concurrent.futures
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.service_manager import ServiceCleanupError
from envctl_engine.startup.startup_execution_support import ProjectStartupFailure
from envctl_engine.startup.selected_context_startup import (
    record_project_startup,
    start_selected_contexts,
    start_selected_contexts_with_runtime,
)
from envctl_engine.startup.session import (
    ProjectStartupResult,
    StartupSession,
    track_unterminated_services,
    unconfirmed_service_names,
)
from envctl_engine.state.models import RequirementsResult, ServiceRecord


class _SpinnerStub:
    def __init__(self) -> None:
        self.updates: list[str] = []
        self.failures: list[str] = []
        self.successes: list[str] = []

    def update(self, message: str) -> None:
        self.updates.append(message)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def succeed(self, message: str) -> None:
        self.successes.append(message)

    def end(self) -> None:
        pass


class _SpinnerFactory:
    def __init__(self) -> None:
        self.instances: list[_SpinnerStub] = []

    def __call__(self, message: str, *, enabled: bool):  # noqa: ANN201
        _ = message, enabled
        instance = _SpinnerStub()
        self.instances.append(instance)

        class _Context:
            def __enter__(self_nonlocal):  # noqa: ANN001, ANN202
                return instance

            def __exit__(self_nonlocal, exc_type, exc, tb):  # noqa: ANN001, ANN202
                return False

        return _Context()


class _RuntimeStub:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.events: list[tuple[str, dict[str, object]]] = []
        self.start_calls: list[tuple[str, Route]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, dict(payload)))

    def _tree_parallel_startup_config(self, *, mode: str, route: Route, project_count: int) -> tuple[bool, int]:
        _ = mode, route, project_count
        return False, 1

    def _start_project_context(self, *, context, mode: str, route: Route, run_id: str):  # noqa: ANN001, ANN202
        _ = mode, run_id
        self.start_calls.append((context.name, route))
        return ProjectStartupResult(
            requirements=RequirementsResult(project=context.name),
            services={},
            warnings=[f"{context.name} warning"],
        )


class SelectedContextStartupTests(unittest.TestCase):
    def test_blank_termination_identity_fails_closed_for_all_services(self) -> None:
        services = {"Main Backend": object(), "Main Frontend": object()}

        self.assertEqual(unconfirmed_service_names(["   "], services), set(services))
        self.assertEqual(unconfirmed_service_names(["", "Main Backend"], services), set(services))

    def test_parallel_renderer_error_occurs_only_after_successful_resources_are_recorded(self) -> None:
        runtime = _RuntimeStub()
        runtime._tree_parallel_startup_config = (  # type: ignore[method-assign]
            lambda **_kwargs: (True, 2)
        )
        route = Route(command="start", mode="trees", flags={})
        contexts = [self._context("Alpha"), self._context("Beta")]
        session = self._session(route=route, contexts=contexts)

        with self.assertRaisesRegex(OSError, "renderer failed"):
            start_selected_contexts(
                runtime=runtime,
                session=session,
                suppress_progress_output=lambda _route: False,
                resolved_run_id=lambda _session: "run-1",
                record_project_startup=record_project_startup,
                render_project_startup_warnings=lambda **_kwargs: (_ for _ in ()).throw(OSError("renderer failed")),
                should_degrade_to_plan_agent_handoff=lambda _session, _error: False,
                record_plan_agent_handoff_local_startup_failure=lambda **_kwargs: None,
                spinner_factory=_SpinnerFactory(),
                use_spinner_policy_fn=lambda _policy: nullcontext(),
                resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False, backend="rich"),
                emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
                project_spinner_group_factory=lambda **_kwargs: SimpleNamespace(),
            )

        self.assertEqual(set(session.services_by_project), {"Alpha", "Beta"})
        self.assertEqual(set(session.requirements_by_project), {"Alpha", "Beta"})
        self.assertEqual(set(session.started_context_names), {"Alpha", "Beta"})

    def test_sequential_record_callback_interrupt_retains_returned_resources(self) -> None:
        runtime = _RuntimeStub()
        context = self._context("Alpha")
        requirements = RequirementsResult(project=context.name)
        service = ServiceRecord(
            name="Alpha Backend",
            type="backend",
            cwd="/alpha",
            pid=8101,
        )
        runtime._start_project_context = lambda **_kwargs: ProjectStartupResult(  # type: ignore[method-assign]
            requirements=requirements,
            services={service.name: service},
        )
        route = Route(command="start", mode="trees", flags={})
        session = self._session(route=route, contexts=[context])
        cancellation = KeyboardInterrupt("cancel during result handoff")

        with self.assertRaises(KeyboardInterrupt) as raised:
            start_selected_contexts(
                runtime=runtime,
                session=session,
                suppress_progress_output=lambda _route: False,
                resolved_run_id=lambda _session: "run-1",
                record_project_startup=lambda *_args: (_ for _ in ()).throw(cancellation),
                render_project_startup_warnings=lambda **_kwargs: None,
                should_degrade_to_plan_agent_handoff=lambda _session, _error: False,
                record_plan_agent_handoff_local_startup_failure=lambda **_kwargs: None,
                spinner_factory=_SpinnerFactory(),
                use_spinner_policy_fn=lambda _policy: nullcontext(),
                resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False, backend="rich"),
                emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
                project_spinner_group_factory=lambda **_kwargs: SimpleNamespace(),
            )

        self.assertIs(raised.exception, cancellation)
        self.assertIs(session.requirements_by_project[context.name], requirements)
        self.assertEqual(
            {tracked.pid for tracked in session.unterminated_services.values()},
            {service.pid},
        )

    def test_parallel_main_thread_interrupt_drains_every_successful_future(self) -> None:
        runtime = _RuntimeStub()
        runtime._tree_parallel_startup_config = lambda **_kwargs: (True, 3)  # type: ignore[method-assign]
        contexts = [self._context(name) for name in ("Alpha", "Beta", "Gamma")]
        expected_pids = {context.name: 8200 + index for index, context in enumerate(contexts, start=1)}

        def start_context(*, context, **_kwargs):  # noqa: ANN001, ANN202
            service = ServiceRecord(
                name=f"{context.name} Backend",
                type="backend",
                cwd=f"/{context.name.lower()}",
                pid=expected_pids[context.name],
            )
            return ProjectStartupResult(
                requirements=RequirementsResult(project=context.name),
                services={service.name: service},
            )

        runtime._start_project_context = start_context  # type: ignore[method-assign]
        route = Route(command="start", mode="trees", flags={})
        session = self._session(route=route, contexts=contexts)
        cancellation = KeyboardInterrupt("cancel while collecting parallel results")

        def interrupting_as_completed(futures):  # noqa: ANN001, ANN202
            done, _ = concurrent.futures.wait(
                futures,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            yield next(iter(done))
            raise cancellation

        with (
            patch(
                "envctl_engine.startup.selected_context_startup.concurrent.futures.as_completed",
                side_effect=interrupting_as_completed,
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            start_selected_contexts(
                runtime=runtime,
                session=session,
                suppress_progress_output=lambda _route: False,
                resolved_run_id=lambda _session: "run-1",
                record_project_startup=record_project_startup,
                render_project_startup_warnings=lambda **_kwargs: None,
                should_degrade_to_plan_agent_handoff=lambda _session, _error: False,
                record_plan_agent_handoff_local_startup_failure=lambda **_kwargs: None,
                spinner_factory=_SpinnerFactory(),
                use_spinner_policy_fn=lambda _policy: nullcontext(),
                resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False, backend="rich"),
                emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
                project_spinner_group_factory=lambda **_kwargs: SimpleNamespace(),
            )

        self.assertIs(raised.exception, cancellation)
        tracked_pids = {
            service.pid
            for project_services in session.services_by_project.values()
            for service in project_services.values()
        }.union(service.pid for service in session.unterminated_services.values())
        self.assertEqual(tracked_pids, set(expected_pids.values()))
        self.assertEqual(
            {requirements.project for requirements in session.requirements_by_project.values()},
            set(expected_pids),
        )

    def test_parallel_failure_callback_error_does_not_hide_later_success(self) -> None:
        runtime = _RuntimeStub()
        runtime._tree_parallel_startup_config = lambda **_kwargs: (True, 2)  # type: ignore[method-assign]

        def start_context(*, context, **_kwargs):  # noqa: ANN001, ANN202
            if context.name == "Alpha":
                raise RuntimeError("alpha failed")
            return ProjectStartupResult(
                requirements=RequirementsResult(project=context.name),
                services={"Beta Backend": object()},
            )

        runtime._start_project_context = start_context  # type: ignore[method-assign]
        original_emit = runtime._emit

        def emit(event: str, **payload: object) -> None:
            if event == "startup.project.failed":
                raise OSError("event sink failed")
            original_emit(event, **payload)

        runtime._emit = emit  # type: ignore[method-assign]
        route = Route(command="start", mode="trees", flags={})
        session = self._session(route=route, contexts=[self._context("Alpha"), self._context("Beta")])

        with self.assertRaisesRegex(RuntimeError, "alpha failed"):
            start_selected_contexts(
                runtime=runtime,
                session=session,
                suppress_progress_output=lambda _route: False,
                resolved_run_id=lambda _session: "run-1",
                record_project_startup=record_project_startup,
                render_project_startup_warnings=lambda **_kwargs: None,
                should_degrade_to_plan_agent_handoff=lambda _session, _error: False,
                record_plan_agent_handoff_local_startup_failure=lambda **_kwargs: None,
                spinner_factory=_SpinnerFactory(),
                use_spinner_policy_fn=lambda _policy: nullcontext(),
                resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False, backend="rich"),
                emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
                project_spinner_group_factory=lambda **_kwargs: SimpleNamespace(),
            )

        self.assertIn("Beta", session.services_by_project)
        self.assertIn("Beta", session.requirements_by_project)

    def test_parallel_name_collision_drains_and_records_every_completed_future(self) -> None:
        runtime = _RuntimeStub()
        runtime._tree_parallel_startup_config = lambda **_kwargs: (True, 3)  # type: ignore[method-assign]

        def start_context(*, context, **_kwargs):  # noqa: ANN001, ANN202
            if context.name == "Gamma":
                service = ServiceRecord(
                    name="Gamma Worker",
                    type="worker",
                    cwd="/gamma",
                    pid=303,
                    project="Gamma",
                    service_slug="worker",
                )
            else:
                service = ServiceRecord(
                    name="Opaque Shared Runtime",
                    type="worker",
                    cwd=f"/{context.name.lower()}",
                    pid=101 if context.name == "Alpha" else 202,
                    project=context.name,
                    service_slug="worker",
                )
            return ProjectStartupResult(
                requirements=RequirementsResult(project=context.name),
                services={service.name: service},
            )

        runtime._start_project_context = start_context  # type: ignore[method-assign]
        route = Route(command="start", mode="trees", flags={})
        contexts = [self._context(name) for name in ("Alpha", "Beta", "Gamma")]
        session = self._session(route=route, contexts=contexts)

        with self.assertRaisesRegex(RuntimeError, "tracked startup state"):
            start_selected_contexts(
                runtime=runtime,
                session=session,
                suppress_progress_output=lambda _route: False,
                resolved_run_id=lambda _session: "run-1",
                record_project_startup=record_project_startup,
                render_project_startup_warnings=lambda **_kwargs: None,
                should_degrade_to_plan_agent_handoff=lambda _session, _error: False,
                record_plan_agent_handoff_local_startup_failure=lambda **_kwargs: None,
                spinner_factory=_SpinnerFactory(),
                use_spinner_policy_fn=lambda _policy: nullcontext(),
                resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False, backend="rich"),
                emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
                project_spinner_group_factory=lambda **_kwargs: SimpleNamespace(),
            )

        tracked = {
            service.pid
            for services in session.services_by_project.values()
            for service in services.values()
        }.union(service.pid for service in session.unterminated_services.values())
        self.assertEqual(tracked, {101, 202, 303})
        self.assertIn("Gamma", session.requirements_by_project)

    def test_unterminated_service_error_is_carried_into_session_state(self) -> None:
        route = Route(command="start", mode="main", flags={})
        session = self._session(route=route, contexts=[])
        service = ServiceRecord(name="Main Backend", type="backend", cwd="/repo", pid=63001)
        failure = ServiceCleanupError("cleanup failed", {service.name: service})

        track_unterminated_services(session, failure)

        self.assertIs(session.unterminated_services[service.name], service)
        self.assertIs(session.merged_services[service.name], service)

    def test_parallel_failure_records_with_duplicate_names_keep_both_processes(self) -> None:
        route = Route(command="start", mode="trees", flags={})
        session = self._session(route=route, contexts=[])
        alpha = ServiceRecord(
            name="Opaque Worker",
            type="worker",
            cwd="/alpha",
            pid=111,
            project="Alpha",
            service_slug="worker",
        )
        beta = ServiceRecord(
            name="Opaque Worker",
            type="worker",
            cwd="/beta",
            pid=222,
            project="Beta",
            service_slug="worker",
        )

        track_unterminated_services(session, ServiceCleanupError("alpha cleanup failed", {alpha.name: alpha}))
        track_unterminated_services(session, ServiceCleanupError("beta cleanup failed", {beta.name: beta}))

        self.assertEqual({service.pid for service in session.unterminated_services.values()}, {111, 222})
        self.assertEqual(len(session.unterminated_services), 2)
        self.assertTrue(any("Restart Collision" in name for name in session.unterminated_services))

    def test_merged_services_rejects_preserved_new_name_collision(self) -> None:
        route = Route(command="restart", mode="main", flags={})
        session = self._session(route=route, contexts=[])
        preserved = ServiceRecord(name="Main Backend", type="backend", cwd="/repo/old", pid=63001)
        replacement = ServiceRecord(name="Main Backend", type="backend", cwd="/repo/new", pid=63002)
        session.preserved_services[preserved.name] = preserved
        session.services_by_project["Main"] = {replacement.name: replacement}

        with self.assertRaisesRegex(
            RuntimeError,
            "Refusing to overwrite preserved service state.*Main Backend",
        ):
            _ = session.merged_services
        self.assertTrue(session.preserve_existing_state_on_failure)
        self.assertEqual(session.service_state_collisions, {"Main Backend"})

    def test_merged_requirements_rejects_preserved_new_owner_collision(self) -> None:
        route = Route(command="restart", mode="main", flags={})
        session = self._session(route=route, contexts=[])
        session.preserved_requirements["Main"] = RequirementsResult(
            project="Main",
            redis={"enabled": True, "final": 6380},
        )
        session.requirements_by_project["Main"] = RequirementsResult(
            project="Main",
            redis={"enabled": True, "final": 6381},
        )

        with self.assertRaisesRegex(RuntimeError, "preserved requirement state.*Main"):
            _ = session.merged_requirements

        self.assertTrue(session.preserve_existing_state_on_failure)

    def test_merged_requirements_deduplicates_reused_alias_authority_by_identity(self) -> None:
        route = Route(command="restart", mode="main", flags={})
        session = self._session(route=route, contexts=[])
        requirements = RequirementsResult(
            project="Main",
            redis={"enabled": True, "success": True, "final": 6381},
        )
        session.preserved_requirements["Main Restart Collision"] = requirements
        session.requirements_by_project["Main"] = requirements

        merged = session.merged_requirements

        self.assertEqual(list(merged), ["Main Restart Collision"])
        self.assertIs(merged["Main Restart Collision"], requirements)

    def test_merged_requirements_ignores_disabled_projection_when_dependencies_are_skipped(self) -> None:
        route = Route(command="start", mode="main", flags={"launch_dependencies": False})
        session = self._session(route=route, contexts=[])
        preserved = RequirementsResult(
            project="Main",
            redis={"enabled": True, "success": True, "final": 6379},
        )
        session.preserved_requirements["Main Historical Authority"] = preserved
        session.requirements_by_project["Main"] = RequirementsResult(
            project="Main",
            redis={"enabled": False, "success": True, "final": 6482},
        )

        merged = session.merged_requirements

        self.assertEqual(list(merged), ["Main Historical Authority"])
        self.assertIs(merged["Main Historical Authority"], preserved)

    def test_record_project_startup_tracks_collision_for_failure_cleanup(self) -> None:
        route = Route(command="restart", mode="main", flags={})
        context = self._context("Main")
        session = self._session(route=route, contexts=[context])
        preserved = ServiceRecord(name="Main Backend", type="backend", cwd="/repo/old", pid=63001)
        replacement = ServiceRecord(name="Main Backend", type="backend", cwd="/repo/new", pid=63002)
        session.preserved_services[preserved.name] = preserved
        requirements = RequirementsResult(project="Main")

        with self.assertRaisesRegex(RuntimeError, "Refusing to overwrite preserved service state"):
            record_project_startup(
                session,
                context,
                ProjectStartupResult(requirements=requirements, services={replacement.name: replacement}),
            )

        self.assertTrue(session.preserve_existing_state_on_failure)
        replacement_names = [
            name for name in session.unterminated_services if name.startswith("Main Backend Restart Collision")
        ]
        self.assertEqual(len(replacement_names), 1)
        self.assertEqual(session.unterminated_services[replacement_names[0]].pid, replacement.pid)
        self.assertEqual(session.unterminated_services[replacement_names[0]].name, replacement_names[0])
        self.assertIs(session.requirements_by_project["Main"], requirements)
        self.assertEqual(session.services_by_project, {})

    def test_duplicate_context_name_with_disjoint_services_retains_both_startups(self) -> None:
        route = Route(command="start", mode="trees", flags={})
        context = self._context("Same")
        session = self._session(route=route, contexts=[context, context])
        first = ServiceRecord(name="Opaque A", type="worker", cwd="/one", pid=1, project="Same")
        second = ServiceRecord(name="Opaque B", type="worker", cwd="/two", pid=2, project="Same")
        first_requirements = RequirementsResult(project="Same", redis={"enabled": True, "final": 6379})
        second_requirements = RequirementsResult(project="Same", redis={"enabled": True, "final": 6381})

        record_project_startup(
            session,
            context,
            ProjectStartupResult(requirements=first_requirements, services={first.name: first}),
        )
        with self.assertRaisesRegex(RuntimeError, "project:Same"):
            record_project_startup(
                session,
                context,
                ProjectStartupResult(requirements=second_requirements, services={second.name: second}),
            )

        self.assertEqual({service.pid for service in session.services_by_project["Same"].values()}, {1})
        self.assertEqual({service.pid for service in session.unterminated_services.values()}, {2})
        self.assertEqual(set(session.requirements_by_project), {"Same", "Same Restart Collision"})
        self.assertIs(session.requirements_by_project["Same"], first_requirements)
        self.assertIs(session.requirements_by_project["Same Restart Collision"], second_requirements)

    def test_project_startup_failure_carries_requirements_into_failure_state(self) -> None:
        route = Route(command="start", mode="main", flags={})
        session = self._session(route=route, contexts=[])
        requirements = RequirementsResult(
            project="Main",
            redis={"enabled": True, "success": True, "final": 6379},
        )
        failure = ProjectStartupFailure(
            "backend failed",
            project="Main",
            requirements=requirements,
        )

        track_unterminated_services(session, failure)

        self.assertIs(session.requirements_by_project["Main"], requirements)
        self.assertIs(session.merged_requirements["Main"], requirements)

    @staticmethod
    def _context(name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, root=Path("/tmp") / name, ports={})

    @staticmethod
    def _session(*, route: Route, contexts: list[SimpleNamespace]) -> StartupSession:
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command=route.command,
            runtime_mode=route.mode,
            run_id="run-1",
        )
        session.selected_contexts = list(contexts)
        session.contexts_to_start = list(contexts)
        return session

    def test_start_selected_contexts_builds_execution_route_and_records_sequential_results(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS"] = "true"
        route = Route(command="plan", mode="trees", raw_args=["plan"], passthrough_args=[], projects=[], flags={})
        session = self._session(route=route, contexts=[self._context("Alpha")])

        start_selected_contexts(
            runtime=runtime,
            session=session,
            suppress_progress_output=lambda route: False,
            resolved_run_id=lambda session: "run-1",
            record_project_startup=lambda session, context, result: (
                session.requirements_by_project.__setitem__(context.name, result.requirements),
                session.services_by_project.__setitem__(context.name, result.services),
                session.started_context_names.append(context.name),
            ),
            render_project_startup_warnings=lambda *, context, warnings, route, project_spinner_group: (
                warnings and None
            ),
            should_degrade_to_plan_agent_handoff=lambda session, error: False,
            record_plan_agent_handoff_local_startup_failure=lambda session, project_name, error: None,
            spinner_factory=_SpinnerFactory(),
            use_spinner_policy_fn=lambda policy: nullcontext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich"),
            emit_spinner_policy_fn=lambda emit, policy, context: emit("spinner.policy", **context),
            project_spinner_group_factory=lambda **kwargs: SimpleNamespace(
                __enter__=lambda self: self,
                __exit__=lambda self, exc_type, exc, tb: False,
                update_project=lambda project, message: None,
                mark_success=lambda project, message: None,
                mark_failure=lambda project, message: None,
            ),
        )

        self.assertEqual(session.started_context_names, ["Alpha"])
        self.assertEqual(runtime.start_calls[0][0], "Alpha")
        execution_route = runtime.start_calls[0][1]
        self.assertIsNone(execution_route.flags["_spinner_update"])
        self.assertIsNone(execution_route.flags["_spinner_update_project"])
        self.assertTrue(execution_route.flags["debug_suppress_progress_output"])
        self.assertEqual(runtime.events[0][0], "spinner.policy")
        self.assertIn(
            ("startup.execution", {"mode": "sequential", "workers": 1, "projects": ["Alpha"]}), runtime.events
        )

    def test_record_project_startup_updates_session_result_maps_and_started_names(self) -> None:
        route = Route(command="start", mode="trees", raw_args=["start"], passthrough_args=[], projects=[], flags={})
        context = self._context("Alpha")
        session = self._session(route=route, contexts=[context])
        requirements = RequirementsResult(project="Alpha")
        result = ProjectStartupResult(requirements=requirements, services={"Alpha Backend": object()})

        record_project_startup(session, context, result)

        self.assertEqual(session.requirements_by_project, {"Alpha": requirements})
        self.assertEqual(session.services_by_project, {"Alpha": result.services})
        self.assertEqual(session.started_context_names, ["Alpha"])

    def test_start_selected_contexts_degrades_local_startup_failure_when_handoff_allowed(self) -> None:
        runtime = _RuntimeStub()

        def fail_start_project_context(**kwargs):  # noqa: ANN001, ANN202
            raise RuntimeError("backend failed")

        runtime._start_project_context = fail_start_project_context  # type: ignore[method-assign]
        route = Route(command="plan", mode="trees", raw_args=["plan"], passthrough_args=[], projects=[], flags={})
        session = self._session(route=route, contexts=[self._context("Alpha")])
        degraded: list[tuple[str, str]] = []

        start_selected_contexts(
            runtime=runtime,
            session=session,
            suppress_progress_output=lambda route: False,
            resolved_run_id=lambda session: "run-1",
            record_project_startup=lambda session, context, result: None,
            render_project_startup_warnings=lambda *, context, warnings, route, project_spinner_group: None,
            should_degrade_to_plan_agent_handoff=lambda session, error: True,
            record_plan_agent_handoff_local_startup_failure=lambda session, project_name, error: degraded.append(
                (project_name, error)
            ),
            spinner_factory=_SpinnerFactory(),
            use_spinner_policy_fn=lambda policy: nullcontext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich"),
            emit_spinner_policy_fn=lambda emit, policy, context: None,
            project_spinner_group_factory=lambda **kwargs: SimpleNamespace(),
        )

        self.assertEqual(degraded, [("Alpha", "backend failed")])
        self.assertEqual(session.started_context_names, [])

    def test_runtime_bound_selected_context_startup_records_results_and_uses_owner_dependencies(self) -> None:
        runtime = _RuntimeStub()
        route = Route(command="start", mode="trees", raw_args=["start"], passthrough_args=[], projects=[], flags={})
        context = self._context("Alpha")
        session = self._session(route=route, contexts=[context])
        rendered_warnings: list[tuple[str, list[str]]] = []
        degradation_checks: list[tuple[str, str]] = []
        local_failures: list[tuple[str, str]] = []
        spinner_policies: list[dict[str, object]] = []

        start_selected_contexts_with_runtime(
            runtime,
            session,
            resolved_run_id=lambda session: "run-1",
            render_project_startup_warnings=lambda *, context, warnings, route, project_spinner_group: (
                rendered_warnings.append((context.name, list(warnings)))
            ),
            should_degrade_to_plan_agent_handoff=lambda session, error: (
                degradation_checks.append((session.requested_command, error)) or False
            ),
            record_plan_agent_handoff_local_startup_failure=lambda session, project_name, error: local_failures.append(
                (project_name, error)
            ),
            spinner_factory=_SpinnerFactory(),
            use_spinner_policy_fn=lambda policy: nullcontext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich"),
            emit_spinner_policy_fn=lambda emit, policy, context: spinner_policies.append(dict(context)),
            project_spinner_group_factory=lambda **kwargs: SimpleNamespace(
                __enter__=lambda self: self,
                __exit__=lambda self, exc_type, exc, tb: False,
                update_project=lambda project, message: None,
                mark_success=lambda project, message: None,
                mark_failure=lambda project, message: None,
            ),
        )

        self.assertEqual(session.started_context_names, ["Alpha"])
        self.assertIn("Alpha", session.requirements_by_project)
        self.assertEqual(session.services_by_project, {"Alpha": {}})
        self.assertEqual(rendered_warnings, [("Alpha", ["Alpha warning"])])
        self.assertEqual(degradation_checks, [])
        self.assertEqual(local_failures, [])
        self.assertEqual(spinner_policies, [{"component": "startup_orchestrator", "op_id": "startup.execute"}])


if __name__ == "__main__":
    unittest.main()
