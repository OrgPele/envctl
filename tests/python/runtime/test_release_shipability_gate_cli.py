from __future__ import annotations

from datetime import UTC, datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "release_shipability_gate.py"


class ReleaseShipabilityGateCliTests(unittest.TestCase):
    @staticmethod
    def _fresh_timestamp() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

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

    def _prepare_repo(self, repo: Path, *, blocking_gaps: int = 0) -> None:
        (repo / "python" / "envctl_engine").mkdir(parents=True, exist_ok=True)
        (repo / "python" / "envctl_engine" / "__init__.py").write_text('"""ok"""\n', encoding="utf-8")
        (repo / "tests" / "python").mkdir(parents=True, exist_ok=True)
        (repo / "tests" / "python" / "test_stub.py").write_text("x = 1\n", encoding="utf-8")
        contracts_dir = repo / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        (contracts_dir / "python_engine_parity_manifest.json").write_text(
            json.dumps(
                {
                    "generated_at": self._fresh_timestamp(),
                    "commands": {"doctor": "python_complete"},
                    "modes": {},
                }
            ),
            encoding="utf-8",
        )
        (contracts_dir / "python_runtime_gap_report.json").write_text(
            json.dumps(
                {
                    "generated_at": self._fresh_timestamp().replace("+00:00", "Z"),
                    "summary": {
                        "gap_count": blocking_gaps,
                        "high_or_medium_gap_count": blocking_gaps,
                        "by_severity": {"high": blocking_gaps, "medium": 0, "low": 0},
                    },
                    "gaps": [],
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "add",
                "python/envctl_engine/__init__.py",
                "tests/python/test_stub.py",
                "contracts/python_engine_parity_manifest.json",
                "contracts/python_runtime_gap_report.json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True, text=True)

    def _write_repo_local_python(self, repo: Path, *, exit_code: int = 0) -> None:
        python_bin = repo / ".venv" / "bin" / "python"
        python_bin.parent.mkdir(parents=True, exist_ok=True)
        python_bin.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
        python_bin.chmod(0o755)

    def _write_minimal_pyproject(self, repo: Path) -> None:
        (repo / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[build-system]",
                    'requires = ["setuptools>=77.0.0"]',
                    'build-backend = "setuptools.build_meta"',
                    "",
                    "[project]",
                    'name = "shipability-test"',
                    'version = "0.0.1"',
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def test_release_shipability_script_reports_clean_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            self._write_repo_local_python(repo)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--skip-tests",
                    "--skip-build",
                    "--skip-parity-sync",
                    "--repo",
                    str(repo),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("shipability.passed: true", result.stdout)
        self.assertNotIn("unrecognized arguments", result.stdout)

    def test_release_shipability_script_reports_blocking_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo, blocking_gaps=1)
            self._write_repo_local_python(repo)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--skip-tests",
                    "--skip-build",
                    "--skip-parity-sync",
                    "--repo",
                    str(repo),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertIn("shipability.passed: false", result.stdout)
        self.assertIn("python runtime gap report has blocking gaps: 1", result.stdout)

    def test_release_shipability_script_reports_packaging_command_on_default_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            self._write_repo_local_python(repo)
            self._write_minimal_pyproject(repo)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--skip-tests",
                    "--skip-parity-sync",
                    "--repo",
                    str(repo),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertIn("packaging.command: .venv/bin/python -m build", result.stdout)
        self.assertIn("shipability.passed: true", result.stdout)

    def test_release_shipability_script_reports_validation_lane_command_and_failure_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            self._write_repo_local_python(repo, exit_code=2)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--check-tests",
                    "--skip-build",
                    "--skip-parity-sync",
                    "--repo",
                    str(repo),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertIn("validation.command: .venv/bin/python -m pytest -q", result.stdout)
        self.assertIn("error: validation_lane_failed: .venv/bin/python -m pytest -q (exit 2)", result.stdout)


if __name__ == "__main__":
    unittest.main()
