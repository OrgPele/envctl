from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route  # noqa: E402
from envctl_engine.runtime.engine_runtime_misc_support import (  # noqa: E402
    batch_mode_requested,
    is_truthy,
    recent_failure_messages,
    requirement_bind_max_retries,
    requirement_enabled,
    route_has_explicit_mode,
    should_enter_post_start_interactive,
    state_compat_mode,
    status_color,
    tokens_set_mode,
)
from envctl_engine.state.models import RunState, ServiceRecord  # noqa: E402
from envctl_engine.state.repository import RuntimeStateRepository  # noqa: E402


class EngineRuntimeMiscSupportTests(unittest.TestCase):
    def test_state_compat_mode_defaults_and_accepts_supported_values(self) -> None:
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={"ENVCTL_STATE_COMPAT_MODE": RuntimeStateRepository.COMPAT_READ_ONLY}),
        )
        self.assertEqual(state_compat_mode(runtime), RuntimeStateRepository.COMPAT_READ_ONLY)
        runtime.config.raw["ENVCTL_STATE_COMPAT_MODE"] = "unknown"
        self.assertEqual(state_compat_mode(runtime), RuntimeStateRepository.COMPAT_READ_WRITE)

    def test_tokens_set_mode_and_route_has_explicit_mode_detect_mode_flags(self) -> None:
        route = parse_route(["start", "--trees"], env={})
        self.assertTrue(tokens_set_mode(["foo", "--trees"]))
        self.assertTrue(route_has_explicit_mode(route, explicit_mode_tokens={"--trees", "--main"}))

    def test_batch_and_interactive_gates_respect_batch_flag(self) -> None:
        runtime = SimpleNamespace(env={}, _can_interactive_tty=lambda: True)
        route = parse_route(["start", "--batch"], env={})

        self.assertTrue(batch_mode_requested(runtime, route))
        self.assertFalse(should_enter_post_start_interactive(runtime, route))

    def test_truthy_and_status_helpers(self) -> None:
        self.assertTrue(is_truthy("yes"))
        self.assertFalse(is_truthy("no"))
        self.assertEqual(status_color("healthy", green="g", yellow="y", red="r"), "g")
        self.assertEqual(status_color("unknown", green="g", yellow="y", red="r"), "y")
        self.assertEqual(status_color("failed", green="g", yellow="y", red="r"), "r")

    def test_recent_failure_messages_deduplicates_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            error_report = root / "error_report.json"
            legacy_root = root / "legacy"
            legacy_root.mkdir()
            error_report.write_text(json.dumps({"errors": ["boom", "boom", "bad"]}), encoding="utf-8")
            (legacy_root / "error_report.json").write_text(json.dumps({"errors": ["legacy"]}), encoding="utf-8")
            runtime = SimpleNamespace(
                _error_report_path=lambda: error_report,
                runtime_legacy_root=legacy_root,
            )

            failures = recent_failure_messages(runtime)

        self.assertEqual(failures, ["boom", "bad", "legacy"])

    def test_requirement_bind_max_retries_has_floor(self) -> None:
        runtime = SimpleNamespace(env={"ENVCTL_REQUIREMENT_BIND_MAX_RETRIES": "0"})
        self.assertEqual(requirement_bind_max_retries(runtime), 1)

    def test_requirement_enabled_respects_main_flags_and_config(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(redis_enable=True, n8n_enable=False),
            _effective_main_requirement_flags=lambda route: {
                "postgres_main_enable": False,
                "redis_main_enable": True,
                "supabase_main_enable": True,
                "n8n_main_enable": False,
            },
        )
        self.assertFalse(requirement_enabled(runtime, "postgres", mode="main"))
        self.assertTrue(requirement_enabled(runtime, "redis", mode="main"))
        self.assertFalse(requirement_enabled(runtime, "n8n", mode="main"))
        self.assertTrue(requirement_enabled(runtime, "supabase", mode="main"))

    def test_print_logs_follow_path_is_not_required_for_basic_log_render(self) -> None:
        from envctl_engine.runtime.engine_runtime_misc_support import print_logs

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "svc.log"
            log_path.write_text("line1\nline2\n", encoding="utf-8")
            runtime = SimpleNamespace(_normalize_log_line=lambda line, no_color=False: line.upper())
            state = RunState(
                run_id="run-1",
                services={
                    "svc": ServiceRecord(
                        name="svc",
                        type="backend",
                        cwd=str(Path(tmpdir)),
                        pid=123,
                        requested_port=8000,
                        actual_port=8000,
                        log_path=str(log_path),
                    )
                },
                requirements={},
                mode="main",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                print_logs(runtime, state, tail=1, no_color=True)

        rendered = out.getvalue()
        self.assertIn("svc: log=", rendered)
        self.assertIn("LINE2", rendered)


if __name__ == "__main__":
    unittest.main()
