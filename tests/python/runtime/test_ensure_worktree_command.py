from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _create_repo(root: Path) -> None:
    (root / ".git").mkdir(parents=True, exist_ok=True)
    _run_git(root, "init")
    _run_git(root, "config", "user.email", "envctl@example.com")
    _run_git(root, "config", "user.name", "envctl")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(root, "add", "README.md")
    _run_git(root, "commit", "-m", "init")


class EnsureWorktreeCommandTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime_root: Path, *, env: dict[str, str] | None = None) -> PythonEngineRuntime:
        resolved_env = dict(env or {})
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime_root),
                **resolved_env,
            }
        )
        return PythonEngineRuntime(config, env=resolved_env)

    def test_ensure_worktree_json_creates_single_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_root = root / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            _create_repo(repo)
            runtime = self._runtime(repo, runtime_root)

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = runtime.dispatch(parse_route(["ensure-worktree", "feature_a", "2", "--json"], env={}))

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["contract_version"], "envctl.ensure_worktree.v1")
            self.assertEqual(payload["surface"], "ensure-worktree")
            self.assertEqual(payload["feature"], "feature_a")
            self.assertEqual(payload["iteration"], "2")
            self.assertEqual(payload["project_name"], "feature_a-2")
            self.assertFalse(payload["runtime_started"])
            self.assertTrue(Path(payload["worktree_root"]).is_dir())

    def test_ensure_worktree_json_reuses_existing_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_root = root / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            _create_repo(repo)
            runtime = self._runtime(repo, runtime_root)

            first = runtime.dispatch(parse_route(["ensure-worktree", "feature_b", "--json"], env={}))
            self.assertEqual(first, 0)

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = runtime.dispatch(parse_route(["ensure-worktree", "feature_b", "--json"], env={}))

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["action"], "reuse")
            self.assertTrue(payload["existed_before"])

    def test_ensure_worktree_rejects_invalid_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_root = root / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            _create_repo(repo)
            runtime = self._runtime(repo, runtime_root)

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = runtime.dispatch(parse_route(["ensure-worktree", "bad/feature", "--json"], env={}))

            self.assertEqual(code, 1)
            payload = json.loads(buffer.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIn("Invalid feature name", payload["error"])


if __name__ == "__main__":
    unittest.main()
