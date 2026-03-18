from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.engine_runtime_artifacts import (  # noqa: E402
    _runtime_readiness_async_enabled,
    print_summary,
    write_artifacts,
    write_runtime_readiness_report,
)
from envctl_engine.runtime.runtime_readiness import RuntimeReadinessResult  # noqa: E402
from envctl_engine.state.models import PortPlan, RunState  # noqa: E402


class EngineRuntimeArtifactsTests(unittest.TestCase):
    def test_runtime_readiness_async_requires_explicit_opt_in(self) -> None:
        self.assertFalse(_runtime_readiness_async_enabled(SimpleNamespace(env={})))
        self.assertFalse(_runtime_readiness_async_enabled(SimpleNamespace(env={"ENVCTL_DEBUG_UI_MODE": "off"})))
        self.assertFalse(
            _runtime_readiness_async_enabled(
                SimpleNamespace(env={"ENVCTL_ASYNC_RUNTIME_READINESS_REPORT": "false", "ENVCTL_DEBUG_UI_MODE": "off"})
            )
        )
        self.assertTrue(
            _runtime_readiness_async_enabled(
                SimpleNamespace(env={"ENVCTL_ASYNC_RUNTIME_READINESS_REPORT": "true", "ENVCTL_DEBUG_UI_MODE": "off"})
            )
        )

    def test_print_summary_includes_project_ports(self) -> None:
        context = SimpleNamespace(
            name="Main",
            ports={
                "backend": PortPlan(project="Main", requested=8000, assigned=8000, final=8000, source="fixed"),
                "frontend": PortPlan(project="Main", requested=9000, assigned=9000, final=9000, source="fixed"),
                "db": PortPlan(project="Main", requested=5432, assigned=5432, final=5432, source="fixed"),
                "redis": PortPlan(project="Main", requested=6379, assigned=6379, final=6379, source="fixed"),
                "n8n": PortPlan(project="Main", requested=5678, assigned=5678, final=5678, source="fixed"),
            },
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_summary(SimpleNamespace(), RunState(run_id="run-1", mode="main"), [context])

        rendered = buffer.getvalue()
        self.assertIn("envctl Python engine run summary", rendered)
        self.assertIn("- Main: backend=8000 frontend=9000 db=5432 redis=6379 n8n=5678", rendered)

    def test_write_artifacts_forwards_expected_state_repository_payload(self) -> None:
        captured: dict[str, object] = {}

        def save_run(**kwargs):  # noqa: ANN003
            captured.update(kwargs)

        runtime = SimpleNamespace(
            state_repository=SimpleNamespace(save_run=save_run),
            events=[{"event": "x"}],
            _emit=lambda *args, **kwargs: None,
            runtime_root=Path("/tmp/runtime-root"),
            runtime_legacy_root=Path("/tmp/runtime-legacy"),
            config=SimpleNamespace(base_dir=Path("/tmp/repo-root")),
            _write_runtime_readiness_report=lambda run_dir: None,
        )
        state = RunState(run_id="run-1", mode="main")

        write_artifacts(runtime, state, [SimpleNamespace(name="Main")], errors=["boom"])

        self.assertIs(captured["state"], state)
        self.assertEqual(captured["errors"], ["boom"])
        self.assertEqual(captured["events"], [{"event": "x"}])
        self.assertTrue(callable(captured["runtime_map_builder"]))
        self.assertTrue(callable(captured["write_runtime_readiness_report"]))

    def test_write_artifacts_writes_runtime_readiness_report_synchronously_without_explicit_async_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"
            legacy_root = Path(tmpdir) / "legacy"
            run_dir = runtime_root / "runs" / "run-1"
            runtime_root.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            def save_run(**kwargs):  # noqa: ANN003
                callback = kwargs["write_runtime_readiness_report"]
                if callable(callback):
                    callback(run_dir)
                return SimpleNamespace(run_dir=run_dir)

            runtime = SimpleNamespace(
                state_repository=SimpleNamespace(save_run=save_run),
                events=[{"event": "x"}],
                _emit=lambda *args, **kwargs: None,
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                config=SimpleNamespace(base_dir=Path(tmpdir)),
                env={"HOME": tmpdir},
            )
            state = RunState(run_id="run-1", mode="main")

            started_threads: list[threading.Thread] = []
            original_start = threading.Thread.start

            def fake_start(self):  # noqa: ANN001
                started_threads.append(self)

            try:
                threading.Thread.start = fake_start  # type: ignore[assignment]
                write_artifacts(runtime, state, [SimpleNamespace(name="Main")], errors=[])
            finally:
                threading.Thread.start = original_start  # type: ignore[assignment]

            payload = json.loads((runtime_root / "runtime_readiness_report.json").read_text(encoding="utf-8"))
            self.assertIn("passed", payload)
            self.assertNotIn("pending", payload)
            self.assertEqual(started_threads, [])

    def test_write_artifacts_writes_pending_runtime_readiness_payload_before_background_refresh_when_async_opted_in(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"
            legacy_root = Path(tmpdir) / "legacy"
            run_dir = runtime_root / "runs" / "run-1"
            runtime_root.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            def save_run(**kwargs):  # noqa: ANN003
                callback = kwargs["write_runtime_readiness_report"]
                if callable(callback):
                    callback(run_dir)
                return SimpleNamespace(run_dir=run_dir)

            runtime = SimpleNamespace(
                state_repository=SimpleNamespace(save_run=save_run),
                events=[{"event": "x"}],
                _emit=lambda *args, **kwargs: None,
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                config=SimpleNamespace(base_dir=Path(tmpdir)),
                env={"HOME": tmpdir, "ENVCTL_ASYNC_RUNTIME_READINESS_REPORT": "true"},
            )
            state = RunState(run_id="run-1", mode="main")

            started_threads: list[threading.Thread] = []
            original_start = threading.Thread.start

            def fake_start(self):  # noqa: ANN001
                started_threads.append(self)

            try:
                threading.Thread.start = fake_start  # type: ignore[assignment]
                write_artifacts(runtime, state, [SimpleNamespace(name="Main")], errors=[])
            finally:
                threading.Thread.start = original_start  # type: ignore[assignment]

            payload = json.loads((runtime_root / "runtime_readiness_report.json").read_text(encoding="utf-8"))
            self.assertIn("passed", payload)
            self.assertTrue(payload["pending"])
            self.assertEqual(len(started_threads), 1)

    def test_write_runtime_readiness_report_writes_runtime_and_run_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"
            legacy_root = Path(tmpdir) / "legacy"
            run_dir = Path(tmpdir) / "run"
            runtime_root.mkdir()
            run_dir.mkdir()
            result = RuntimeReadinessResult(
                passed=True,
                report_path=Path(tmpdir) / "contracts/python_runtime_gap_report.json",
                report_generated_at="2026-03-06T10:00:00Z",
                report_sha256="gap123",
                parity_manifest_path=Path(tmpdir) / "contracts/python_engine_parity_manifest.json",
                parity_manifest_generated_at="2026-03-06T10:00:00Z",
                parity_manifest_sha256="manifest123",
                blocking_gap_count=0,
                high_gap_count=0,
                medium_gap_count=0,
                low_gap_count=1,
                total_gap_count=1,
                errors=[],
                warnings=[],
            )
            runtime = SimpleNamespace(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                config=SimpleNamespace(base_dir=Path(tmpdir)),
            )

            write_runtime_readiness_report(runtime, run_dir=run_dir, readiness_result=result)

            report = json.loads((runtime_root / "runtime_readiness_report.json").read_text(encoding="utf-8"))
            run_report = json.loads((run_dir / "runtime_readiness_report.json").read_text(encoding="utf-8"))

        self.assertTrue(report["passed"])
        self.assertEqual(run_report["summary"]["blocking_gap_count"], 0)
        self.assertEqual(run_report["gap_report"]["sha256"], "gap123")

    def test_write_runtime_readiness_report_reuses_cached_payload_when_report_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            legacy_root = Path(tmpdir) / "legacy"
            run_dir = Path(tmpdir) / "run"
            gap_report_path = repo_root / "contracts" / "python_runtime_gap_report.json"
            manifest_path = repo_root / "contracts" / "python_engine_parity_manifest.json"
            gap_report_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_root.mkdir()
            run_dir.mkdir()
            report_text = json.dumps({"generated_at": "now", "summary": {"total_gap_count": 0}}, sort_keys=True)
            report_hash = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
            gap_report_path.write_text(report_text, encoding="utf-8")
            manifest_path.write_text(
                json.dumps({"generated_at": "now", "commands": {}, "modes": {}}, sort_keys=True), encoding="utf-8"
            )
            report_payload = {
                "passed": True,
                "errors": [],
                "warnings": [],
                "gap_report": {
                    "path": str(gap_report_path),
                    "generated_at": "now",
                    "sha256": report_hash,
                },
                "parity_manifest": {
                    "path": str(manifest_path),
                    "generated_at": "now",
                    "sha256": "manifest123",
                },
                "summary": {
                    "blocking_gap_count": 0,
                    "high_gap_count": 0,
                    "medium_gap_count": 0,
                    "low_gap_count": 0,
                    "total_gap_count": 0,
                },
            }
            (runtime_root / "runtime_readiness_report.json").write_text(
                json.dumps(report_payload, indent=2, sort_keys=True), encoding="utf-8"
            )
            emitted: list[tuple[str, dict[str, object]]] = []
            runtime = SimpleNamespace(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                config=SimpleNamespace(base_dir=repo_root),
                _emit=lambda event, **payload: emitted.append((event, payload)),
            )

            write_runtime_readiness_report(runtime, run_dir=run_dir, readiness_result=None)

            run_report = json.loads((run_dir / "runtime_readiness_report.json").read_text(encoding="utf-8"))
            self.assertTrue(run_report["passed"])
            self.assertTrue(
                any(
                    event == "artifacts.runtime_readiness_report" and payload.get("used_cached_contract") is True
                    for event, payload in emitted
                )
            )


if __name__ == "__main__":
    unittest.main()
