from __future__ import annotations

from pathlib import Path

from envctl_engine.debug.debug_utils import file_lock


def test_file_lock_keeps_stable_inode_after_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "stable.lock"

    with file_lock(lock_path, timeout=1.0):
        inode = lock_path.stat().st_ino

    assert lock_path.stat().st_ino == inode
