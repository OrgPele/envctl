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

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.engine_runtime_artifacts import (  # noqa: E402
    print_summary,
    write_artifacts,
    write_shell_prune_report,
)
from envctl_engine.state.models import PortPlan, RunState  # noqa: E402


class EngineRuntimeArtifactsTests(unittest.TestCase):
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
            _write_shell_prune_report=lambda run_dir: None,
        )
        state = RunState(run_id="run-1", mode="main")

        write_artifacts(runtime, state, [SimpleNamespace(name="Main")], errors=["boom"])

        self.assertIs(captured["state"], state)
        self.assertEqual(captured["errors"], ["boom"])
        self.assertEqual(captured["events"], [{"event": "x"}])
        self.assertTrue(callable(captured["runtime_map_builder"]))
        self.assertTrue(callable(captured["write_shell_prune_report"]))

    def test_write_artifacts_writes_pending_shell_prune_payload_before_background_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"
            legacy_root = Path(tmpdir) / "legacy"
            run_dir = runtime_root / "runs" / "run-1"
            runtime_root.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            captured: dict[str, object] = {}

            def save_run(**kwargs):  # noqa: ANN003
                callback = kwargs["write_shell_prune_report"]
                if callable(callback):
                    callback(run_dir)
                captured.update(kwargs)
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

            def fake_start(thread):  # noqa: ANN001
                started_threads.append(thread)

            try:
                threading.Thread.start = fake_start  # type: ignore[assignment]
                write_artifacts(runtime, state, [SimpleNamespace(name="Main")], errors=[])
            finally:
                threading.Thread.start = original_start  # type: ignore[assignment]

            payload = json.loads((runtime_root / "shell_prune_report.json").read_text(encoding="utf-8"))
            self.assertIn("passed", payload)
            self.assertTrue(payload["pending"])
            self.assertEqual(len(started_threads), 1)

    def test_write_shell_prune_report_writes_runtime_and_run_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"
            legacy_root = Path(tmpdir) / "legacy"
            run_dir = Path(tmpdir) / "run"
            runtime_root.mkdir()
            run_dir.mkdir()
            result = SimpleNamespace(
                ledger_path=Path("/tmp/ledger.json"),
                ledger_generated_at="2026-03-06T10:00:00Z",
                ledger_hash="abc123",
                status_counts={"python_complete": 1},
                partial_keep_covered_count=2,
                partial_keep_uncovered_count=0,
                partial_keep_budget_actual=2,
                partial_keep_budget_basis="uncovered",
                intentional_keep_budget_actual=0,
                passed=True,
                errors=[],
                warnings=[],
                missing_python_complete_commands=[],
            )
            runtime = SimpleNamespace(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                config=SimpleNamespace(base_dir=Path(tmpdir)),
                _shell_prune_budget_profile=lambda: (0, 0, 0, "cutover"),
            )

            write_shell_prune_report(runtime, run_dir=run_dir, contract_result=result)

            snapshot = json.loads((runtime_root / "shell_ownership_snapshot.json").read_text(encoding="utf-8"))
            report = json.loads((runtime_root / "shell_prune_report.json").read_text(encoding="utf-8"))
            run_report = json.loads((run_dir / "shell_prune_report.json").read_text(encoding="utf-8"))

        self.assertEqual(snapshot["ledger_hash"], "abc123")
        self.assertTrue(report["passed"])
        self.assertEqual(run_report["snapshot"]["status_counts"], {"python_complete": 1})

    def test_write_shell_prune_report_reuses_cached_payload_when_ledger_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            legacy_root = Path(tmpdir) / "legacy"
            run_dir = Path(tmpdir) / "run"
            ledger_path = repo_root / "contracts" / "envctl-shell-ownership-ledger.json"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_root.mkdir()
            run_dir.mkdir()
            ledger_text = json.dumps({"generated_at": "now", "entries": [], "command_mappings": []}, sort_keys=True)
            ledger_hash = hashlib.sha256(ledger_text.encode("utf-8")).hexdigest()
            ledger_path.write_text(ledger_text, encoding="utf-8")
            snapshot_payload = {
                "ledger_path": str(ledger_path),
                "ledger_generated_at": "2026-03-06T10:00:00Z",
                "ledger_hash": ledger_hash,
                "status_counts": {"python_complete": 1},
                "partial_keep_covered_count": 0,
                "partial_keep_uncovered_count": 0,
                "partial_keep_budget_actual": 0,
                "partial_keep_budget_basis": "uncovered",
                "intentional_keep_budget_actual": 0,
            }
            report_payload = {
                "passed": True,
                "errors": [],
                "warnings": [],
                "missing_python_complete_commands": [],
                "snapshot": snapshot_payload,
            }
            (runtime_root / "shell_ownership_snapshot.json").write_text(json.dumps(snapshot_payload, indent=2, sort_keys=True), encoding="utf-8")
            (runtime_root / "shell_prune_report.json").write_text(json.dumps(report_payload, indent=2, sort_keys=True), encoding="utf-8")
            emitted: list[tuple[str, dict[str, object]]] = []
            runtime = SimpleNamespace(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                config=SimpleNamespace(base_dir=repo_root),
                _shell_prune_budget_profile=lambda: (0, 0, 0, "cutover"),
                _emit=lambda event, **payload: emitted.append((event, payload)),
            )

            write_shell_prune_report(runtime, run_dir=run_dir, contract_result=None)

            run_report = json.loads((run_dir / "shell_prune_report.json").read_text(encoding="utf-8"))
            self.assertTrue(run_report["passed"])
            self.assertTrue(
                any(
                    event == "artifacts.shell_prune_report" and payload.get("used_cached_contract") is True
                    for event, payload in emitted
                )
            )


if __name__ == "__main__":
    unittest.main()
