from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
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


class _MissingExecutableRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, cmd, *, cwd=None, env=None, timeout=None, stdin=None):  # noqa: ANN001, ANN201
        self.calls.append({"cmd": list(cmd), "cwd": cwd, "env": dict(env or {}), "timeout": timeout, "stdin": stdin})
        raise FileNotFoundError(2, "No such file or directory", str(cmd[0]))


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
    def test_passthrough_help_prints_envctl_playwright_help_without_state_lookup(self) -> None:
        runner = _Runner()
        runtime = SimpleNamespace(
            process_runner=runner,
            _try_load_existing_state=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("state not needed")),
        )
        route = Route(
            command="playwright",
            mode="trees",
            projects=["feature-a-1"],
            passthrough_args=["--help"],
            raw_args=["playwright", "--project", "feature-a-1", "--", "--help"],
            flags={},
        )
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = run_playwright_command(runtime, route)

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("envctl playwright - run a browser-test command", output)
        self.assertIn("envctl playwright --project <name> -- <command>", output)
        self.assertEqual(runner.calls, [])

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


    def test_writes_endpoint_artifact_and_exports_path(self) -> None:
        runner = _Runner()
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "runs" / "run-pw" / "test-results"
            runtime = SimpleNamespace(
                env={"ENVCTL_PUBLIC_HOST": "public.example.test", "KEEP": "1"},
                config=SimpleNamespace(raw={}),
                runtime_root=Path(tmpdir),
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
            endpoint_path = Path(payload["endpoints_path"])
            self.assertEqual(endpoint_path, artifact_dir / "playwright-endpoints.json")
            endpoints = json.loads(endpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(endpoints["project"], "feature-a-1")
            env = runner.calls[0]["env"]
            self.assertEqual(env["ENVCTL_ENDPOINTS_JSON"], str(endpoint_path))
            self.assertEqual(env["ENVCTL_ENDPOINTS_JSON_PATH"], str(endpoint_path))
            metadata = json.loads((artifact_dir / "playwright-runtime-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["endpoints_path"], str(endpoint_path))
        self.assertNotIn("KEEP", metadata)

    def test_missing_passthrough_executable_reports_command_not_found(self) -> None:
        runner = _MissingExecutableRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "runs" / "run-pw" / "test-results"
            runtime = SimpleNamespace(
                env={"ENVCTL_PUBLIC_HOST": "public.example.test"},
                config=SimpleNamespace(raw={}),
                runtime_root=Path(tmpdir),
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
                passthrough_args=["missing-playwright-bin", "--version"],
                flags={"json": True},
            )
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = run_playwright_command(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "command_not_found")
        self.assertEqual(payload["command"], "missing-playwright-bin")
        self.assertEqual(runner.calls[0]["cmd"], ["missing-playwright-bin", "--version"])

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

    def test_invalid_loaded_state_is_reported_as_missing_state(self) -> None:
        runner = _Runner()
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            runtime_root=Path("/tmp/envctl-runtime-test"),
            process_runner=runner,
            _try_load_existing_state=lambda **_kwargs: object(),
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
        self.assertEqual(payload["error"], "state_not_found")
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
