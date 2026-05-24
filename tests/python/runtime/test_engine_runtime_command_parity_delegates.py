# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.engine_runtime_command_parity_test_support import *


class EngineRuntimeCommandParityDelegateTests(EngineRuntimeCommandParityTestCase):
    def test_non_start_commands_do_not_silently_route_to_start(self) -> None:
        runtime = self._runtime()

        def fail_start(_route):
            self.fail("_start should not be used for direct command actions")

        runtime._start = fail_start  # type: ignore[assignment]

        commands = [
            "--doctor",
            "--dashboard",
            "--logs",
            "--health",
            "--errors",
            "--test",
            "--pr",
            "--commit",
            "--review",
            "--migrate",
            "--delete-worktree",
            "--blast-worktree",
        ]
        for token in commands:
            route = parse_route([token], env={})
            code = runtime.dispatch(route)
            self.assertIn(code, {0, 1}, msg=token)

    def test_start_family_routes_to_start_path(self) -> None:
        runtime = self._runtime()
        seen: list[str] = []

        def fake_start(route):
            seen.append(route.command)
            return 0

        runtime.startup_orchestrator.execute = fake_start  # type: ignore[assignment]

        for token in ("start", "--plan", "--restart"):
            route = parse_route([token], env={})
            code = runtime.dispatch(route)
            self.assertEqual(code, 0, msg=token)

        self.assertEqual(seen, ["start", "plan", "restart"])

    def test_start_method_delegates_to_startup_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["start"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "start")
            return 91

        runtime.startup_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._start(route)

        self.assertEqual(code, 91)

    def test_resume_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--resume"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "resume")
            return 73

        runtime.resume_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._resume(route)

        self.assertEqual(code, 73)

    def test_doctor_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()

        def fake_execute():  # noqa: ANN202
            return 64

        runtime.doctor_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._doctor()

        self.assertEqual(code, 64)

    def test_dashboard_method_delegates_to_dashboard_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--dashboard"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "dashboard")
            return 58

        runtime.dashboard_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._dashboard(route)

        self.assertEqual(code, 58)

    def test_state_action_method_delegates_to_state_action_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--health"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "health")
            return 39

        runtime.state_action_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._state_action(route)

        self.assertEqual(code, 39)

    def test_action_command_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["test", "--project", "feature-a-1"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "test")
            return 27

        runtime.action_command_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._run_action_command(route)

        self.assertEqual(code, 27)

    def test_doctor_readiness_gates_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()

        expected = {
            "command_parity": True,
            "runtime_truth": False,
            "lifecycle": True,
            "shipability": False,
        }

        def fake_readiness():  # noqa: ANN202
            return expected

        runtime.doctor_orchestrator.readiness_gates = fake_readiness  # type: ignore[assignment]

        readiness = runtime._doctor_readiness_gates()

        self.assertEqual(readiness, expected)

    def test_resume_restore_missing_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        state = RunState(run_id="run-1", mode="main")
        missing = ["Main Backend"]
        expected = ["Main: restore failed"]

        def fake_restore(s, m, *, route=None):  # noqa: ANN001
            self.assertIs(s, state)
            self.assertEqual(m, missing)
            self.assertIsNone(route)
            return expected

        runtime.resume_orchestrator.restore_missing = fake_restore  # type: ignore[assignment]

        errors = runtime._resume_restore_missing(state, missing, route=None)

        self.assertEqual(errors, expected)

    def test_resolve_action_targets_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["test", "--project", "feature-a-1"], env={})
        expected_targets: list[object] = []
        expected_error = "missing targets"

        def fake_resolve(r, *, trees_only):  # noqa: ANN001
            self.assertEqual(r.command, "test")
            self.assertFalse(trees_only)
            return expected_targets, expected_error

        runtime.action_command_orchestrator.resolve_targets = fake_resolve  # type: ignore[assignment]

        targets, error = runtime._resolve_action_targets(route, trees_only=False)

        self.assertEqual(targets, expected_targets)
        self.assertEqual(error, expected_error)

    def test_run_test_action_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["test"], env={})
        expected_code = 12

        def fake_run(r, targets):  # noqa: ANN001
            self.assertEqual(r.command, "test")
            self.assertEqual(targets, [])
            return expected_code

        runtime.action_command_orchestrator.run_test_action = fake_run  # type: ignore[assignment]

        code = runtime._run_test_action(route, [])

        self.assertEqual(code, expected_code)

    def test_run_project_action_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["pr"], env={})
        expected_code = 19

        def fake_run_project(r, targets, **kwargs):  # noqa: ANN001
            self.assertEqual(r.command, "pr")
            self.assertEqual(targets, [])
            self.assertEqual(kwargs["command_name"], "pr")
            self.assertEqual(kwargs["env_key"], "ENVCTL_ACTION_PR_CMD")
            return expected_code

        runtime.action_command_orchestrator.run_project_action = fake_run_project  # type: ignore[assignment]

        code = runtime._run_project_action(
            route,
            [],
            command_name="pr",
            env_key="ENVCTL_ACTION_PR_CMD",
            default_command=None,
            default_cwd=runtime.config.base_dir,
            default_append_project_path=False,
            extra_env={},
        )

        self.assertEqual(code, expected_code)

    def test_action_entrypoint_methods_delegate_to_action_support(self) -> None:
        for method_name in (
            "_run_action_command",
            "_resolve_action_targets",
            "_run_test_action",
            "_run_pr_action",
            "_run_commit_action",
            "_run_analyze_action",
            "_run_migrate_action",
            "_run_project_action",
            "_action_replacements",
            "_action_env",
            "_action_extra_env",
        ):
            with self.subTest(method=method_name):
                self.assertLessEqual(len(getattr(PythonEngineRuntime, method_name).__code__.co_names), 3)

    def test_service_policy_and_command_methods_delegate_to_runtime_owners(self) -> None:
        for method_name in (
            "_service_rebound_max_delta",
            "_service_listener_timeout",
            "_service_startup_progress_timeout",
            "_dashboard_truth_refresh_seconds",
            "_dashboard_reconcile_for_snapshot",
            "_service_truth_timeout",
            "_service_startup_grace_seconds",
            "_service_within_startup_grace",
            "_requirement_command",
            "_requirement_command_source",
            "_requirement_command_resolved",
            "_service_start_command",
            "_service_command_source",
            "_service_start_command_resolved",
            "_command_override_value",
            "_split_command",
            "_command_env",
            "_default_python_executable",
            "_command_exists",
        ):
            with self.subTest(method=method_name):
                self.assertLessEqual(len(getattr(PythonEngineRuntime, method_name).__code__.co_names), 3)

    def test_run_migrate_action_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["migrate"], env={})
        expected_code = 33

        def fake_migrate(r, targets):  # noqa: ANN001
            self.assertEqual(r.command, "migrate")
            self.assertEqual(targets, [])
            return expected_code

        runtime.action_command_orchestrator.run_migrate_action = fake_migrate  # type: ignore[assignment]

        code = runtime._run_migrate_action(route, [])

        self.assertEqual(code, expected_code)

    def test_run_delete_worktree_action_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["delete-worktree", "--project", "feature-a-1"], env={})
        expected_code = 44

        def fake_delete(r):  # noqa: ANN001
            self.assertEqual(r.command, "delete-worktree")
            return expected_code

        runtime.action_command_orchestrator.run_delete_worktree_action = fake_delete  # type: ignore[assignment]

        code = runtime._run_delete_worktree_action(route)

        self.assertEqual(code, expected_code)

    def test_resume_context_for_project_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        state = RunState(run_id="run-1", mode="trees")
        expected = SimpleNamespace(name="feature-a-1")

        def fake_context_for_project(s, p):  # noqa: ANN001
            self.assertIs(s, state)
            self.assertEqual(p, "feature-a-1")
            return expected

        runtime.resume_orchestrator.context_for_project = fake_context_for_project  # type: ignore[assignment]

        context = runtime._resume_context_for_project(state, "feature-a-1")

        self.assertIs(context, expected)

    def test_resume_project_root_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        state = RunState(run_id="run-1", mode="trees")
        expected = Path("/tmp/feature-a-1")

        def fake_project_root(s, p):  # noqa: ANN001
            self.assertIs(s, state)
            self.assertEqual(p, "feature-a-1")
            return expected

        runtime.resume_orchestrator.project_root = fake_project_root  # type: ignore[assignment]

        root = runtime._resume_project_root(state, "feature-a-1")

        self.assertEqual(root, expected)

    def test_apply_resume_ports_to_context_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        state = RunState(run_id="run-1", mode="trees")
        context = SimpleNamespace(name="feature-a-1")
        seen: list[object] = []

        def fake_apply(c, s):  # noqa: ANN001
            seen.extend([c, s])

        runtime.resume_orchestrator.apply_ports_to_context = fake_apply  # type: ignore[assignment]

        runtime._apply_resume_ports_to_context(context, state)  # type: ignore[arg-type]

        self.assertEqual(seen, [context, state])

    def test_clear_runtime_state_method_delegates_to_lifecycle_cleanup_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--stop-all"], env={})
        seen: dict[str, object] = {}

        def fake_clear(*, command, aggressive=False, route=None):  # noqa: ANN001
            seen["command"] = command
            seen["aggressive"] = aggressive
            seen["route"] = route

        runtime.lifecycle_cleanup_orchestrator.clear_runtime_state = fake_clear  # type: ignore[assignment]

        runtime._clear_runtime_state(command="stop-all", aggressive=True, route=route)

        self.assertEqual(seen["command"], "stop-all")
        self.assertEqual(seen["aggressive"], True)
        self.assertIs(seen["route"], route)

    def test_blast_all_port_range_method_delegates_to_lifecycle_cleanup_orchestrator(self) -> None:
        runtime = self._runtime()
        expected = [8100, 8101, 8102]

        def fake_port_range():  # noqa: ANN202
            return expected

        runtime.lifecycle_cleanup_orchestrator.blast_all_port_range = fake_port_range  # type: ignore[assignment]

        ports = runtime._blast_all_port_range()

        self.assertEqual(ports, expected)

    def test_blast_all_docker_cleanup_method_delegates_to_lifecycle_cleanup_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--blast-all"], env={})
        expected = 7

        def fake_cleanup(*, route=None):  # noqa: ANN001
            self.assertIs(route, route_arg)
            return expected

        route_arg = route
        runtime.lifecycle_cleanup_orchestrator.blast_all_docker_cleanup = fake_cleanup  # type: ignore[assignment]

        removed = runtime._blast_all_docker_cleanup(route=route)

        self.assertEqual(removed, expected)

    def test_enforce_runtime_readiness_contract_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()
        seen: dict[str, object] = {}

        def fake_enforce(*, scope, strict_required=None):  # noqa: ANN001
            seen["scope"] = scope
            seen["strict_required"] = strict_required
            return False

        runtime.doctor_orchestrator.enforce_runtime_readiness_contract = fake_enforce  # type: ignore[assignment]

        passed = runtime._enforce_runtime_readiness_contract(scope="resume", strict_required=True)

        self.assertFalse(passed)
        self.assertEqual(seen, {"scope": "resume", "strict_required": True})

    def test_doctor_should_check_tests_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()

        runtime.doctor_orchestrator.doctor_should_check_tests = lambda: True  # type: ignore[assignment]

        self.assertTrue(runtime._doctor_should_check_tests())

    def test_start_project_context_method_delegates_to_startup_orchestrator(self) -> None:
        runtime = self._runtime()
        context = SimpleNamespace(name="feature-a-1")
        route = parse_route(["start"], env={})
        expected_requirements = SimpleNamespace(project="feature-a-1")
        expected_services = {"feature-a-1 Backend": object()}
        expected_warnings = ["Warning: backend migration step failed; continuing without migration (...)"]

        def fake_start_project_context(*, context, mode, route, run_id):  # noqa: ANN001
            self.assertEqual(getattr(context, "name", ""), "feature-a-1")
            self.assertEqual(mode, "trees")
            self.assertEqual(route.command, "start")
            self.assertEqual(run_id, "run-42")
            return ProjectStartupResult(
                requirements=expected_requirements,
                services=expected_services,
                warnings=expected_warnings,
            )

        runtime.startup_orchestrator.start_project_context = fake_start_project_context  # type: ignore[assignment]

        result = runtime._start_project_context(
            context=context,  # type: ignore[arg-type]
            mode="trees",
            route=route,
            run_id="run-42",
        )

        self.assertIs(result.requirements, expected_requirements)
        self.assertIs(result.services, expected_services)
        self.assertEqual(result.warnings, expected_warnings)

    def test_start_requirements_for_project_method_delegates_to_startup_orchestrator(self) -> None:
        runtime = self._runtime()
        context = SimpleNamespace(name="Main")
        route = parse_route(["start"], env={})
        expected = SimpleNamespace(project="Main")

        def fake_start_requirements(c, *, mode, route=None):  # noqa: ANN001
            self.assertIs(c, context)
            self.assertEqual(mode, "main")
            self.assertIs(route, route_arg)
            return expected

        route_arg = route
        runtime.startup_orchestrator.start_requirements_for_project = fake_start_requirements  # type: ignore[assignment]

        result = runtime._start_requirements_for_project(context, mode="main", route=route)  # type: ignore[arg-type]

        self.assertIs(result, expected)

    def test_start_project_services_method_delegates_to_startup_orchestrator(self) -> None:
        runtime = self._runtime()
        context = SimpleNamespace(name="Main")
        requirements = SimpleNamespace(project="Main")
        route = parse_route(["start"], env={})
        expected = {"Main Backend": object()}

        def fake_start_services(c, *, requirements, run_id, route=None):  # noqa: ANN001
            self.assertIs(c, context)
            self.assertIs(requirements, requirements_arg)
            self.assertEqual(run_id, "run-99")
            self.assertIs(route, route_arg)
            return expected

        requirements_arg = requirements
        route_arg = route
        runtime.startup_orchestrator.start_project_services = fake_start_services  # type: ignore[assignment]

        services = runtime._start_project_services(
            context,  # type: ignore[arg-type]
            requirements=requirements,  # type: ignore[arg-type]
            run_id="run-99",
            route=route,
        )

        self.assertIs(services, expected)
