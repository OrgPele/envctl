from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.startup.resume_progress import ResumeProjectSpinnerGroup


class ResumeProgressTests(unittest.TestCase):
    def test_update_project_deduplicates_identical_lines(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        group = ResumeProjectSpinnerGroup(
            projects=["Main"],
            enabled=False,
            policy=type("Policy", (), {"enabled": False, "backend": "rich", "style": "dots"})(),
            emit=lambda event, **payload: events.append((event, payload)),
            env={},
        )

        group.update_project("Main", "[1/1] Starting requirements...")
        group.update_project("Main", "[1/1] Starting requirements...")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "ui.spinner.lifecycle")
        self.assertEqual(events[0][1]["message"], "Main: [1/1] Starting requirements...")


if __name__ == "__main__":
    unittest.main()
