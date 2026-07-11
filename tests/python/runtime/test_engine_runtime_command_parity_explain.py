# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.engine_runtime_command_parity_test_support import *


class EngineRuntimeCommandParityExplainTests(EngineRuntimeCommandParityTestCase):
    def test_explain_startup_json_reports_headless_tree_selection_requirement(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        trees_dir = repo / "trees"
        trees_dir.mkdir(exist_ok=True)
        (trees_dir / "feature" / "1").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_DEFAULT_MODE": "trees",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        with patch.object(runtime, "_can_interactive_tty", return_value=False):
            buffer = StringIO()
            with redirect_stdout(buffer):
                code = runtime.dispatch(parse_route(["--explain-startup", "--trees", "--headless", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["headless"])
        self.assertEqual(payload["selection"]["reason"], "headless_tree_start_requires_explicit_selection")

    def test_explain_startup_json_includes_enabled_additional_services_urls_and_warnings(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "voice-runtime" / "app").mkdir(parents=True, exist_ok=True)
        (repo / "voice-runtime" / "app" / "main.py").write_text("# runtime\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PUBLIC_HOST": "72.61.80.25",
                "ENVCTL_ADDITIONAL_SERVICES": "voice-runtime",
                "ENVCTL_SERVICE_VOICE_RUNTIME_DIR": "voice-runtime",
                "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD": "scripts/envctl/start-voice-runtime.sh {port}",
                "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE": "8014",
                "ENVCTL_SERVICE_VOICE_RUNTIME_HEALTH_URL": "${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL}/readyz",
                "ENVCTL_SERVICE_VOICE_RUNTIME_ENABLE_IF_PATH": "voice-runtime/app/main.py",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["services"]["voice-runtime"], True)
        self.assertEqual(
            payload["additional_service_urls"]["voice-runtime"],
            {
                "port": 8014,
                "public_url": "http://72.61.80.25:8014",
                "public_ws_url": "ws://72.61.80.25:8014",
                "health_url": "http://72.61.80.25:8014/readyz",
            },
        )
        warning = payload["warnings"][0]
        self.assertEqual(warning["service"], "voice-runtime")
        self.assertEqual(warning["reason"], "missing_command_path")
        self.assertIn("scripts/envctl/start-voice-runtime.sh", warning["path"])

    def test_preflight_json_skips_additional_service_when_enable_if_path_is_absent(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_ADDITIONAL_SERVICES": "voice-runtime",
                "ENVCTL_SERVICE_VOICE_RUNTIME_DIR": "voice-runtime",
                "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD": "scripts/envctl/start-voice-runtime.sh {port}",
                "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE": "8014",
                "ENVCTL_SERVICE_VOICE_RUNTIME_ENABLE_IF_PATH": "voice-runtime/app/main.py",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["preflight", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        startup = payload["startup"]
        self.assertEqual(startup["services"]["voice-runtime"], False)
        self.assertNotIn("voice-runtime", startup["additional_service_urls"])
        self.assertEqual(startup["warnings"], [])

    def test_preflight_json_wraps_startup_explanation_in_versioned_contract(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "MAIN_STARTUP_ENABLE": "false",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["preflight", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["contract_version"], "envctl.preflight.v1")
        self.assertEqual(payload["surface"], "preflight")
        self.assertEqual(payload["mode"], "main")
        self.assertEqual(payload["command"], "start")
        self.assertFalse(payload["startup_enabled"])
        self.assertIn("startup", payload)
        self.assertEqual(payload["startup"]["reason"], "config_startup_disabled")

    def test_explain_startup_json_reports_disabled_startup(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "MAIN_STARTUP_ENABLE": "false",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], "main")
        self.assertEqual(payload["startup_enabled"], False)
        self.assertEqual(payload["reason"], "config_startup_disabled")
        self.assertEqual(payload["dependencies"], [])
        self.assertEqual(payload["services"], {"backend": False, "frontend": False})

    def test_explain_startup_json_reports_dashboard_reuse_decision_for_disabled_startup(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        runtime_root = Path(tmpdir.name) / "runtime"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime_root),
                "MAIN_STARTUP_ENABLE": "false",
            }
        )
        runtime = PythonEngineRuntime(config, env={})
        context = runtime._discover_projects(mode="main")[0]
        metadata = startup_support.build_startup_identity_metadata(
            runtime,
            runtime_mode="main",
            project_contexts=[context],
        )
        runtime.state_repository.save_resume_state(
            state=RunState(
                run_id="run-dashboard",
                mode="main",
                services={},
                requirements={},
                metadata={
                    **metadata,
                    "dashboard_runs_disabled": True,
                    "repo_scope_id": config.runtime_scope_id,
                },
            ),
            emit=lambda *args, **kwargs: None,
            runtime_map_builder=lambda _state: {},
        )

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], "main")
        self.assertEqual(payload["run_reuse"]["decision_kind"], "resume_dashboard_exact")
        self.assertEqual(payload["run_reuse"]["reason"], "exact_match")
        self.assertEqual(payload["run_reuse"]["run_id"], "run-dashboard")

    def test_explain_startup_json_preserves_plan_selection_semantics(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_DEFAULT_MODE": "trees",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["command"], "plan")
        self.assertEqual(payload["selection"]["reason"], "no_planning_files")
        self.assertEqual(payload["selection"]["selected_projects"], [])

    def test_explain_startup_json_predicts_plan_worktrees_before_creation(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["selection"]["selected_projects"], ["feature_task-1"])
        self.assertEqual(payload["selection"]["predicted_projects"][0]["action"], "create")
        self.assertTrue(payload["selection"]["predicted_projects"][0]["root"].endswith("trees/feature_task/1"))
        self.assertEqual(payload["run_reuse"]["selected_projects"][0]["name"], "feature_task-1")

    def test_plan_dry_run_previews_without_creating_worktrees(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--plan", "feature/task", "--headless", "--dry-run"], env={}))

        self.assertEqual(code, 0)
        rendered = buffer.getvalue()
        self.assertIn("Dry run: no worktrees, git state, or services were modified.", rendered)
        self.assertIn("feature_task-1: create", rendered)
        self.assertNotIn("Starting project", rendered)
        self.assertFalse((repo / "trees" / "feature_task" / "1").exists())

    def test_plan_dry_run_with_omx_ultragoal_does_not_launch_agent_or_start_services(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_ENABLED": "true",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(
                parse_route(["--plan", "feature/task", "--headless", "--dry-run", "--omx", "--ultragoal"], env={})
            )

        self.assertEqual(code, 0)
        rendered = buffer.getvalue()
        self.assertIn("Dry run: no worktrees, git state, or services were modified.", rendered)
        self.assertNotIn("Plan agent launch", rendered)
        self.assertNotIn("Starting project", rendered)
        self.assertFalse((repo / "trees" / "feature_task" / "1").exists())

    def test_explain_startup_json_reports_plan_agent_launch_state(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
            }
        )
        runtime = PythonEngineRuntime(config, env={"CMUX_WORKSPACE_ID": "workspace:4"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["cli"], "codex")
        self.assertEqual(payload["plan_agent_launch"]["preset"], "implement_task")
        self.assertEqual(payload["plan_agent_launch"]["workflow_mode"], "codex_cycles")
        self.assertEqual(payload["plan_agent_launch"]["codex_cycles"], 2)
        self.assertEqual(payload["plan_agent_launch"]["configured_workspace"], None)
        self.assertEqual(payload["plan_agent_launch"]["workspace_id"], None)
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_codex_cycle_workflow_state(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
            }
        )
        runtime = PythonEngineRuntime(config, env={"CMUX_WORKSPACE_ID": "workspace:4"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["plan_agent_launch"]["workflow_mode"], "codex_cycles")
        self.assertEqual(payload["plan_agent_launch"]["codex_cycles"], 2)
        self.assertIsNone(payload["plan_agent_launch"]["workflow_warning"])

    def test_explain_startup_json_reports_cycles_alias_workflow_state(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                "CYCLES": "3",
            }
        )
        runtime = PythonEngineRuntime(config, env={"CMUX_WORKSPACE_ID": "workspace:4"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["plan_agent_launch"]["workflow_mode"], "codex_cycles")
        self.assertEqual(payload["plan_agent_launch"]["codex_cycles"], 3)
        self.assertIsNone(payload["plan_agent_launch"]["workflow_warning"])

    def test_explain_startup_json_keeps_opencode_on_single_prompt_when_cycles_are_set(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                "ENVCTL_PLAN_AGENT_CLI": "opencode",
                "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
            }
        )
        runtime = PythonEngineRuntime(config, env={"CMUX_WORKSPACE_ID": "workspace:4"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["plan_agent_launch"]["cli"], "opencode")
        self.assertEqual(payload["plan_agent_launch"]["workflow_mode"], "single_prompt")
        self.assertEqual(payload["plan_agent_launch"]["codex_cycles"], 2)

    def test_explain_startup_json_reports_omx_plan_agent_transport(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--omx", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["plan_agent_launch"]["transport"], "omx")
        self.assertEqual(payload["plan_agent_launch"]["cli"], "codex")
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_omx_workflow_modifier(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
            }
        )

        for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
            with self.subTest(token=token):
                runtime = PythonEngineRuntime(config, env={})
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = runtime.dispatch(
                        parse_route(["--explain-startup", "--plan", "feature/task", "--omx", token, "--json"], env={})
                    )

                self.assertEqual(code, 0)
                payload = json.loads(buffer.getvalue())
                self.assertEqual(payload["plan_agent_launch"]["transport"], "omx")
                self.assertEqual(payload["plan_agent_launch"]["omx_workflow"], workflow_name)
                self.assertEqual(payload["plan_agent_launch"]["workflow_mode"], "codex_cycles")
                self.assertEqual(payload["plan_agent_launch"]["codex_cycles"], 2)
                self.assertIsNone(payload["plan_agent_launch"]["workflow_warning"])
                self.assertTrue(payload["plan_agent_launch"]["codex_goal_enable"])

    def test_explain_startup_json_reports_plan_agent_workspace_override(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["preset"], "implement_task")
        self.assertEqual(payload["plan_agent_launch"]["workspace_id"], "workspace:9")
        self.assertEqual(payload["plan_agent_launch"]["configured_workspace"], "workspace:9")
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_cmux_alias_enablement(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "CMUX": "true",
            }
        )
        runtime = PythonEngineRuntime(config, env={"CMUX_WORKSPACE_ID": "workspace:4"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["preset"], "implement_task")
        self.assertEqual(payload["plan_agent_launch"]["workspace_id"], None)
        self.assertEqual(payload["plan_agent_launch"]["configured_workspace"], None)
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_superset_transport_and_project(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "SUPERSET": "true",
                "SUPERSET_PROJECT": "proj-1",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["transport"], "superset")
        self.assertEqual(payload["plan_agent_launch"]["workflow_mode"], "single_prompt")
        self.assertEqual(payload["plan_agent_launch"]["codex_cycles"], 2)
        self.assertEqual(payload["plan_agent_launch"]["superset_project"], "proj-1")
        self.assertIsNone(payload["plan_agent_launch"]["configured_workspace"])
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_superset_transport_for_project_alias_only(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "SUPERSET_PROJECT": "proj-1",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["transport"], "superset")
        self.assertEqual(payload["plan_agent_launch"]["workflow_mode"], "single_prompt")
        self.assertEqual(payload["plan_agent_launch"]["codex_cycles"], 2)
        self.assertEqual(payload["plan_agent_launch"]["superset_project"], "proj-1")
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_superset_transport_for_canonical_project_only(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT": "proj-1",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["transport"], "superset")
        self.assertEqual(payload["plan_agent_launch"]["workflow_mode"], "single_prompt")
        self.assertEqual(payload["plan_agent_launch"]["codex_cycles"], 2)
        self.assertEqual(payload["plan_agent_launch"]["superset_project"], "proj-1")
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_superset_missing_project_reason(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "SUPERSET": "true",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["plan_agent_launch"]["transport"], "superset")
        self.assertEqual(payload["plan_agent_launch"]["reason"], "missing_superset_project")

    def test_explain_startup_json_reports_invalid_surface_transport(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "supersurface",
            }
        )
        runtime = PythonEngineRuntime(config, env={"CMUX_WORKSPACE_ID": "workspace:4"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["plan_agent_launch"]["transport"], "cmux")
        self.assertEqual(payload["plan_agent_launch"]["reason"], "invalid_surface_transport")
