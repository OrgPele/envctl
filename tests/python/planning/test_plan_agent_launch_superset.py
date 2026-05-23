# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchSupersetTests(PlanAgentLaunchSupportTestCase):
    def test_superset_alias_selects_superset_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "SUPERSET": "true",
                    "SUPERSET_PROJECT": "proj-1",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config_obj,
                {},
                route=parse_route(["--plan", "feature-a"], env={}),
            )

        self.assertEqual(launch_config.transport, "superset")
        self.assertTrue(launch_config.enabled)
        self.assertEqual(launch_config.superset_project, "proj-1")

    def test_superset_project_alias_alone_selects_superset_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "SUPERSET_PROJECT": "proj-1",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config_obj,
                {},
                route=parse_route(["--plan", "feature-a"], env={}),
            )

        self.assertEqual(launch_config.transport, "superset")
        self.assertTrue(launch_config.enabled)
        self.assertEqual(launch_config.superset_project, "proj-1")

    def test_canonical_superset_project_alone_selects_superset_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT": "proj-1",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config_obj,
                {},
                route=parse_route(["--plan", "feature-a"], env={}),
            )

        self.assertEqual(launch_config.transport, "superset")
        self.assertTrue(launch_config.enabled)
        self.assertEqual(launch_config.superset_project, "proj-1")

    def test_canonical_surface_transport_cmux_wins_over_superset_project_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "cmux",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config_obj,
                {},
                route=parse_route(["--plan", "feature-a"], env={}),
            )

        self.assertEqual(launch_config.transport, "cmux")
        self.assertTrue(launch_config.enabled)
        self.assertEqual(launch_config.superset_project, "proj-1")

    def test_superset_launch_missing_project_without_workspace_skips_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET": "true"})

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "missing_superset_project")
        self.assertEqual(rt.process_runner.calls, [])

    def test_superset_project_launch_uses_public_workspace_create_cli_and_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            worktree.mkdir(parents=True, exist_ok=True)
            host_db = self._superset_host_db(home)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "HOME": str(home),
                    "SUPERSET": "true",
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/superset\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-123"}}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(
                        CreatedPlanWorktree(
                            name="features_envctl_plan_agent_superset_lean_launch_1",
                            root=worktree,
                            plan_file="a.md",
                        ),
                    ),
                )
            create_call = rt.process_runner.calls[1]
            agent_id = create_call[create_call.index("--agent") + 1]
            with sqlite3.connect(host_db) as connection:
                host_agent_row = connection.execute(
                    "select command, args_json, prompt_transport from host_agent_configs where id = ?",
                    (agent_id,),
                ).fetchone()
            launcher_path = Path(json.loads(host_agent_row[1])[0]) if host_agent_row else Path()
            launcher_exists = launcher_path.exists()
            launcher_source = launcher_path.read_text(encoding="utf-8") if launcher_exists else ""

        rendered = buffer.getvalue()
        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].surface_id, "ws-123")
        self.assertIn("features_envctl_plan_agent_superset_lean_launch_1", rendered)
        self.assertIn("ws-123", rendered)
        self.assertEqual(rt.process_runner.calls[0], ["git", "-C", str(worktree), "branch", "--show-current"])
        self.assertEqual(create_call[:7], ["superset", "workspaces", "create", "--local", "--project", "proj-1", "--name"])
        self.assertIn("--branch", create_call)
        self.assertEqual(create_call[create_call.index("--branch") + 1], "feature/superset")
        self.assertIn("--agent", create_call)
        self.assertRegex(agent_id, r"^[0-9a-f-]{36}$")
        self.assertNotEqual(agent_id, "codex")
        self.assertIn("--prompt", create_call)
        prompt = create_call[create_call.index("--prompt") + 1]
        payload = json.loads(prompt)
        self.assertEqual(payload["version"], 1)
        self.assertTrue(payload["goal"].startswith("Implement the envctl plan-agent task for a.md"))
        self.assertIn("Workflow mode: single_prompt.", payload["goal"])
        self.assertIn("Authoritative source of truth", payload["prompt"])
        self.assertEqual(create_call[-1], "--json")
        self.assertEqual(rt.process_runner.calls[2], ["superset", "workspaces", "open", "ws-123"])
        self.assertIsNotNone(host_agent_row)
        self.assertEqual(host_agent_row[0], "python3")
        self.assertEqual(host_agent_row[2], "argv")
        self.assertEqual(launcher_path, worktree / ".envctl-state" / "superset-codex-goal-launcher.py")
        self.assertTrue(launcher_exists)
        self.assertIn('if b"Goal active" in buffer:', launcher_source)
        self.assertIn('f"/goal {goal}"', launcher_source)
        self.assertIn('os.write(master_fd, b"\\r")', launcher_source)
        self.assertIn('os.write(master_fd, b"\\n")', launcher_source)
        self.assertIn("goal_submit_attempts < 6", launcher_source)
        self.assertIn("prompt_submit_attempts < 6", launcher_source)
        self.assertIn("prompt_pasted = True", launcher_source)
        self.assertNotIn("goal_deadline", launcher_source)
        flattened = "\n".join(" ".join(call) for call in rt.process_runner.calls)
        self.assertNotIn("cmux read-screen", flattened)
        self.assertNotIn("cmux send-key", flattened)
        self.assertNotIn("cmux set-buffer", flattened)
        self.assertNotIn("cmux paste-buffer", flattened)
        warnings = self._events(rt, "planning.agent_launch.superset_cycles_unsupported")
        self.assertEqual(len(warnings), 1)
        goal_events = self._events(rt, "planning.agent_launch.codex_goal_launcher_prepared")
        self.assertEqual(len(goal_events), 1)
        self.assertEqual(goal_events[0]["transport"], "superset")

    def test_superset_project_launch_honors_no_goal_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/superset\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-123"}}),
                        stderr="",
                    ),
                ]
            )

            launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--no-goal"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )

        create_call = rt.process_runner.calls[1]
        prompt = create_call[create_call.index("--prompt") + 1]
        self.assertFalse(prompt.startswith("/goal "))
        self.assertEqual(self._events(rt, "planning.agent_launch.codex_goal_launcher_prepared"), [])

    def test_superset_workspace_launch_uses_public_agent_run_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_WORKSPACE": "ws-existing",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-existing"}, "session": {"id": "agent-1"}}),
                        stderr="",
                    )
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

        rendered = buffer.getvalue()
        self.assertEqual(result.status, "launched")
        run_call = rt.process_runner.calls[0]
        self.assertEqual(run_call[:5], ["superset", "agents", "run", "--workspace", "ws-existing"])
        self.assertIn("--agent", run_call)
        self.assertIn("--prompt", run_call)
        self.assertEqual(run_call[-1], "--json")
        self.assertEqual(result.outcomes[0].surface_id, "ws-existing")
        self.assertIn("feature-a-1", rendered)
        self.assertIn("ws-existing", rendered)
        self.assertIn("superset workspaces open ws-existing", rendered)

    def test_superset_project_launch_uses_top_level_workspace_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/top\n", stderr=""),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout=json.dumps({"id": "ws-top"}), stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].surface_id, "ws-top")
        self.assertIn("ws-top", buffer.getvalue())
        self.assertIn("superset workspaces open ws-top", buffer.getvalue())

    def test_superset_project_launch_uses_agents_workspace_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_PROJECT": "proj-1"})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/agents\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"agents": [{"workspace_id": "ws-agent"}]}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].surface_id, "ws-agent")
        self.assertEqual(rt.process_runner.calls[2], ["superset", "workspaces", "open", "ws-agent"])

    def test_superset_success_with_non_json_stdout_reports_missing_workspace_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_PROJECT": "proj-1"})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/non-json\n", stderr=""),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="workspace created", stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertIsNone(result.outcomes[0].surface_id)
        self.assertIn("no workspace id was returned", buffer.getvalue())
        self.assertEqual(len(self._events(rt, "planning.agent_launch.superset_debug_output")), 1)

    def test_superset_project_launch_uses_host_instead_of_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SUPERSET_HOST": "https://superset.example",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/host\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-host"}}),
                        stderr="",
                    ),
                ]
            )

            launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )

        create_call = rt.process_runner.calls[1]
        self.assertIn("--host", create_call)
        self.assertEqual(create_call[create_call.index("--host") + 1], "https://superset.example")
        self.assertNotIn("--local", create_call)

    def test_superset_project_launch_falls_back_to_worktree_name_when_branch_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=1, stdout="", stderr="not a branch"),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-fallback"}}),
                        stderr="",
                    ),
                ]
            )

            launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )

        create_call = rt.process_runner.calls[1]
        self.assertEqual(create_call[create_call.index("--branch") + 1], "feature-a-1")
        fallback_events = self._events(rt, "planning.agent_launch.superset_branch_fallback")
        self.assertEqual(len(fallback_events), 1)
        self.assertEqual(fallback_events[0]["fallback"], "feature-a-1")

    def test_superset_open_failure_emits_event_and_keeps_launch_successful(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_PROJECT": "proj-1"})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/open\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-open"}}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=1, stdout="", stderr="browser failed"),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].status, "launched")
        self.assertIn("browser failed", buffer.getvalue())
        open_failed_events = self._events(rt, "planning.agent_launch.superset_open_failed")
        self.assertEqual(len(open_failed_events), 1)
        self.assertEqual(open_failed_events[0]["reason"], "superset_open_failed")
        self.assertEqual(open_failed_events[0]["workspace_id"], "ws-open")
        self.assertEqual(open_failed_events[0]["error"], "browser failed")

    def test_superset_open_verifies_desktop_workspace_cache_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            db_path = home / ".superset" / "local.db"
            worktree.mkdir(parents=True, exist_ok=True)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db_path) as connection:
                connection.execute("create table workspaces (id text primary key)")
                connection.execute("insert into workspaces (id) values (?)", ("ws-ready",))
            rt = self._runtime(repo, runtime, env={"SUPERSET_PROJECT": "proj-1", "HOME": str(home)})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/open\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-ready"}}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].status, "launched")
        ready_events = self._events(rt, "planning.agent_launch.superset_desktop_workspace_ready")
        self.assertEqual(len(ready_events), 1)
        self.assertEqual(ready_events[0]["workspace_id"], "ws-ready")

    def test_superset_open_bridges_desktop_workspace_cache_from_host_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            superset_dir = home / ".superset"
            local_db = superset_dir / "local.db"
            tanstack_db = superset_dir / "tanstack-db.sqlite"
            host_db = superset_dir / "host" / "host-1" / "host.db"
            worktree.mkdir(parents=True, exist_ok=True)
            local_db.parent.mkdir(parents=True, exist_ok=True)
            host_db.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(local_db) as connection:
                connection.execute(
                    """
                    create table projects (
                        id text primary key,
                        main_repo_path text,
                        name text,
                        color text,
                        tab_order integer,
                        last_opened_at integer,
                        created_at integer,
                        default_branch text,
                        github_owner text,
                        default_app text
                    )
                    """
                )
                connection.execute(
                    """
                    create table worktrees (
                        id text primary key,
                        project_id text,
                        path text,
                        branch text,
                        base_branch text,
                        created_at integer,
                        created_by_superset integer
                    )
                    """
                )
                connection.execute(
                    """
                    create table workspaces (
                        id text primary key,
                        project_id text,
                        worktree_id text,
                        type text,
                        branch text,
                        name text,
                        tab_order integer,
                        created_at integer,
                        updated_at integer,
                        last_opened_at integer,
                        is_unread integer,
                        is_unnamed integer
                    )
                    """
                )
            with sqlite3.connect(tanstack_db) as connection:
                connection.execute(
                    """
                    create table collection_registry (
                        collection_id text primary key,
                        table_name text not null unique,
                        tombstone_table_name text not null unique,
                        schema_version integer not null,
                        updated_at integer not null
                    )
                    """
                )
                connection.execute(
                    """
                    insert into collection_registry
                    (collection_id, table_name, tombstone_table_name, schema_version, updated_at)
                    values ('v2_workspaces-org-1', 'c_workspaces_org_1', 'c_workspaces_org_1_tombstones', 1, 1)
                    """
                )
                connection.execute(
                    "create table c_workspaces_org_1 (key text primary key, value text, metadata text, row_version integer)"
                )
            with sqlite3.connect(host_db) as connection:
                connection.execute(
                    "create table projects (id text primary key, repo_path text, repo_owner text, repo_name text, created_at text)"
                )
                connection.execute(
                    "create table workspaces (id text primary key, worktree_path text, branch text, created_at text)"
                )
                connection.execute(
                    "insert into projects values (?, ?, ?, ?, ?)",
                    ("proj-1", str(repo), "OrgPele", "envctl", "2026-05-20 15:00:00+00"),
                )
                connection.execute(
                    "insert into workspaces values (?, ?, ?, ?)",
                    ("ws-bridged", str(worktree), "feature/open", "2026-05-20 15:01:00+00"),
                )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "HOME": str(home),
                    "ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_RESTART": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/open\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "workspace": {
                                    "id": "ws-bridged",
                                    "projectId": "proj-1",
                                    "hostId": "host-1",
                                    "organizationId": "org-1",
                                    "branch": "feature/open",
                                    "name": "feature-a-1",
                                    "createdByUserId": "user-1",
                                    "createdAt": "2026-05-20 15:01:00+00",
                                    "updatedAt": "2026-05-20 15:01:00+00",
                                }
                            }
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )
            with sqlite3.connect(local_db) as connection:
                local_row = connection.execute(
                    "select project_id, worktree_id, type, branch, name from workspaces where id = 'ws-bridged'"
                ).fetchone()
            with sqlite3.connect(tanstack_db) as connection:
                cache_row = connection.execute(
                    "select value from c_workspaces_org_1 where key = 's:ws-bridged'"
                ).fetchone()

        self.assertEqual(result.status, "launched")
        self.assertEqual(local_row, ("proj-1", "ws-bridged", "worktree", "feature/open", "feature-a-1"))
        self.assertIsNotNone(cache_row)
        cached_payload = json.loads(cache_row[0])
        self.assertEqual(cached_payload["id"], "ws-bridged")
        self.assertEqual(cached_payload["projectId"], "proj-1")
        self.assertEqual(cached_payload["organizationId"], "org-1")
        bridge_events = self._events(rt, "planning.agent_launch.superset_desktop_bridge")
        self.assertEqual(len(bridge_events), 1)
        ready_events = self._events(rt, "planning.agent_launch.superset_desktop_workspace_ready")
        self.assertEqual(len(ready_events), 1)

    def test_superset_open_fails_when_desktop_cache_cannot_resolve_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            db_path = home / ".superset" / "local.db"
            worktree.mkdir(parents=True, exist_ok=True)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db_path) as connection:
                connection.execute("create table workspaces (id text primary key)")
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "HOME": str(home),
                    "ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_VERIFY_TIMEOUT": "0",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/open\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-missing"}}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "launch_failed")
        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertIn("could not resolve", str(result.outcomes[0].reason))
        self.assertIn("could not resolve", buffer.getvalue())
        unavailable_events = self._events(rt, "planning.agent_launch.superset_desktop_workspace_unavailable")
        self.assertEqual(len(unavailable_events), 1)
        self.assertEqual(unavailable_events[0]["workspace_id"], "ws-missing")

    def test_superset_nonzero_exit_returns_failed_outcome_with_error_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_WORKSPACE": "ws-existing"})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=1,
                        stdout="host unavailable",
                        stderr="not logged in",
                    )
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

        rendered = buffer.getvalue()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertIn("not logged in", str(result.outcomes[0].reason))
        self.assertIn("not logged in", rendered)

    def test_superset_review_launch_is_explicitly_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_WORKSPACE": "ws-existing"})

            readiness = launch_support.review_agent_launch_readiness(rt)
            result = launch_support.launch_review_agent_terminal(
                rt,
                repo_root=repo,
                project_name="feature-a-1",
                project_root=repo,
            )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "unsupported_superset_review_tab")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "unsupported_superset_review_tab")
