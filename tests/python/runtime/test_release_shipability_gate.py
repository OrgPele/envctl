from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.release_gate import (
    _manifest_freshness_is_valid,
    canonical_packaging_command,
    canonical_validation_command,
    evaluate_shipability,
    ShipabilityResult,
)


class ReleaseShipabilityGateTests(unittest.TestCase):
    _PARITY_MANIFEST_PATH = "contracts/python_engine_parity_manifest.json"
    _GAP_REPORT_PATH = "contracts/python_runtime_gap_report.json"
    _MATRIX_PATH = "contracts/runtime_feature_matrix.json"

    @staticmethod
    def _iso_timestamp(*, days_ago: int = 0, utc_suffix: str = "+00:00") -> str:
        timestamp = (datetime.now(UTC) - timedelta(days=days_ago)).replace(microsecond=0)
        rendered = timestamp.isoformat()
        if utc_suffix == "Z":
            return rendered.replace("+00:00", "Z")
        if utc_suffix == "naive":
            return timestamp.replace(tzinfo=None).isoformat()
        return rendered

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

    def _isolated_git_env(self, tmpdir: str, *, excludes_path: Path | None = None) -> dict[str, str]:
        home = Path(tmpdir) / "home"
        xdg = Path(tmpdir) / "xdg"
        home.mkdir(parents=True, exist_ok=True)
        xdg.mkdir(parents=True, exist_ok=True)
        global_config = Path(tmpdir) / "gitconfig"
        global_config.write_text("", encoding="utf-8")
        env = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg),
            "GIT_CONFIG_GLOBAL": str(global_config),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if excludes_path is not None:
            subprocess.run(
                ["git", "config", "--global", "core.excludesFile", str(excludes_path)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        return env

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

    def _write_parity_manifest(
        self,
        repo: Path,
        *,
        complete: bool = True,
        generated_at: str | None = None,
    ) -> None:
        parity_manifest = repo / self._PARITY_MANIFEST_PATH
        parity_manifest.parent.mkdir(parents=True, exist_ok=True)
        parity_manifest.write_text(
            json.dumps(
                {
                    "generated_at": generated_at or self._iso_timestamp(),
                    "commands": {"doctor": "python_complete" if complete else "python_partial"},
                    "modes": {},
                }
            ),
            encoding="utf-8",
        )

    def _write_runtime_feature_matrix(
        self,
        repo: Path,
        *,
        generated_at: str | None = None,
        features: list[dict[str, object]] | None = None,
    ) -> tuple[str, str]:
        matrix_path = repo / self._MATRIX_PATH
        matrix_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "generated_at": generated_at or self._iso_timestamp(),
            "summary": {"feature_count": len(features or [])},
            "features": list(features or []),
        }
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        matrix_path.write_text(rendered, encoding="utf-8")
        return str(payload["generated_at"]), rendered

    def _write_gap_report(
        self,
        repo: Path,
        *,
        high: int = 0,
        medium: int = 0,
        low: int = 0,
        generated_at: str | None = None,
        matrix_generated_at: str | None = None,
        matrix_sha256: str | None = None,
    ) -> None:
        gap_report = repo / self._GAP_REPORT_PATH
        gap_report.parent.mkdir(parents=True, exist_ok=True)
        total = high + medium + low
        gap_report.write_text(
            json.dumps(
                {
                    "generated_at": generated_at or self._iso_timestamp(utc_suffix="Z"),
                    "matrix_generated_at": matrix_generated_at or "",
                    "matrix_sha256": matrix_sha256 or "",
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
        self,
        repo: Path,
        *,
        complete_manifest: bool = True,
        high: int = 0,
        medium: int = 0,
        low: int = 0,
        manifest_generated_at: str | None = None,
        gap_generated_at: str | None = None,
    ) -> None:
        self._write_required_engine_init(repo)
        self._write_required_test_files(repo)
        self._write_parity_manifest(repo, complete=complete_manifest, generated_at=manifest_generated_at)
        matrix_generated_at, matrix_rendered = self._write_runtime_feature_matrix(repo)
        self._write_gap_report(
            repo,
            high=high,
            medium=medium,
            low=low,
            generated_at=gap_generated_at,
            matrix_generated_at=matrix_generated_at,
            matrix_sha256=hashlib.sha256(matrix_rendered.encode("utf-8")).hexdigest(),
        )
        self._commit_paths(
            repo,
            "python/envctl_engine/__init__.py",
            "tests/python/test_stub.py",
            self._PARITY_MANIFEST_PATH,
            self._GAP_REPORT_PATH,
            self._MATRIX_PATH,
        )

    def _write_repo_local_python(self, repo: Path) -> Path:
        python_bin = repo / ".venv" / "bin" / "python"
        python_bin.parent.mkdir(parents=True, exist_ok=True)
        python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        python_bin.chmod(0o755)
        return python_bin

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
                    'dependencies = ["textual>=0.58"]',
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
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

    def test_gate_fails_when_runtime_feature_matrix_drifts_from_gap_report_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)

            self._write_runtime_feature_matrix(
                repo,
                generated_at="2026-03-10T00:00:00+00:00",
                features=[{"id": "feature-1", "feature": "drift"}],
            )

            result = evaluate_shipability(
                repo_root=repo,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_runtime_readiness_contract=True,
            )

            self.assertFalse(result.passed)
            self.assertTrue(any("runtime feature matrix sha256 mismatch" in error for error in result.errors))

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

    def test_gate_fails_when_runtime_dependency_manifests_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_minimal_pyproject(repo)
            self._write_required_engine_init(repo)
            (repo / "python").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "requirements.txt").write_text("rich>=13.7\n", encoding="utf-8")
            self._write_parity_manifest(repo, complete=True)
            self._commit_paths(
                repo,
                "pyproject.toml",
                "python/envctl_engine/__init__.py",
                "python/requirements.txt",
                self._PARITY_MANIFEST_PATH,
            )

            with (
                patch("envctl_engine.runtime.release_gate._runtime_parity_is_complete", return_value=True),
                patch(
                    "envctl_engine.runtime.release_gate._manifest_freshness_is_valid",
                    return_value=(True, "manifest fresh"),
                ),
                patch(
                    "envctl_engine.runtime.release_gate.evaluate_runtime_readiness",
                    return_value=ShipabilityResult(passed=True, errors=[], warnings=[]),
                ),
            ):
                result = evaluate_shipability(
                    repo_root=repo,
                    required_paths=(),
                    required_scopes=(),
                    check_tests=False,
                    check_packaging=False,
                    enforce_parity_sync=True,
                    enforce_runtime_readiness_contract=False,
                )

            self.assertFalse(result.passed)
            self.assertTrue(any("runtime dependency manifests differ" in error for error in result.errors))

    def test_manifest_freshness_accepts_offset_aware_and_z_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)

            self._write_parity_manifest(repo, generated_at="2026-03-10T14:57:02+00:00")
            valid, message = _manifest_freshness_is_valid(
                repo,
                now=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
            )
            self.assertTrue(valid, msg=message)

            self._write_parity_manifest(repo, generated_at="2026-03-10T14:57:02Z")
            valid, message = _manifest_freshness_is_valid(
                repo,
                now=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
            )
            self.assertTrue(valid, msg=message)

    def test_manifest_freshness_reports_stale_manifests_against_explicit_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)

            self._write_parity_manifest(repo, generated_at="2026-03-01T12:00:00+00:00")
            valid, message = _manifest_freshness_is_valid(
                repo,
                now=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
            )
            self.assertFalse(valid)
            self.assertIn("manifest stale", message)

    def test_gate_treats_repo_flag_as_supported_documented_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            docs_path = repo / "docs" / "reference" / "important-flags.md"
            docs_path.parent.mkdir(parents=True, exist_ok=True)
            docs_path.write_text("| `--repo <path>` | Resolve repo root. |\n", encoding="utf-8")

            result = evaluate_shipability(
                repo_root=repo,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_runtime_readiness_contract=True,
                enforce_documented_flag_parity=True,
            )

            self.assertTrue(result.passed, msg=result.errors)
            self.assertEqual(result.errors, [])

    def test_gate_treats_launcher_version_flag_as_supported_documented_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            docs_path = repo / "docs" / "reference" / "important-flags.md"
            docs_path.parent.mkdir(parents=True, exist_ok=True)
            docs_path.write_text(
                "| `--version` | Print the current envctl package version and exit. |\n",
                encoding="utf-8",
            )

            result = evaluate_shipability(
                repo_root=repo,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_runtime_readiness_contract=True,
                enforce_documented_flag_parity=True,
            )

            self.assertTrue(result.passed, msg=result.errors)
            self.assertEqual(result.errors, [])

    def test_gate_check_tests_uses_canonical_pytest_validation_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            python_bin = self._write_repo_local_python(repo)

            with patch("envctl_engine.runtime.release_gate._run_cmd_capture") as run_cmd:
                run_cmd.return_value = type("Result", (), {"returncode": 0, "output": ""})()
                result = evaluate_shipability(
                    repo_root=repo,
                    check_tests=True,
                    check_packaging=False,
                    enforce_parity_sync=False,
                    enforce_runtime_readiness_contract=True,
                )

        self.assertTrue(result.passed, msg=result.errors)
        self.assertEqual(run_cmd.call_count, 1)
        self.assertEqual(run_cmd.call_args.args[0], repo)
        self.assertEqual(run_cmd.call_args.args[1], canonical_validation_command(repo))
        self.assertEqual(run_cmd.call_args.args[1][0], str(python_bin))

    def test_gate_check_packaging_reports_failed_build_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            self._write_repo_local_python(repo)
            self._write_minimal_pyproject(repo)

            with patch("envctl_engine.runtime.release_gate._run_cmd_capture") as run_cmd:
                run_cmd.return_value = type("Result", (), {"returncode": 2, "output": "build failed"})()
                result = evaluate_shipability(
                    repo_root=repo,
                    check_tests=False,
                    check_packaging=True,
                    enforce_parity_sync=False,
                    enforce_runtime_readiness_contract=True,
                )

        self.assertFalse(result.passed)
        self.assertIn("packaging_build_failed", result.errors[0])
        self.assertIn(".venv/bin/python -m build", result.errors[0])
        self.assertEqual(run_cmd.call_args.args[1], canonical_packaging_command(repo))

    def test_gate_check_packaging_reports_warning_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            self._write_repo_local_python(repo)
            self._write_minimal_pyproject(repo)

            with patch("envctl_engine.runtime.release_gate._run_cmd_capture") as run_cmd:
                run_cmd.return_value = type(
                    "Result",
                    (),
                    {"returncode": 0, "output": "SetuptoolsDeprecationWarning: old config"},
                )()
                result = evaluate_shipability(
                    repo_root=repo,
                    check_tests=False,
                    check_packaging=True,
                    enforce_parity_sync=False,
                    enforce_runtime_readiness_contract=True,
                )

        self.assertFalse(result.passed)
        self.assertIn("packaging_build_warned", result.errors[0])

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

    def test_gate_ignores_envctl_local_artifacts_hidden_by_global_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            excludes_path = Path(tmpdir) / "git" / "ignore"
            excludes_path.parent.mkdir(parents=True, exist_ok=True)
            excludes_path.write_text(".envctl*\nMAIN_TASK.md\nOLD_TASK_*.md\ntrees/\ntrees-*\n", encoding="utf-8")
            env = self._isolated_git_env(tmpdir, excludes_path=excludes_path)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            (repo / "MAIN_TASK.md").write_text("task\n", encoding="utf-8")

            with patch.dict(os.environ, env, clear=True):
                result = evaluate_shipability(
                    repo_root=repo,
                    required_scopes=["."],
                    check_tests=False,
                    enforce_parity_sync=False,
                    enforce_runtime_readiness_contract=True,
                )

            self.assertTrue(result.passed, msg=result.errors)

    def test_gate_still_fails_for_unrelated_untracked_files_with_global_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._prepare_repo(repo)
            excludes_path = Path(tmpdir) / "git" / "ignore"
            excludes_path.parent.mkdir(parents=True, exist_ok=True)
            excludes_path.write_text(".envctl*\nMAIN_TASK.md\nOLD_TASK_*.md\ntrees/\ntrees-*\n", encoding="utf-8")
            env = self._isolated_git_env(tmpdir, excludes_path=excludes_path)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            (repo / "MAIN_TASK.md").write_text("task\n", encoding="utf-8")
            (repo / "notes.tmp").write_text("visible\n", encoding="utf-8")

            with patch.dict(os.environ, env, clear=True):
                result = evaluate_shipability(
                    repo_root=repo,
                    required_scopes=["."],
                    check_tests=False,
                    enforce_parity_sync=False,
                    enforce_runtime_readiness_contract=True,
                )

            self.assertFalse(result.passed)
            self.assertTrue(any("notes.tmp" in error for error in result.errors))

if __name__ == "__main__":
    unittest.main()
