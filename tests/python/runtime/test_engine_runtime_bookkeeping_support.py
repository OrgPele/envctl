from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.runtime.engine_runtime_bookkeeping_support import (
    add_emit_listener,
    consume_project_startup_warnings,
    ensure_legacy_lock_view,
    record_project_startup_warning,
    reset_project_startup_warnings,
)


class EngineRuntimeBookkeepingSupportTests(unittest.TestCase):
    def test_add_emit_listener_returns_idempotent_remover(self) -> None:
        listeners: list[object] = []
        listener = lambda _event, _payload: None  # noqa: E731
        runtime = SimpleNamespace(_emit_listeners=listeners)

        remove = add_emit_listener(runtime, listener)

        self.assertEqual(listeners, [listener])
        remove()
        remove()
        self.assertEqual(listeners, [])

    def test_project_startup_warnings_are_trimmed_keyed_and_consumed_once(self) -> None:
        runtime = SimpleNamespace(_startup_warnings_lock=threading.Lock(), _startup_warnings_by_project={})

        record_project_startup_warning(runtime, " Main ", " first ")
        record_project_startup_warning(runtime, "Main", "")
        record_project_startup_warning(runtime, "", "ignored")

        self.assertEqual(consume_project_startup_warnings(runtime, " Main "), ["first"])
        self.assertEqual(consume_project_startup_warnings(runtime, "Main"), [])

    def test_reset_project_startup_warnings_clears_all_projects(self) -> None:
        runtime = SimpleNamespace(
            _startup_warnings_lock=threading.Lock(),
            _startup_warnings_by_project={"Main": ["warning"]},
        )

        reset_project_startup_warnings(runtime)

        self.assertEqual(runtime._startup_warnings_by_project, {})

    def test_ensure_legacy_lock_view_creates_legacy_link_to_scoped_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = SimpleNamespace(runtime_root=root / "scoped", runtime_legacy_root=root / "legacy")

            ensure_legacy_lock_view(runtime)

            self.assertTrue((runtime.runtime_root / "locks").is_dir())
            legacy_locks = runtime.runtime_legacy_root / "locks"
            self.assertTrue(legacy_locks.exists())
            if legacy_locks.is_symlink():
                self.assertEqual(
                    legacy_locks.resolve(strict=False),
                    (runtime.runtime_root / "locks").resolve(strict=False),
                )


if __name__ == "__main__":
    unittest.main()
