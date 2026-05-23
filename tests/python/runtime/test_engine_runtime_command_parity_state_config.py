# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.engine_runtime_command_parity_test_support import *


class EngineRuntimeCommandParityStateConfigTests(EngineRuntimeCommandParityTestCase):

    def test_list_targets_discovers_projects_in_main_mode(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-targets", "--main"], env={}))
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        # In main mode with a .envctl file, should discover at least the main project
        self.assertIn("Main", output)  # Project name is capitalized

    def test_list_targets_discovers_projects_in_trees_mode(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        trees_dir = repo / "trees"
        trees_dir.mkdir(exist_ok=True)
        feature_dir = trees_dir / "feature" / "1"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-targets", "--trees"], env={}))
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        # Should discover the feature/1 worktree
        lines = [line.strip() for line in output.strip().split("\n") if line.strip()]
        self.assertGreater(len(lines), 0, "Should discover at least one project in trees mode")

    def test_list_trees_discovers_projects_in_trees_mode(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        trees_dir = repo / "trees"
        trees_dir.mkdir(exist_ok=True)
        feature_dir = trees_dir / "feature" / "1"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-trees"], env={}))
        self.assertEqual(code, 0)
        lines = [line.strip() for line in buffer.getvalue().strip().split("\n") if line.strip()]
        self.assertGreater(len(lines), 0, "Should discover at least one project via --list-trees")

    def test_list_trees_json_reports_selected_state_presence_and_service_truth(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        runtime_root = Path(tmpdir.name) / "runtime"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        trees_dir = repo / "trees"
        trees_dir.mkdir(exist_ok=True)
        feature_dir = trees_dir / "feature" / "1"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)})
        runtime = PythonEngineRuntime(config, env={})
        runtime.state_repository.save_resume_state(
            state=RunState(
                run_id="run-prev",
                mode="trees",
                services={"feature-1 Backend": ServiceRecord(name="feature-1 Backend", type="backend", cwd=".", status="unknown")},
                requirements={},
                metadata={"repo_scope_id": config.runtime_scope_id, "project_roots": {"feature-1": str(feature_dir)}},
            ),
            emit=lambda *args, **kwargs: None,
            runtime_map_builder=lambda _state: {},
        )

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-trees", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], "trees")
        self.assertGreaterEqual(payload["count"], 1)
        feature = payload["projects"][0]
        self.assertTrue(feature["selected"])
        self.assertTrue(feature["preselected"])
        self.assertTrue(feature["state_present"])
        self.assertFalse(feature["services_running"])
        self.assertFalse(feature["running"])

    def test_show_config_json_prints_effective_payload(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\nBACKEND_DIR=api\nMAIN_STARTUP_ENABLE=false\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-config", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["base_dir"], str(repo.resolve()))
        self.assertEqual(payload["execution_root"], str(repo.resolve()))
        self.assertEqual(payload["effective"]["default_mode"], "trees")
        self.assertEqual(payload["effective"]["directories"]["backend"], "api")
        self.assertEqual(payload["effective"]["profiles"]["main"]["startup_enabled"], False)

    def test_show_config_json_reports_launch_env_inferred_dynamic_dependencies(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / ".envctl").write_text(
            "\n".join(
                [
                    "# >>> envctl managed startup config >>>",
                    "ENVCTL_DEFAULT_MODE=main",
                    "# <<< envctl managed startup config <<<",
                    "",
                    "# >>> envctl backend launch env >>>",
                    "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}",
                    "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}",
                    "# <<< envctl backend launch env <<<",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-config", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())

        self.assertTrue(payload["effective"]["profiles"]["main"]["dependencies"]["postgres"])
        self.assertTrue(payload["effective"]["profiles"]["main"]["dependencies"]["redis"])

    def test_show_config_json_reports_plan_agent_codex_cycles(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-config", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["plan_agent"]["cli"], "codex")
        self.assertEqual(payload["plan_agent"]["codex_cycles"], 2)

    def test_show_config_json_reports_cycles_alias(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                "CYCLES": "3",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-config", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["plan_agent"]["codex_cycles"], 3)

    def test_show_config_json_reports_additional_service_validation_errors_and_metadata(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / ".envctl").write_text(
            "\n".join(
                [
                    "ENVCTL_ADDITIONAL_SERVICES=voice-runtime,worker",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_DIR=voice-runtime",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD=python -m voice_runtime --port {port}",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE=8010",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_DEPENDS_ON=worker",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_CRITICAL=false",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_PUBLIC_URL=https://voice.example.test",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_HEALTH_URL=https://voice.example.test/readyz",
                    "ENVCTL_SERVICE_WORKER_DIR=worker",
                    "ENVCTL_SERVICE_WORKER_START_CMD=python worker.py",
                    "ENVCTL_SERVICE_WORKER_EXPECT_LISTENER=false",
                    "ENVCTL_SERVICE_WORKER_DEPENDS_ON=voice-runtime",
                    "",
                    "# >>> envctl service voice-runtime launch env >>>",
                    "VOICE_PUBLIC=${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL}",
                    "# <<< envctl service voice-runtime launch env <<<",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-config", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertIn("additional service dependency cycle: voice-runtime -> worker -> voice-runtime", payload["additional_service_errors"])
        self.assertTrue(payload["service_dependency_env_section_present"]["voice-runtime"])
        self.assertEqual(payload["service_dependency_env_templates"]["voice-runtime"][0]["name"], "VOICE_PUBLIC")

    def test_show_state_json_includes_runtime_map_for_additional_services(self) -> None:
        runtime = self._runtime()
        state = RunState(
            run_id="run-voice",
            mode="main",
            services={
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/tmp/repo/voice-runtime",
                    pid=123,
                    requested_port=8010,
                    actual_port=8012,
                    status="running",
                    listener_expected=True,
                    project="Main",
                    service_slug="voice-runtime",
                    public_url="https://voice.example.test",
                    health_url="https://voice.example.test/readyz",
                    log_path="/tmp/voice.log",
                )
            },
        )
        runtime.state_repository.save_resume_state(
            state=state,
            emit=runtime._emit,
            runtime_map_builder=engine_runtime_module.build_runtime_map,
        )

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-state", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        service = payload["state"]["services"]["Main Voice Runtime"]
        projected = payload["runtime_map"]["projects"]["Main"]["services"]["voice-runtime"]
        self.assertEqual(service["project"], "Main")
        self.assertEqual(service["service_slug"], "voice-runtime")
        self.assertEqual(projected["url"], "http://localhost:8012")
        self.assertEqual(projected["public_url"], "https://voice.example.test")
        self.assertEqual(projected["health_url"], "https://voice.example.test/readyz")

    def test_runtime_uses_legacy_spacing_strategy_when_requested(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )
        runtime = PythonEngineRuntime(config, env={"ENVCTL_PORT_PREFERRED_STRATEGY": "legacy_spacing"})

        self.assertEqual(runtime.port_planner.preferred_port_strategy, "legacy_spacing")
        plans = runtime.port_planner.plan_project_stack("tree-beta", index=2)
        self.assertEqual(plans["backend"].final, 8040)
        self.assertEqual(plans["frontend"].final, 9040)
        self.assertEqual(plans["db"].final, 5434)

    def test_runtime_uses_session_scoped_main_dependency_ports_by_default(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )

        runtime = PythonEngineRuntime(config, env={})
        plans = runtime.port_planner.plan_project_stack("Main", index=0)

        self.assertEqual(plans["backend"].final, 8000)
        self.assertEqual(plans["frontend"].final, 9000)
        self.assertNotEqual(plans["db"].final, 5432)
        self.assertNotEqual(plans["redis"].final, 6379)
        self.assertEqual(plans["db"].final - 5432, plans["redis"].final - 6379)

    def test_runtime_can_disable_session_scoped_main_dependency_ports(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )

        runtime = PythonEngineRuntime(config, env={"ENVCTL_DYNAMIC_MAIN_DEPENDENCY_PORTS": "false"})
        plans = runtime.port_planner.plan_project_stack("Main", index=0)

        self.assertEqual(plans["db"].final, 5432)
        self.assertEqual(plans["redis"].final, 6379)
        self.assertEqual(plans["n8n"].final, 5678)

    def test_show_config_plain_output_reports_preferred_port_strategy(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )
        runtime = PythonEngineRuntime(config, env={"ENVCTL_PORT_PREFERRED_STRATEGY": "legacy_spacing"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-config"], env={}))
        self.assertEqual(code, 0)
        self.assertIn("preferred_port_strategy: legacy_spacing", buffer.getvalue())
        self.assertIn("main_startup_enabled: True", buffer.getvalue())
        self.assertIn("trees_startup_enabled: True", buffer.getvalue())

    def test_show_state_json_reports_missing_state(self) -> None:
        runtime = self._runtime()

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-state", "--json"], env={}))
        self.assertEqual(code, 1)
        payload = json.loads(buffer.getvalue())
        self.assertFalse(payload["found"])
