# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchSupersetDesktopTests(PlanAgentLaunchSupportTestCase):
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


if __name__ == "__main__":
    unittest.main()
