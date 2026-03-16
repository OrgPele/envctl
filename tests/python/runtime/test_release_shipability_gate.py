from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.shell.release_gate import evaluate_shipability


class ReleaseShipabilityGateTests(unittest.TestCase):
    _PARITY_MANIFEST_PATH = "contracts/python_engine_parity_manifest.json"
    _GAP_REPORT_PATH = "contracts/python_runtime_gap_report.json"

    @staticmethod
    def _fresh_manifest_timestamp(*, aware: bool = False) -> str:
        now = datetime.now(UTC).replace(microsecond=0)
        if aware:
            return now.isoformat()
        return now.replace(tzinfo=None).isoformat()

    def _init_repo(self, root: Path) -> None:
        subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Test"], check=True, capture_output=True, text=True
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
            text=True,
        )

    def _commit_paths(self, repo: Path, *paths: str, message: str = "init") -> None:
        subprocess.run(["git", "-C", str(repo), "add", *paths], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True, text=True)

    def _write_required_engine_init(self, repo: Path) -> None:
        required_dir = repo / "python" / "envctl_engine"
        required_dir.mkdir(parents=True, exist_ok=True)
        (required_dir / "__init__.py").write_text('"""ok"""\n', encoding="utf-8")

    def _write_required_test_files(self, repo: Path) -> None:
        (repo / "tests" / "python").mkdir(parents=True, exist_ok=True)
        (repo / "tests" / "python" / "test_stub.py").write_text("x = 1\n", encoding="utf-8")

    def _write_parity_manifest(self, repo: Path, *, complete: bool = True) -> None:
        parity_manifest = repo / self._PARITY_MANIFEST_PATH
        parity_manifest.parent.mkdir(parents=True, exist_ok=True)
        parity_manifest.write_text(
            json.dumps(
                {
                    "generated_at": self._fresh_manifest_timestamp(),
                    "commands": {"doctor": "python_complete" if complete else "python_partial"},
                    "modes": {},
                }
            ),
            encoding="utf-8",
        )

    def _write_gap_report(self, repo: Path, *, high: int = 0, medium: int = 0, low: int = 0) -> None:
        gap_report = repo / self._GAP_REPORT_PATH
        gap_report.parent.mkdir(parents=True, exist_ok=True)
        total = high + medium + low
        gap_report.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-09T00:00:00Z",
                    "summary": {
                        "gap_count": total,
                        "high_or_medium_gap_count": high + medium,
                        "by_severity": {
                            "high": high,
                            "medium": medium,
                            "low": low,
                        },
                    },
                    "gaps": [],
                }
            ),
            encoding="utf-8",
        )

    def _prepare_repo(
        self, repo: Path, *, complete_manifest: bool = True, high: int = 0, medium: int = 0, low: int = 0
    ) -> None:
        self._write_required_engine_init(repo)
        self._write_required_test_files(repo)
        self._write_parity_manifest(repo, complete=complete_manifest)
        self._write_gap_report(repo, high=high, medium=medium, low=low)
        self._commit_paths(
            repo,
            "python/envctl_engine/__init__.py",
            "tests/python/test_stub.py",
            self._PARITY_MANIFEST_PATH,
            self._GAP_REPORT_PATH,
        )

    def test_gate_passes_when_required_paths_and_runtime_readiness_are_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)

            result = evaluate_shipability(
                repo_root=repo,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_runtime_readiness_contract=True,
            )

            self.assertTrue(result.passed)
            self.assertEqual(result.errors, [])

    def test_gate_fails_when_runtime_gap_report_has_blocking_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo, high=1)

            result = evaluate_shipability(
                repo_root=repo,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_runtime_readiness_contract=True,
            )

            self.assertFalse(result.passed)
            self.assertTrue(any("blocking gaps" in error for error in result.errors))

    def test_gate_fails_when_gap_report_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            (repo / self._GAP_REPORT_PATH).unlink()

            result = evaluate_shipability(
                repo_root=repo,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_runtime_readiness_contract=True,
            )

            self.assertFalse(result.passed)
            self.assertTrue(any("runtime gap report missing" in error for error in result.errors))

    def test_gate_fails_when_manifest_is_not_python_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo, complete_manifest=False)

            result = evaluate_shipability(
                repo_root=repo,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_runtime_readiness_contract=True,
            )

            self.assertFalse(result.passed)
            self.assertTrue(any("parity manifest is not fully python_complete" in error for error in result.errors))

    def test_release_shipability_script_enforces_runtime_readiness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo, high=1)
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from scripts import release_shipability_gate

            code = release_shipability_gate.main(["--repo", str(repo), "--skip-parity-sync"])

            self.assertEqual(code, 1)

    def test_gate_accepts_timezone_aware_manifest_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            manifest = repo / self._PARITY_MANIFEST_PATH
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["generated_at"] = self._fresh_manifest_timestamp(aware=True)
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self._commit_paths(repo, self._PARITY_MANIFEST_PATH, message="update manifest timestamp")

            result = evaluate_shipability(
                repo_root=repo,
                check_tests=False,
                enforce_parity_sync=True,
                enforce_runtime_readiness_contract=True,
                enforce_documented_flag_parity=False,
            )

            self.assertTrue(result.passed, msg=result.errors)

    def test_gate_ignores_launcher_only_repo_flag_in_docs_parity_check(self) -> None:
        result = evaluate_shipability(
            repo_root=REPO_ROOT,
            check_tests=False,
            enforce_parity_sync=False,
            enforce_runtime_readiness_contract=False,
            enforce_documented_flag_parity=True,
        )

        self.assertFalse(any("--repo" in error for error in result.errors), msg=result.errors)


if __name__ == "__main__":
    unittest.main()
