from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from envctl_engine.planning.plan_agent.constants import _OMX_TMUX_LOCK_STALE_SECONDS
from envctl_engine.planning.plan_agent import omx_lock_support


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _emit(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))


class PlanAgentOmxLockSupportTests(unittest.TestCase):
    def test_cleanup_stale_locks_removes_old_lock_and_emits_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "worktree"
            lock_root = worktree_root / ".omx" / "state" / "tmux-extended-keys"
            fresh_lock = lock_root / "fresh.lock"
            stale_lock = lock_root / "stale.lock"
            fresh_lock.mkdir(parents=True, exist_ok=True)
            stale_lock.mkdir(parents=True, exist_ok=True)
            now = time.time()
            os.utime(stale_lock, (now - _OMX_TMUX_LOCK_STALE_SECONDS - 10.0,) * 2)
            os.utime(fresh_lock, (now - 1.0,) * 2)
            runtime = _Runtime()

            omx_lock_support.cleanup_stale_omx_tmux_locks(runtime, worktree_root=worktree_root)

            self.assertFalse(stale_lock.exists())
            self.assertTrue(fresh_lock.exists())
            self.assertEqual(runtime.events[0][0], ("planning.agent_launch.omx_lock_cleanup",))
            self.assertEqual(runtime.events[0][1]["worktree"], str(worktree_root.resolve()))

    def test_cleanup_checks_selected_omx_root_before_legacy_worktree_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "worktree"
            omx_root = Path(tmpdir) / "selected-omx"
            selected_lock = omx_root / ".omx" / "state" / "tmux-extended-keys" / "old.lock"
            selected_lock.mkdir(parents=True)
            stale_time = time.time() - _OMX_TMUX_LOCK_STALE_SECONDS - 10.0
            os.utime(selected_lock, (stale_time, stale_time))
            runtime = _Runtime()

            omx_lock_support.cleanup_stale_omx_tmux_locks(
                runtime,
                worktree_root=worktree_root,
                omx_root=omx_root,
            )

            self.assertFalse(selected_lock.exists())
            self.assertEqual(len(runtime.events), 1)


if __name__ == "__main__":
    unittest.main()
