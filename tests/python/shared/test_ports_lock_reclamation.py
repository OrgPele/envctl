from __future__ import annotations

import os
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
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

    def test_concurrent_threads_never_publish_duplicate_reservations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worker_count = 64
            barrier = threading.Barrier(worker_count)

            def reserve(index: int) -> int:
                planner = PortPlanner(
                    lock_dir=tmpdir,
                    session_id=f"session-{index}",
                    availability_checker=lambda _port: True,
                )
                barrier.wait()
                return planner.reserve_next(12000, owner=f"worker-{index}")

            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                reserved = list(executor.map(reserve, range(worker_count)))

            self.assertEqual(len(set(reserved)), worker_count)
            self.assertEqual(len(list(Path(tmpdir).glob("*.lock"))), worker_count)
            PortPlanner(lock_dir=tmpdir, session_id="cleanup").release_all()

    def test_concurrent_stale_reclaim_is_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "13000.lock"
            lock_path.write_text(
                json.dumps({"owner": "dead", "session": "dead", "pid": 99999999, "created_at": 0}),
                encoding="utf-8",
            )
            worker_count = 32
            barrier = threading.Barrier(worker_count)

            def reserve(index: int) -> int:
                planner = PortPlanner(
                    lock_dir=tmpdir,
                    session_id=f"session-{index}",
                    availability_checker=lambda _port: True,
                )
                barrier.wait()
                return planner.reserve_next(13000, owner=f"worker-{index}")

            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                reserved = list(executor.map(reserve, range(worker_count)))

            self.assertEqual(len(set(reserved)), worker_count)
            self.assertEqual(len(list(Path(tmpdir).glob("*.lock"))), worker_count)
            PortPlanner(lock_dir=tmpdir, session_id="cleanup").release_all()

    def test_lock_path_is_linked_only_after_payload_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            observed: dict[str, object] = {}
            real_link = os.link

            def inspected_link(source: str | Path, destination: str | Path) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                observed["destination_preexisted"] = destination_path.exists()
                observed["payload"] = json.loads(source_path.read_text(encoding="utf-8"))
                real_link(source_path, destination_path)

            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="complete-publication",
                availability_checker=lambda _port: True,
            )
            with (
                patch("envctl_engine.shared.ports.os.link", side_effect=inspected_link),
                patch("envctl_engine.shared.ports.fsync_directory") as fsync_directory,
            ):
                reserved = planner.reserve_next(14000, owner="worker")

            self.assertEqual(reserved, 14000)
            self.assertFalse(observed["destination_preexisted"])
            self.assertEqual(observed["payload"], json.loads((Path(tmpdir) / "14000.lock").read_text()))
            self.assertEqual(list((Path(tmpdir) / ".port-guards").glob("*.pending")), [])
            fsync_directory.assert_called_once_with(Path(tmpdir))

    def test_corrupt_lock_gets_a_grace_period_then_becomes_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            now = [1000.0]
            lock_path = Path(tmpdir) / "15000.lock"
            lock_path.write_text("{}", encoding="utf-8")
            os.utime(lock_path, (now[0], now[0]))
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="new",
                availability_checker=lambda _port: True,
                time_provider=lambda: now[0],
                corrupt_lock_grace_seconds=2.0,
            )

            self.assertEqual(planner.reserve_next(15000, owner="new"), 15001)
            planner.release_session()
            now[0] += 3.0
            self.assertEqual(planner.reserve_next(15000, owner="new"), 15000)

    def test_permission_error_means_lock_owner_is_still_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "16000.lock"
            lock_path.write_text(
                json.dumps({"owner": "foreign", "session": "foreign", "pid": 424242, "created_at": 0}),
                encoding="utf-8",
            )
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="new",
                availability_checker=lambda _port: True,
            )

            with patch("envctl_engine.shared.ports.os.kill", side_effect=PermissionError("denied")):
                self.assertEqual(planner.reserve_next(16000, owner="new"), 16001)

    def test_boolean_pid_is_corrupt_data_not_a_live_pid_one_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "16010.lock"
            lock_path.write_text(
                json.dumps({"owner": "broken", "session": "broken", "pid": True, "created_at": False}),
                encoding="utf-8",
            )
            os.utime(lock_path, (0, 0))
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="new",
                availability_checker=lambda _port: True,
                pid_checker=lambda _pid: self.fail("a JSON boolean must not be treated as PID 1"),
                corrupt_lock_grace_seconds=0.0,
            )

            self.assertEqual(planner.reserve_next(16010, owner="new"), 16010)

    def test_failed_pid_probe_preserves_a_foreign_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "16020.lock"
            lock_path.write_text(
                json.dumps({"owner": "foreign", "session": "foreign", "pid": 424242, "created_at": 0}),
                encoding="utf-8",
            )
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="new",
                availability_checker=lambda _port: True,
                pid_checker=lambda _pid: (_ for _ in ()).throw(OSError("probe unavailable")),
            )

            self.assertEqual(planner.reserve_next(16020, owner="new"), 16021)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["owner"], "foreign")

    def test_non_finite_corrupt_timestamp_cannot_pin_a_port_forever(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "16030.lock"
            lock_path.write_text(
                '{"owner":"broken","session":"broken","pid":false,"created_at":"nan"}',
                encoding="utf-8",
            )
            os.utime(lock_path, (0, 0))
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="new",
                availability_checker=lambda _port: True,
                corrupt_lock_grace_seconds=0.0,
            )

            self.assertEqual(planner.reserve_next(16030, owner="new"), 16030)

    def test_normal_release_is_session_qualified_but_release_all_is_explicitly_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            owner = PortPlanner(
                lock_dir=tmpdir,
                session_id="session-a",
                availability_checker=lambda _port: True,
            )
            foreign = PortPlanner(
                lock_dir=tmpdir,
                session_id="session-b",
                availability_checker=lambda _port: True,
            )
            port = owner.reserve_next(17000, owner="Main:backend")

            foreign.release(port, owner="Main:backend")
            self.assertTrue((Path(tmpdir) / f"{port}.lock").exists())
            foreign.release_all()
            self.assertFalse((Path(tmpdir) / f"{port}.lock").exists())

    def test_reap_stale_never_removes_a_live_foreign_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "18000.lock"
            lock_path.write_text(
                json.dumps({"owner": "worker", "session": "old", "pid": os.getpid(), "created_at": 0}),
                encoding="utf-8",
            )
            planner = PortPlanner(lock_dir=tmpdir, session_id="new", availability_checker=lambda _port: True)

            self.assertFalse(planner.reap_stale(18000, owner="worker"))
            self.assertTrue(lock_path.exists())
            lock_path.write_text(
                json.dumps({"owner": "worker", "session": "old", "pid": 99999999, "created_at": 0}),
                encoding="utf-8",
            )
            self.assertTrue(planner.reap_stale(18000, owner="worker"))
            self.assertFalse(lock_path.exists())

    def test_release_owned_requires_exact_owner_and_original_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original = PortPlanner(
                lock_dir=tmpdir,
                session_id="old-session",
                availability_checker=lambda _port: True,
            )
            cleanup = PortPlanner(
                lock_dir=tmpdir,
                session_id="cleanup-session",
                availability_checker=lambda _port: True,
            )
            port = original.reserve_next(19000, owner="Main:backend")

            self.assertFalse(cleanup.release_owned(port, "Other:backend", expected_session="old-session"))
            self.assertTrue((Path(tmpdir) / f"{port}.lock").exists())
            self.assertFalse(cleanup.release_owned(port, "Main:backend", expected_session="cleanup-session"))
            self.assertFalse(cleanup.release_owned(port, "Main:backend", expected_session=""))
            self.assertTrue((Path(tmpdir) / f"{port}.lock").exists())
            self.assertTrue(cleanup.release_owned(port, "Main:backend", expected_session="old-session"))
            self.assertFalse((Path(tmpdir) / f"{port}.lock").exists())

    def test_bulk_stale_reap_preserves_live_and_non_numeric_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "19100.lock").write_text(
                json.dumps({"owner": "dead", "session": "old", "pid": 99999999, "created_at": 0}),
                encoding="utf-8",
            )
            (root / "19101.lock").write_text(
                json.dumps({"owner": "live", "session": "live", "pid": os.getpid(), "created_at": 0}),
                encoding="utf-8",
            )
            (root / "19102.lock").write_text("{}", encoding="utf-8")
            os.utime(root / "19102.lock", (0, 0))
            (root / "not-a-port.lock").write_text("invalid", encoding="utf-8")
            planner = PortPlanner(lock_dir=tmpdir, session_id="cleanup", corrupt_lock_grace_seconds=1.0)

            self.assertEqual(planner.reap_stale_locks(), 2)
            self.assertFalse((root / "19100.lock").exists())
            self.assertTrue((root / "19101.lock").exists())
            self.assertFalse((root / "19102.lock").exists())
            self.assertTrue((root / "not-a-port.lock").exists())

    def test_event_handler_failure_cannot_hide_a_successful_acquire_or_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="event-failure",
                availability_checker=lambda _port: True,
                event_handler=lambda _name, _payload: (_ for _ in ()).throw(RuntimeError("telemetry failed")),
            )

            port = planner.reserve_next(19200, owner="worker")

            self.assertEqual(port, 19200)
            self.assertTrue((Path(tmpdir) / "19200.lock").exists())
            planner.release(port, owner="worker")
            self.assertFalse((Path(tmpdir) / "19200.lock").exists())

    def test_lock_and_guard_directories_reject_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            external = root / "external"
            external.mkdir()
            lock_link = root / "lock-link"
            lock_link.symlink_to(external, target_is_directory=True)

            with self.assertRaisesRegex(OSError, "not a real directory"):
                PortPlanner(lock_dir=str(lock_link))

            lock_dir = root / "locks"
            lock_dir.mkdir()
            (lock_dir / ".port-guards").symlink_to(external, target_is_directory=True)
            planner = PortPlanner(
                lock_dir=str(lock_dir),
                session_id="symlink-guard",
                availability_checker=lambda _port: True,
            )
            with self.assertRaisesRegex(OSError, "not a real directory"):
                planner.reserve_next(19300, owner="worker")
            self.assertEqual(list(external.iterdir()), [])

    def test_guard_artifacts_are_bounded_by_the_fixed_shard_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="bounded",
                availability_checker=lambda _port: True,
            )
            for port in range(20000, 20128):
                self.assertEqual(planner.reserve_next(port, owner=f"worker-{port}"), port)
                planner.release(port, owner=f"worker-{port}")

            guard_dir = Path(tmpdir) / ".port-guards"
            self.assertLessEqual(len(list(guard_dir.glob("*.guard"))), 64)
            self.assertEqual(list(guard_dir.glob("*.pending")), [])
            self.assertEqual(list(Path(tmpdir).glob("*.lock")), [])


if __name__ == "__main__":
    unittest.main()
