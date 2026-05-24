# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.ui.dashboard_rendering_parity_test_support import *


class DashboardRenderingDependenciesParityTests(DashboardRenderingParityTestCase):
    def test_dashboard_visual_host_rewrites_dashboard_urls_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"NO_COLOR": "1", "ENVCTL_UI_VISUAL_HOST": "192.0.2.42"},
            )
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-visual-host",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        pid=222,
                        status="unreachable",
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                        n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://192.0.2.42:8000", output)
            self.assertIn("Frontend: http://192.0.2.42:9000", output)
            self.assertIn("redis: http://192.0.2.42:6380 [Healthy]", output)
            self.assertIn("n8n: http://192.0.2.42:5678 [Healthy]", output)
            self.assertNotIn("http://localhost:8000", output)
            self.assertNotIn("http://localhost:9000", output)
            self.assertNotIn("http://localhost:6380", output)
            self.assertNotIn("http://localhost:5678", output)

            runtime_projection = cast(dict[str, Any], build_runtime_map(state)["projection"])
            self.assertEqual(runtime_projection["Main"]["backend_url"], "http://localhost:8000")
            self.assertIsNone(runtime_projection["Main"]["frontend_url"])

    def test_dashboard_groups_shared_tree_dependencies_once_after_project_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"NO_COLOR": "1", "ENVCTL_UI_VISUAL_HOST": "192.0.2.42"},
            )
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            shared_requirements = RequirementsResult(
                project="Main",
                redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                supabase={"enabled": True, "runtime_status": "healthy", "final": 54321, "success": True},
                n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
            )
            state = RunState(
                run_id="run-shared-deps",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8101,
                        actual_port=8101,
                        pid=111,
                        status="running",
                    ),
                    "feature-b-1 Frontend": ServiceRecord(
                        name="feature-b-1 Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9102,
                        actual_port=9102,
                        pid=222,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": shared_requirements,
                    "feature-b-1": shared_requirements,
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo / "trees" / "feature-a" / "1"),
                        "feature-b-1": str(repo / "trees" / "feature-b" / "1"),
                    },
                    "dashboard_dependency_scope": "shared",
                    "dashboard_shared_dependency_project": "Main",
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Shared dependencies:", output)
            self.assertEqual(output.count("redis:"), 1)
            self.assertEqual(output.count("supabase:"), 1)
            self.assertEqual(output.count("n8n:"), 1)
            self.assertIn("redis: http://192.0.2.42:6380 [Healthy]", output)
            self.assertIn("supabase: http://192.0.2.42:54321 [Healthy]", output)
            self.assertIn("n8n: http://192.0.2.42:5678 [Healthy]", output)
            self.assertLess(output.index("feature-b-1"), output.index("Shared dependencies:"))

    def test_dashboard_shared_dependencies_survive_truth_reconcile_after_app_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            worktree = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            worktree.mkdir(parents=True, exist_ok=True)
            redis_container = build_container_name(prefix="envctl-redis", project_root=repo, project_name="Main")
            n8n_container = build_container_name(prefix="envctl-n8n", project_root=repo, project_name="Main")

            class _Runner:
                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                    _ = cwd, env, timeout
                    args = tuple(cmd)
                    if args[:4] == ("docker", "ps", "-a", "--filter"):
                        name_filter = next((str(part) for part in args if str(part).startswith("name=")), "")
                        container_name = name_filter.removeprefix("name=^/").removesuffix("$")
                        if container_name in {redis_container, n8n_container}:
                            return SimpleNamespace(returncode=0, stdout=f"{container_name}\n", stderr="")
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    if args[:2] == ("docker", "port"):
                        container = str(args[2])
                        if container == redis_container:
                            return SimpleNamespace(returncode=0, stdout="6379/tcp -> 0.0.0.0:6485\n", stderr="")
                        if container == n8n_container:
                            return SimpleNamespace(returncode=0, stdout="5678/tcp -> 0.0.0.0:5784\n", stderr="")
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

                def wait_for_port(self, port, timeout):  # noqa: ANN001
                    _ = timeout
                    return port in {6485, 5784}

            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime_dir)),
                env={"NO_COLOR": "1", "ENVCTL_UI_VISUAL_HOST": "192.0.2.42"},
            )
            engine.process_runner = _Runner()  # type: ignore[assignment]
            engine._service_truth_status = lambda service: service.status  # type: ignore[method-assign]

            state = RunState(
                run_id="run-shared-deps-after-restart",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(worktree / "backend"),
                        requested_port=8101,
                        actual_port=8101,
                        pid=111,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(worktree / "frontend"),
                        requested_port=9101,
                        actual_port=9101,
                        pid=222,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": RequirementsResult(
                        project="Main",
                        redis={"enabled": True, "success": True, "final": 6485},
                        n8n={"enabled": True, "success": True, "final": 5784},
                        supabase={"enabled": True, "success": False},
                        failures=["supabase unavailable"],
                    ),
                },
                metadata={
                    "project_roots": {"feature-a-1": str(worktree), "Main": str(repo)},
                    "dashboard_dependency_scope": "shared",
                    "dashboard_shared_dependency_project": "Main",
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Shared dependencies:", output)
            self.assertIn("redis: http://192.0.2.42:6485 [Healthy]", output)
            self.assertIn("n8n: http://192.0.2.42:5784 [Healthy]", output)
            self.assertIn("supabase: n/a [Unhealthy]", output)
            self.assertNotIn("redis: n/a [Unreachable]", output)
            self.assertNotIn("n8n: n/a [Unreachable]", output)

    def test_dashboard_infers_shared_tree_dependencies_for_legacy_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"NO_COLOR": "1", "ENVCTL_UI_VISUAL_HOST": "192.0.2.42"},
            )
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            shared_requirements = RequirementsResult(
                project="",
                redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                supabase={"enabled": True, "runtime_status": "healthy", "final": 54321, "success": True},
                n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
            )
            state = RunState(
                run_id="run-legacy-shared-deps",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8101,
                        actual_port=8101,
                        pid=111,
                        status="running",
                    ),
                    "feature-b-1 Frontend": ServiceRecord(
                        name="feature-b-1 Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9102,
                        actual_port=9102,
                        pid=222,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": shared_requirements,
                    "feature-b-1": shared_requirements,
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo / "trees" / "feature-a" / "1"),
                        "feature-b-1": str(repo / "trees" / "feature-b" / "1"),
                    },
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Shared dependencies:", output)
            self.assertEqual(output.count("redis:"), 1)
            self.assertEqual(output.count("supabase:"), 1)
            self.assertEqual(output.count("n8n:"), 1)
            self.assertIn("redis: http://192.0.2.42:6380 [Healthy]", output)
            self.assertIn("supabase: http://192.0.2.42:54321 [Healthy]", output)
            self.assertIn("n8n: http://192.0.2.42:5678 [Healthy]", output)
            self.assertLess(output.index("feature-b-1"), output.index("Shared dependencies:"))

    def test_dashboard_keeps_isolated_tree_dependencies_under_each_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-isolated-deps",
                mode="trees",
                services={},
                requirements={
                    "feature-a-1": RequirementsResult(
                        project="feature-a-1",
                        redis={"enabled": True, "runtime_status": "healthy", "final": 6381, "success": True},
                    ),
                    "feature-b-1": RequirementsResult(
                        project="feature-b-1",
                        redis={"enabled": True, "runtime_status": "healthy", "final": 6382, "success": True},
                    ),
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo / "trees" / "feature-a" / "1"),
                        "feature-b-1": str(repo / "trees" / "feature-b" / "1"),
                    },
                    "dashboard_dependency_scope": "isolated",
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertNotIn("Shared dependencies:", output)
            self.assertEqual(output.count("redis:"), 2)
            self.assertIn("redis: http://localhost:6381 [Healthy]", output)
            self.assertIn("redis: http://localhost:6382 [Healthy]", output)

    def test_dashboard_visual_host_blank_value_uses_public_host_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"NO_COLOR": "1", "ENVCTL_PUBLIC_HOST": "203.0.113.10", "ENVCTL_UI_VISUAL_HOST": "   "},
            )
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-visual-host-default",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://203.0.113.10:8000", output)
            self.assertNotIn("http://   :8000", output)

    def test_dashboard_visual_host_defaults_to_public_host_from_envctl_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_PUBLIC_HOST=203.0.113.10\n", encoding="utf-8")
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-public-host-envctl",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://203.0.113.10:8000", output)

    def test_dashboard_visual_host_can_be_loaded_from_envctl_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_UI_VISUAL_HOST=198.51.100.7\n", encoding="utf-8")
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-visual-host-envctl",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://198.51.100.7:8000", output)
            self.assertNotIn("Backend: http://localhost:8000", output)
