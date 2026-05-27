from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from envctl_engine.actions.action_ship_failure_logs import (
    classify_failure_log,
    failed_checks_with_log_excerpts,
    failure_log_excerpt,
)


def test_ship_failure_log_excerpt_starts_at_failure_section_and_strips_runner_prefixes() -> None:
    excerpt, truncated = failure_log_excerpt(
        "pytest\tRun pytest\t2026-05-25T20:00:00Z setup line\n"
        "pytest\tRun pytest\t2026-05-25T20:00:01Z ================= FAILURES =================\n"
        "pytest\tRun pytest\t2026-05-25T20:00:02Z FAILED tests/test_demo.py::test_demo - AssertionError\n"
        "pytest\tRun pytest\t2026-05-25T20:00:03Z Error: Process completed with exit code 1.\n"
    )

    assert excerpt == (
        "================= FAILURES =================\n"
        "FAILED tests/test_demo.py::test_demo - AssertionError\n"
        "Error: Process completed with exit code 1."
    )
    assert truncated is True

def test_failed_check_log_enrichment_reports_runner_os_errors(tmp_path: Path) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", "gh-test")

    enriched = failed_checks_with_log_excerpts(
        tmp_path,
        gh_path="gh-test",
        failing_checks=[
            {
                "name": "pytest",
                "workflow": "Tests",
                "state": "FAILURE",
                "link": "https://github.com/acme/repo/actions/runs/123/job/456",
            }
        ],
        run_command=fake_run,
    )

    assert enriched == [
        {
            "name": "pytest",
            "workflow": "Tests",
            "state": "FAILURE",
            "link": "https://github.com/acme/repo/actions/runs/123/job/456",
            "failure_log_error": "[Errno 2] No such file or directory: 'gh-test'",
        }
    ]

def test_failed_check_log_enrichment_reports_empty_log_command_errors(tmp_path: Path) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=2, stdout="", stderr="")

    enriched = failed_checks_with_log_excerpts(
        tmp_path,
        gh_path="gh-test",
        failing_checks=[
            {
                "name": "pytest",
                "workflow": "Tests",
                "state": "FAILURE",
                "link": "https://github.com/acme/repo/actions/runs/123/job/456",
            }
        ],
        run_command=fake_run,
    )

    assert enriched == [
        {
            "name": "pytest",
            "workflow": "Tests",
            "state": "FAILURE",
            "link": "https://github.com/acme/repo/actions/runs/123/job/456",
            "failure_log_error": "GitHub Actions log command failed with exit code 2.",
        }
    ]

def test_failed_check_log_enrichment_bounds_log_fetch_subprocesses(tmp_path: Path) -> None:
    seen_timeout: list[float] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen_timeout.append(cast(float, kwargs["timeout"]))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="FAILED tests/test_demo.py::test_demo\n", stderr="")

    enriched = failed_checks_with_log_excerpts(
        tmp_path,
        gh_path="gh-test",
        failing_checks=[
            {
                "name": "pytest",
                "workflow": "Tests",
                "state": "FAILURE",
                "link": "https://github.com/acme/repo/actions/runs/123/job/456",
            }
        ],
        run_command=fake_run,
    )

    assert enriched[0]["failure_excerpt"] == "FAILED tests/test_demo.py::test_demo"
    assert seen_timeout == [30.0]

def test_classify_failure_log_ignores_checkout_setup_when_test_body_failed() -> None:
    log_text = (
        "pytest\tCheckout repository\t2026-05-25T20:00:00Z ##[group]Run actions/checkout@v6\n"
        "pytest\tRun pytest\t2026-05-25T20:00:01Z ================= FAILURES =================\n"
        "pytest\tRun pytest\t2026-05-25T20:00:02Z FAILED tests/test_demo.py::test_demo - AssertionError\n"
    )

    assert classify_failure_log(log_text) == {}
