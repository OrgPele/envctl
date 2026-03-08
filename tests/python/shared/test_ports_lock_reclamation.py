from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shared.ports import PortPlanner


class PortsLockReclamationTests(unittest.TestCase):
    def test_injected_availability_checker_controls_port_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            calls: list[int] = []

            def checker(port: int) -> bool:
                calls.append(port)
                return port == 5433

            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="session-a",
                availability_checker=checker,
            )
            reserved = planner.reserve_next(5432, owner="worker")

            self.assertEqual(reserved, 5433)
            self.assertEqual(calls, [5432, 5433])

    def test_stale_lock_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "5432.lock"
            lock_path.write_text(
                json.dumps(
                    {
                        "owner": "old-worker",
                        "session": "old-session",
                        "pid": 999999,
                        "created_at": "2000-01-01T00:00:00+00:00",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="new-session",
                availability_checker=lambda _port: True,
            )
            reserved = planner.reserve_next(5432, owner="new-worker")

            self.assertEqual(reserved, 5432)
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["owner"], "new-worker")
            self.assertEqual(payload["session"], "new-session")

    def test_stale_lock_reclaim_event_includes_previous_owner_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "5432.lock"
            lock_path.write_text(
                json.dumps(
                    {
                        "owner": "old-worker",
                        "session": "old-session",
                        "pid": 999999,
                        "created_at": "2000-01-01T00:00:00+00:00",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            events: list[tuple[str, dict[str, object]]] = []

            def on_event(name: str, payload: dict[str, object]) -> None:
                events.append((name, payload))

            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="new-session",
                availability_checker=lambda _port: True,
                event_handler=on_event,
            )
            reserved = planner.reserve_next(5432, owner="new-worker")

            self.assertEqual(reserved, 5432)
            reclaim_events = [payload for name, payload in events if name == "port.lock.reclaim"]
            self.assertTrue(reclaim_events)
            latest = reclaim_events[-1]
            self.assertEqual(latest.get("port"), 5432)
            self.assertEqual(latest.get("owner"), "new-worker")
            self.assertEqual(latest.get("reclaimed_owner"), "old-worker")
            self.assertEqual(latest.get("reclaimed_session"), "old-session")
            self.assertEqual(latest.get("reclaimed_pid"), 999999)

    def test_active_pid_lock_is_not_reclaimed_by_age_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "5432.lock"
            lock_path.write_text(
                json.dumps(
                    {
                        "owner": "active-worker",
                        "session": "active-session",
                        "pid": 4242,
                        "created_at": "2000-01-01T00:00:00+00:00",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="new-session",
                availability_checker=lambda _port: True,
                pid_checker=lambda _pid: True,
            )
            reserved = planner.reserve_next(5432, owner="new-worker")

            self.assertEqual(reserved, 5433)
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["owner"], "active-worker")

    def test_reserve_next_skips_host_occupied_ports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            occupied_port = 5520

            def checker(port: int) -> bool:
                return port != occupied_port

            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="session-a",
                availability_checker=checker,
            )
            reserved = planner.reserve_next(occupied_port, owner="worker")

            self.assertEqual(reserved, occupied_port + 1)

    def test_release_session_removes_owned_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="session-a",
                availability_checker=lambda _port: True,
            )
            first = planner.reserve_next(5540, owner="worker-a")
            second = planner.reserve_next(5541, owner="worker-a")
            self.assertTrue((Path(tmpdir) / f"{first}.lock").exists())
            self.assertTrue((Path(tmpdir) / f"{second}.lock").exists())

            planner.release_session()

            self.assertFalse((Path(tmpdir) / f"{first}.lock").exists())
            self.assertFalse((Path(tmpdir) / f"{second}.lock").exists())

    def test_release_session_isolated_to_own_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner_a = PortPlanner(
                lock_dir=tmpdir,
                session_id="session-a",
                availability_checker=lambda _port: True,
            )
            planner_b = PortPlanner(
                lock_dir=tmpdir,
                session_id="session-b",
                availability_checker=lambda _port: True,
            )

            a_port = planner_a.reserve_next(5600, owner="worker-a")
            b_port = planner_b.reserve_next(5601, owner="worker-b")
            planner_a.release_session()

            self.assertFalse((Path(tmpdir) / f"{a_port}.lock").exists())
            self.assertTrue((Path(tmpdir) / f"{b_port}.lock").exists())


if __name__ == "__main__":
    unittest.main()
