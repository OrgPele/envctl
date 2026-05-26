from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.runtime.startup_inspection_support import (
    build_preflight_payload,
    build_startup_explanation_payload,
    print_preflight,
    print_startup_explanation,
    startup_route_for_explanation,
)


class StartupInspectionSupportTests(unittest.TestCase):
    def _runtime(self, raw: dict[str, str] | None = None) -> PythonEngineRuntime:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                **(raw or {}),
            }
        )
        return PythonEngineRuntime(config, env={})

    def test_startup_route_for_explanation_strips_inspection_surface_flags(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={})

        startup_route = startup_route_for_explanation(runtime, route)

        self.assertEqual(startup_route.command, "plan")
        self.assertEqual(startup_route.passthrough_args, ["feature/task"])
        self.assertNotIn("--explain-startup", startup_route.raw_args)

    def test_build_payload_reports_disabled_startup_without_enabled_dependencies(self) -> None:
        runtime = self._runtime({"MAIN_STARTUP_ENABLE": "false"})
        route = parse_route(["--explain-startup", "--json"], env={})

        payload = build_startup_explanation_payload(runtime, route)

        self.assertEqual(payload["mode"], "main")
        self.assertFalse(payload["startup_enabled"])
        self.assertEqual(payload["reason"], "config_startup_disabled")
        self.assertEqual(payload["dependencies"], [])

    def test_preflight_payload_wraps_startup_contract(self) -> None:
        runtime = self._runtime({"MAIN_STARTUP_ENABLE": "false"})
        route = parse_route(["preflight", "--json"], env={})

        payload = build_preflight_payload(runtime, route)

        self.assertEqual(payload["contract_version"], "envctl.preflight.v1")
        self.assertEqual(payload["surface"], "preflight")
        self.assertEqual(payload["mode"], "main")
        self.assertEqual(payload["command"], "start")
        self.assertFalse(payload["selection_required"])
        self.assertEqual(payload["startup"]["reason"], "config_startup_disabled")

    def test_print_functions_emit_json_contracts(self) -> None:
        runtime = self._runtime({"MAIN_STARTUP_ENABLE": "false"})

        explain_stdout = StringIO()
        with redirect_stdout(explain_stdout):
            explain_code = print_startup_explanation(
                runtime,
                parse_route(["--explain-startup", "--json"], env={}),
                json_output=True,
            )
        self.assertEqual(explain_code, 0)
        self.assertEqual(json.loads(explain_stdout.getvalue())["reason"], "config_startup_disabled")

        preflight_stdout = StringIO()
        with redirect_stdout(preflight_stdout):
            preflight_code = print_preflight(runtime, parse_route(["preflight", "--json"], env={}), json_output=True)
        self.assertEqual(preflight_code, 0)
        self.assertEqual(json.loads(preflight_stdout.getvalue())["contract_version"], "envctl.preflight.v1")


if __name__ == "__main__":
    unittest.main()
