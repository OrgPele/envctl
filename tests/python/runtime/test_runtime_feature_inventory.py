from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import list_supported_commands
from envctl_engine.runtime_feature_inventory import (
    validate_python_runtime_gap_report_payload,
    validate_runtime_feature_matrix_payload,
)


class RuntimeFeatureInventoryTests(unittest.TestCase):
    _MATRIX_PATH = REPO_ROOT / "contracts" / "runtime_feature_matrix.json"
    _GAP_REPORT_PATH = REPO_ROOT / "contracts" / "python_runtime_gap_report.json"
    _PLAN_PATH = REPO_ROOT / "todo" / "plans" / "refactoring" / "python-runtime-gap-closure.md"
    _ARCHIVE_ROOT = REPO_ROOT / "todo" / "done" / "refactoring"

    def test_repository_runtime_feature_matrix_matches_generator(self) -> None:
        payload = json.loads(self._MATRIX_PATH.read_text(encoding="utf-8"))
        generated_at = str(payload["generated_at"])
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "generate_runtime_feature_matrix.py"),
                "--repo",
                str(REPO_ROOT),
                "--stdout",
                "--timestamp",
                generated_at,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        generated = json.loads(completed.stdout)
        self.assertEqual(generated, payload)

    def test_runtime_feature_matrix_contract_is_valid(self) -> None:
        payload = json.loads(self._MATRIX_PATH.read_text(encoding="utf-8"))
        validate_runtime_feature_matrix_payload(payload, repo_root=REPO_ROOT)
        features = payload["features"]
        self.assertGreaterEqual(len(features), len(list_supported_commands()))
        areas = {str(feature["area"]) for feature in features}
        self.assertTrue(
            {
                "launcher",
                "cli",
                "lifecycle",
                "planning",
                "requirements",
                "artifacts",
                "actions",
                "inspection",
                "diagnostics",
            }.issubset(areas)
        )

    def test_runtime_feature_matrix_tracks_all_supported_commands(self) -> None:
        payload = json.loads(self._MATRIX_PATH.read_text(encoding="utf-8"))
        feature_commands = {str(feature["command"]) for feature in payload["features"] if "command" in feature}
        self.assertEqual(feature_commands, set(list_supported_commands()))

    def test_repository_gap_report_matches_generator(self) -> None:
        gap_payload = json.loads(self._GAP_REPORT_PATH.read_text(encoding="utf-8"))
        generated_at = str(gap_payload["generated_at"])
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "generate_python_runtime_gap_report.py"),
                "--repo",
                str(REPO_ROOT),
                "--stdout",
                "--timestamp",
                generated_at,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        generated = json.loads(completed.stdout)
        self.assertEqual(generated, gap_payload)

    def test_gap_report_contract_is_valid(self) -> None:
        matrix_payload = json.loads(self._MATRIX_PATH.read_text(encoding="utf-8"))
        gap_payload = json.loads(self._GAP_REPORT_PATH.read_text(encoding="utf-8"))
        validate_runtime_feature_matrix_payload(matrix_payload, repo_root=REPO_ROOT)
        validate_python_runtime_gap_report_payload(gap_payload, matrix_payload=matrix_payload)
        matrix_ids = {str(feature["id"]) for feature in matrix_payload["features"]}
        gap_ids = {str(gap["feature_id"]) for gap in gap_payload["gaps"]}
        self.assertTrue(gap_ids.issubset(matrix_ids))
        verified_ids = {
            str(feature["id"])
            for feature in matrix_payload["features"]
            if str(feature["parity_status"]) == "verified_python"
        }
        self.assertTrue(gap_ids.isdisjoint(verified_ids))

    def test_gap_report_has_no_remaining_high_or_medium_work(self) -> None:
        payload = json.loads(self._GAP_REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["gap_count"], 0)
        self.assertEqual(payload["summary"]["high_or_medium_gap_count"], 0)
        self.assertEqual(payload["gaps"], [])
        self.assertNotIn("shell_retirement_blockers", payload)

    def test_repository_gap_plan_matches_generator(self) -> None:
        expected = self._PLAN_PATH.read_text(encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "generate_python_runtime_gap_plan.py"),
                "--repo",
                str(REPO_ROOT),
                "--stdout",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout, expected)

    def test_gap_plan_contains_all_waves(self) -> None:
        rendered = self._PLAN_PATH.read_text(encoding="utf-8")
        for wave in ("Wave A", "Wave B", "Wave C", "Wave D", "Wave E"):
            self.assertIn(f"### {wave}", rendered)
            self.assertIn("No currently reported gaps in this wave.", rendered)

    def test_stale_shell_retirement_refactoring_plans_are_archived(self) -> None:
        active_root = REPO_ROOT / "todo" / "plans" / "refactoring"
        for relative in (
            "envctl-bash-deletion-ledger-and-prune-plan.md",
            "envctl-python-engine-final-100-percent-cutover-plan.md",
            "envctl-python-engine-ideal-state-finalization-plan.md",
            "shell-runtime-retirement.md",
        ):
            self.assertFalse((active_root / relative).exists(), relative)
            self.assertTrue((self._ARCHIVE_ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
