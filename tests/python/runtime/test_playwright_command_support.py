from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.playwright_command_support import run_playwright_command
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


class _Runner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[dict[str, object]] = []
        self.returncode = returncode

    def run(self, cmd, *, cwd=None, env=None, timeout=None, stdin=None):  # noqa: ANN001, ANN201
        self.calls.append({"cmd": list(cmd), "cwd": cwd, "env": dict(env or {}), "timeout": timeout, "stdin": stdin})
        return subprocess.CompletedProcess(list(cmd), self.returncode, stdout="ok\n", stderr="")


def _state() -> RunState:
    return RunState(
        run_id="run-pw",
        mode="trees",
        metadata={
            "project_roots": {"feature-a-1": "/repo/trees/feature-a/1"},
            "dependency_mode": "isolated",
            "shared_dependencies": False,
        },
        services={
            "feature-a-1 Frontend": ServiceRecord(
                name="feature-a-1 Frontend",
                type="frontend",
                cwd="/repo/trees/feature-a/1/web",
                project="feature-a-1",
                status="running",
                actual_port=3100,
            )
        },
        requirements={"feature-a-1": RequirementsResult(project="feature-a-1")},
    )


class PlaywrightCommandSupportTests(unittest.TestCase):
    def test_exports_base_url_and_writes_runtime_metadata(self) -> None:
        runner = _Runner()
        artifact_dir = Path("/tmp/envctl-runtime-test/runs/run-pw/test-results")
        runtime = SimpleNamespace(
            env={"ENVCTL_PUBLIC_HOST": "public.example.test", "KEEP": "1"},
            config=SimpleNamespace(raw={}),
            runtime_root=Path("/tmp/envctl-runtime-test"),
            state_repository=SimpleNamespace(test_results_dir_path=lambda run_id: artifact_dir),
            process_runner=runner,
            _try_load_existing_state=lambda **_kwargs: _state(),
            _state_lookup_strict_mode_match=lambda _route: True,
            _emit=lambda *_args, **_kwargs: None,
        )
        route = Route(
            command="playwright",
            mode="trees",
            projects=["feature-a-1"],
            passthrough_args=["python", "-c", "print('x')"],
            flags={"json": True},
        )
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = run_playwright_command(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(runner.calls[0]["cmd"], ["python", "-c", "print('x')"])
        self.assertEqual(runner.calls[0]["cwd"], Path("/repo/trees/feature-a/1"))
        env = runner.calls[0]["env"]
        self.assertEqual(env["QA_BASE_URL"], "http://public.example.test:3100")
        self.assertEqual(env["BASE_URL"], "http://public.example.test:3100")
        self.assertEqual(env["ENVCTL_PROJECT_NAME"], "feature-a-1")
        self.assertEqual(env["ENVCTL_RUN_ID"], "run-pw")
        self.assertEqual(env["ENVCTL_DEPENDENCY_MODE"], "isolated")
        metadata_path = Path(payload["metadata_path"])
        self.assertEqual(metadata_path, artifact_dir / "playwright-runtime-metadata.json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["selected_url"], "http://public.example.test:3100")
        self.assertEqual(metadata["exit_code"], 0)

    def test_requires_project_when_multiple_projects_are_active(self) -> None:
        runner = _Runner()
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            runtime_root=Path("/tmp/envctl-runtime-test"),
            process_runner=runner,
            _try_load_existing_state=lambda **_kwargs: RunState(
                run_id="run-pw-multi",
                mode="trees",
                requirements={
                    "feature-a-1": RequirementsResult(project="feature-a-1"),
                    "feature-b-1": RequirementsResult(project="feature-b-1"),
                },
            ),
            _state_lookup_strict_mode_match=lambda _route: True,
            _emit=lambda *_args, **_kwargs: None,
        )
        route = Route(
            command="playwright",
            mode="trees",
            passthrough_args=["echo", "x"],
            flags={"json": True},
        )
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = run_playwright_command(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "project_required")
        self.assertEqual(payload["active_projects"], ["feature-a-1", "feature-b-1"])
        self.assertEqual(runner.calls, [])

    def test_missing_frontend_fails_without_running_subprocess(self) -> None:
        runner = _Runner()
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            runtime_root=Path("/tmp/envctl-runtime-test"),
            process_runner=runner,
            _try_load_existing_state=lambda **_kwargs: RunState(
                run_id="run-no-frontend",
                mode="trees",
                requirements={"feature-a-1": RequirementsResult(project="feature-a-1")},
            ),
            _state_lookup_strict_mode_match=lambda _route: True,
            _emit=lambda *_args, **_kwargs: None,
        )
        route = Route(
            command="playwright",
            mode="trees",
            projects=["feature-a-1"],
            passthrough_args=["echo", "x"],
            flags={"json": True},
        )
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = run_playwright_command(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "frontend_not_running")
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
