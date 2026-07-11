from __future__ import annotations

import errno
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.state.persistence import (
    advisory_file_lock,
    atomic_write_text,
    durable_mkdir,
    require_path_component,
    scavenge_atomic_write_temps,
)


class StatePersistenceTests(unittest.TestCase):
    def test_failed_atomic_replaces_preserve_old_value_and_leave_no_temp_files_or_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "state.json"
            target.write_text("old", encoding="utf-8")
            descriptor_root = Path("/dev/fd")
            descriptors_before = len(list(descriptor_root.iterdir())) if descriptor_root.is_dir() else None

            with patch("envctl_engine.state.persistence.os.replace", side_effect=OSError("forced failure")):
                for _ in range(25):
                    with self.assertRaisesRegex(OSError, "forced failure"):
                        atomic_write_text(target, "new")

            descriptors_after = len(list(descriptor_root.iterdir())) if descriptor_root.is_dir() else None
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(root.glob(".*.tmp")), [])
            if descriptors_before is not None:
                self.assertEqual(descriptors_after, descriptors_before)

    def test_target_local_scavenge_removes_only_exact_regular_atomic_temps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "state.json"
            stale = root / ".state.json.abcdefgh.tmp"
            unrelated_target = root / ".other.json.abcdefgh.tmp"
            malformed_token = root / ".state.json.not-atomic.tmp"
            generic_tmp = root / "notes.tmp"
            external = root / "external"
            symlink_temp = root / ".state.json.ijklmnop.tmp"
            for path in (stale, unrelated_target, malformed_token, generic_tmp):
                path.write_text(path.name, encoding="utf-8")
            external.write_text("sentinel", encoding="utf-8")
            symlink_temp.symlink_to(external)

            removed = scavenge_atomic_write_temps(target)

            self.assertEqual(removed, 1)
            self.assertFalse(stale.exists())
            self.assertTrue(unrelated_target.is_file())
            self.assertTrue(malformed_token.is_file())
            self.assertTrue(generic_tmp.is_file())
            self.assertTrue(symlink_temp.is_symlink())
            self.assertEqual(external.read_text(encoding="utf-8"), "sentinel")

    def test_target_local_scavenge_rejects_symlink_parent_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            external = root / "external"
            external.mkdir()
            stale = external / ".state.json.abcdefgh.tmp"
            stale.write_text("sentinel", encoding="utf-8")
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(external, target_is_directory=True)

            with self.assertRaises(OSError):
                scavenge_atomic_write_temps(linked_parent / "state.json")

            self.assertEqual(stale.read_text(encoding="utf-8"), "sentinel")

    def test_path_component_validation_accepts_safe_names_and_rejects_traversal(self) -> None:
        self.assertEqual(require_path_component("run-2026_07.11", label="run_id"), "run-2026_07.11")
        for value in ("", " ", ".", "..", "../run", "nested/run", "nested\\run", "/tmp/run", "bad\0id"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "path component"):
                    require_path_component(value, label="run_id")

    def test_lock_descriptor_is_closed_if_stream_construction_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "state.lock"
            opened_descriptors: list[int] = []
            closed_descriptors: list[int] = []
            real_open = os.open
            real_close = os.close

            def tracked_open(*args: object, **kwargs: object) -> int:
                descriptor = real_open(*args, **kwargs)  # type: ignore[arg-type]
                opened_descriptors.append(descriptor)
                return descriptor

            def tracked_close(descriptor: int) -> None:
                closed_descriptors.append(descriptor)
                real_close(descriptor)

            with (
                patch("envctl_engine.state.persistence.os.open", side_effect=tracked_open),
                patch("envctl_engine.state.persistence.os.fdopen", side_effect=OSError("fdopen failed")),
                patch("envctl_engine.state.persistence.os.close", side_effect=tracked_close),
            ):
                with self.assertRaisesRegex(OSError, "fdopen failed"):
                    with advisory_file_lock(lock_path, exclusive=True):
                        self.fail("lock acquisition unexpectedly succeeded")

            self.assertEqual(len(opened_descriptors), 1)
            self.assertEqual(closed_descriptors, opened_descriptors)

    def test_lock_rejects_symlink_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "external-target"
            target.write_text("sentinel", encoding="utf-8")
            lock_path = root / "state.lock"
            lock_path.symlink_to(target)

            with self.assertRaises(OSError):
                with advisory_file_lock(lock_path, exclusive=True):
                    self.fail("symlink lock unexpectedly succeeded")

            self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")

    def test_lock_timeout_does_not_leak_or_enter_critical_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "state.lock"
            holder_entered = threading.Event()
            release_holder = threading.Event()

            def hold_lock() -> None:
                with advisory_file_lock(lock_path, exclusive=True):
                    holder_entered.set()
                    release_holder.wait(timeout=2)

            holder = threading.Thread(target=hold_lock)
            holder.start()
            self.assertTrue(holder_entered.wait(timeout=1))
            try:
                with self.assertRaisesRegex(TimeoutError, "Timed out acquiring lock"):
                    with advisory_file_lock(lock_path, exclusive=True, timeout_seconds=0.02):
                        self.fail("contended lock unexpectedly succeeded")
            finally:
                release_holder.set()
                holder.join(timeout=1)
            self.assertFalse(holder.is_alive())

    def test_unsupported_directory_fsync_does_not_undo_committed_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "state.json"
            with patch(
                "envctl_engine.state.persistence.os.fsync",
                side_effect=[None, OSError(errno.EINVAL, "directory fsync unsupported")],
            ):
                atomic_write_text(target, "committed")

            self.assertEqual(target.read_text(encoding="utf-8"), "committed")

    def test_durable_mkdir_fsyncs_each_new_directory_and_its_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "runs" / "run-a" / "revisions"
            synced: list[Path] = []

            with patch(
                "envctl_engine.state.persistence.fsync_directory",
                side_effect=lambda path: synced.append(path),
            ):
                durable_mkdir(target)

            self.assertTrue(target.is_dir())
            for directory in (root / "runs", root / "runs" / "run-a", target):
                self.assertIn(directory, synced)
                self.assertIn(directory.parent, synced)


if __name__ == "__main__":
    unittest.main()
