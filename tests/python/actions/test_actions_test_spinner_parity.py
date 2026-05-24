from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    parse_route,
)


class ActionsTestSpinnerParityTests(_ActionsParityTestCase):
    def test_test_action_uses_suite_spinner_group_and_suppresses_single_line_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            class _Policy:
                enabled = True
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = ""
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.sys.stderr",
                    new=SimpleNamespace(isatty=lambda: True),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(any(event.startswith("running:") for event in suite_events), msg=suite_events)
            self.assertTrue(any(event.startswith("done:") for event in suite_events), msg=suite_events)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertFalse(
                any(message.startswith("Tests progress: running ") for message in status_messages), msg=status_messages
            )

    def test_parallel_suite_spinner_group_receives_live_progress_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            class _Policy:
                enabled = True
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = ""
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_progress(self, execution, *, status_text: str) -> None:  # noqa: ANN001
                    suite_events.append(f"progress:{int(getattr(execution, 'index', 0))}:{status_text}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            class _ProgressRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = SimpleNamespace(
                        counts_detected=True,
                        passed=0,
                        failed=0,
                        skipped=0,
                        errors=0,
                        total=0,
                    )

                def run_tests(self, command, *, cwd=None, env=None, timeout=None, progress_callback=None):  # noqa: ANN001
                    _ = cwd, env, timeout
                    rendered = " ".join(str(part) for part in command)
                    if "pytest" in rendered:
                        self.last_result = SimpleNamespace(
                            counts_detected=True,
                            passed=3,
                            failed=0,
                            skipped=0,
                            errors=0,
                            total=3,
                        )
                        if callable(progress_callback):
                            progress_callback(1, 3)
                            progress_callback(3, 3)
                    else:
                        self.last_result = SimpleNamespace(
                            counts_detected=True,
                            passed=5,
                            failed=1,
                            skipped=0,
                            errors=0,
                            total=6,
                            failed_tests=["src/foo.test.ts::bar"],
                        )
                        if callable(progress_callback):
                            progress_callback(-1, 6)
                            progress_callback(2, 0)
                            progress_callback(6, 6)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _ProgressRunner),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(
                any(event == "progress:1:1/3 complete • 1 passed, 0 failed" for event in suite_events), msg=suite_events
            )
            self.assertTrue(
                any(event == "progress:1:3/3 complete • 3 passed, 0 failed" for event in suite_events), msg=suite_events
            )
            self.assertTrue(any(event == "progress:2:6 discovered" for event in suite_events), msg=suite_events)
            self.assertTrue(
                any(event == "progress:2:2 complete • 1 passed, 1 failed" for event in suite_events), msg=suite_events
            )
            self.assertTrue(
                any(event == "progress:2:6/6 complete • 5 passed, 1 failed" for event in suite_events), msg=suite_events
            )

    def test_interactive_single_suite_uses_rich_suite_spinner_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            class _Policy:
                enabled = True
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = ""
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_progress(self, execution, *, status_text: str) -> None:  # noqa: ANN001
                    suite_events.append(f"progress:{int(getattr(execution, 'index', 0))}:{status_text}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            with (
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "backend=false"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Test execution mode: sequential (1 suites)", rendered)
            self.assertNotIn("Frontend (package test) started", rendered)
            self.assertNotIn("command: ", rendered)
            self.assertNotIn("cwd: ", rendered)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(any(event.startswith("running:") for event in suite_events), msg=suite_events)
            self.assertTrue(any(event.startswith("done:") for event in suite_events), msg=suite_events)

    def test_test_action_suite_spinner_group_overrides_non_tty_policy_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            class _Policy:
                enabled = False
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = "non_tty"
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(any(event.startswith("running:") for event in suite_events), msg=suite_events)
            self.assertTrue(any(event.startswith("done:") for event in suite_events), msg=suite_events)
            policy_events = [
                event for event in engine.events if event.get("event") == "test.suite_spinner_group.policy"
            ]
            self.assertTrue(policy_events)
            self.assertTrue(bool(policy_events[-1].get("enabled")))

