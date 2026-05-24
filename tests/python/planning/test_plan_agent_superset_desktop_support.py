from __future__ import annotations

import sqlite3
import subprocess
import tempfile
from pathlib import Path
import unittest

from envctl_engine.planning.plan_agent import superset_desktop_support as support


class SupersetDesktopSupportTests(unittest.TestCase):
    def test_parse_superset_json_output_accepts_empty_dicts_lists_and_rejects_scalars(self) -> None:
        self.assertEqual(support.parse_superset_json_output(""), {})
        self.assertEqual(support.parse_superset_json_output('{"id": "ws-1"}'), {"id": "ws-1"})
        self.assertEqual(support.parse_superset_json_output('[{"id": "ws-2"}]'), [{"id": "ws-2"}])
        self.assertIsNone(support.parse_superset_json_output('"ws-1"'))
        self.assertIsNone(support.parse_superset_json_output("workspace created"))

    def test_workspace_id_from_superset_payload_checks_workspace_top_level_and_agents(self) -> None:
        self.assertEqual(support.workspace_id_from_superset_payload({"workspace": {"id": "ws-nested"}}), "ws-nested")
        self.assertEqual(support.workspace_id_from_superset_payload({"workspace_id": "ws-top"}), "ws-top")
        self.assertEqual(support.workspace_id_from_superset_payload({"id": "ws-id"}), "ws-id")
        self.assertEqual(support.workspace_id_from_superset_payload({"agents": [{"workspace_id": "ws-agent"}]}), "ws-agent")
        self.assertEqual(support.workspace_id_from_superset_payload([{"workspace": {"id": "ws-list"}}]), "ws-list")
        self.assertIsNone(support.workspace_id_from_superset_payload({"agents": [{}]}))

    def test_workspace_payload_from_superset_payload_returns_nested_workspace_or_first_list_match(self) -> None:
        self.assertEqual(
            support.workspace_payload_from_superset_payload({"workspace": {"id": "ws-1", "projectId": "p1"}}),
            {"id": "ws-1", "projectId": "p1"},
        )
        self.assertEqual(
            support.workspace_payload_from_superset_payload([{}, {"workspace": {"id": "ws-2"}}]),
            {"id": "ws-2"},
        )
        self.assertEqual(support.workspace_payload_from_superset_payload([]), {})

    def test_completed_process_error_text_prefers_stderr_then_stdout_then_exit_code(self) -> None:
        both = subprocess.CompletedProcess(args=["superset"], returncode=1, stdout="out", stderr="err")
        self.assertEqual(support.superset_completed_process_error_text(both), "err\nout")

        stdout = subprocess.CompletedProcess(args=["superset"], returncode=2, stdout="out", stderr="")
        self.assertEqual(support.superset_completed_process_error_text(stdout), "out")

        empty = subprocess.CompletedProcess(args=["superset"], returncode=3, stdout="", stderr="")
        self.assertEqual(support.superset_completed_process_error_text(empty), "exit:3")

    def test_verify_superset_desktop_workspace_reports_ready_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            db_path = home / ".superset" / "local.db"
            db_path.parent.mkdir(parents=True)
            with sqlite3.connect(db_path) as connection:
                connection.execute("create table workspaces (id text primary key)")
                connection.execute("insert into workspaces values ('ws-ready')")
            runtime = _Runtime(env={"HOME": str(home), "ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_VERIFY_TIMEOUT": "0"})

            ready = support.verify_superset_desktop_workspace(
                runtime,
                worktree=_Worktree("feature-a", Path(tmpdir)),
                workspace_id="ws-ready",
            )
            missing = support.verify_superset_desktop_workspace(
                runtime,
                worktree=_Worktree("feature-a", Path(tmpdir)),
                workspace_id="ws-missing",
            )

        self.assertIsNone(ready)
        self.assertIn("could not resolve", str(missing))
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.superset_desktop_workspace_ready")


class _Runtime:
    def __init__(self, *, env: dict[str, str]) -> None:
        self.env = env
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class _Worktree:
    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self.root = root


if __name__ == "__main__":
    unittest.main()
