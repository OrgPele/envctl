# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.lifecycle_parity_test_support import *


class LifecycleStateActionsParityTests(unittest.TestCase):
    def test_state_actions_use_strict_mode_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(run_id="run-trees", mode="trees")

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]

            for command in ("--health", "--errors", "--logs"):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route([command, "--main"], env={}))
                self.assertEqual(code, 1)
                self.assertIn("No previous state found", out.getvalue())

            self.assertEqual(
                seen_calls,
                [
                    ("main", True),
                    ("main", True),
                    ("main", True),
                ],
            )

    def test_dashboard_does_not_fallback_to_cross_mode_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(run_id="run-trees", mode="trees")

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--dashboard", "--main"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("No active run state found.", out.getvalue())
            self.assertEqual(seen_calls, [("main", True)])
