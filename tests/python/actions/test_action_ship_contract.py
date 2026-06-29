from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from envctl_engine.actions.action_ship_contract import (
    ship_action_payload as ship_action_payload_from_contract,
    ship_operation_statuses,
)
from envctl_engine.actions.action_ship_support import parse_ship_json_output, print_ship_result, ship_payload
from tests.python.actions.ship_owner_test_support import ShipContext


def test_ship_payload_and_result_output_keep_json_contract(tmp_path: Path, capsys: Any) -> None:
    context = ShipContext(project_name="Main", project_root=tmp_path / "project", repo_root=tmp_path, env={})
    context.project_root.mkdir()

    payload = ship_payload(
        context=context,
        git_root=tmp_path,
        branch="feature",
        status="checks_passed",
        started=0.0,
        commit_sha="abc123",
        committed=True,
        pushed=True,
        pr_url="https://example.test/pr/1",
        pr_created=False,
        checks={"state": "checks_passed", "duration_seconds": 0.1},
        protected_paths=[".envctl-state/code-intelligence.json"],
    )
    code = print_ship_result(payload, json_output=True, ok=True)

    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["contract_version"] == "envctl.ship.v1"
    assert printed["operation_statuses"] == {
        "checks": "checks_passed",
        "commit": "success",
        "merge_conflicts": "none",
        "pr": "existing",
        "push": "success",
    }
    assert printed["checks_state"] == "checks_passed"
    assert printed["passed_checks"] == []
    assert printed["checks_error"] == ""
    assert printed["checks_timeout_seconds"] == 0.0
    assert printed["protected_local_artifacts_skipped"] == [".envctl-state/code-intelligence.json"]
    assert parse_ship_json_output(ShipContext("Main", tmp_path, tmp_path, {})) is True
    assert parse_ship_json_output(ShipContext("Main", tmp_path, tmp_path, {"ENVCTL_ACTION_JSON": "true"})) is True
    assert parse_ship_json_output(ShipContext("Main", tmp_path, tmp_path, {"ENVCTL_ACTION_HUMAN": "true"})) is False

def test_ship_contract_owner_parses_embedded_payload_and_strips_ansi() -> None:
    output = (
        "\x1b[32mship progress\x1b[0m\n"
        "{\n"
        '  "contract_version": "envctl.ship.v1",\n'
        '  "status": "checks_pending_timeout"\n'
        "}\n"
    )

    assert ship_action_payload_from_contract(output) == {
        "contract_version": "envctl.ship.v1",
        "status": "checks_pending_timeout",
    }

def test_ship_operation_statuses_treat_commit_failure_before_new_commit_as_skipped_push() -> None:
    assert ship_operation_statuses(
        status="commit_failed",
        committed=False,
        pushed=False,
        pr_url="",
        pr_created=False,
        checks_state="",
        merge_conflicts={},
    ) == {
        "checks": "not_run",
        "commit": "failed",
        "merge_conflicts": "not_checked",
        "pr": "not_run",
        "push": "not_run",
    }

def test_ship_operation_statuses_treat_commit_failure_after_new_commit_as_push_failure() -> None:
    assert ship_operation_statuses(
        status="commit_failed",
        committed=True,
        pushed=False,
        pr_url="",
        pr_created=False,
        checks_state="",
        merge_conflicts={},
    ) == {
        "checks": "not_run",
        "commit": "success",
        "merge_conflicts": "not_checked",
        "pr": "not_run",
        "push": "failed",
    }

def test_ship_payload_normalizes_malformed_nested_payloads(tmp_path: Path) -> None:
    context = ShipContext(project_name="Main", project_root=tmp_path / "project", repo_root=tmp_path, env={})
    context.project_root.mkdir()

    payload = ship_payload(
        context=context,
        git_root=tmp_path,
        branch="feature",
        status="checks_passed",
        started=0.0,
        checks={
            "state": "checks_passed",
            "passed_checks": "malformed",
            "failing_checks": {"name": "pytest"},
            "pending_checks": None,
        },
        merge_conflicts=cast(Any, "malformed"),
    )

    assert payload["passed_checks"] == []
    assert payload["failing_checks"] == []
    assert payload["pending_checks"] == []
    assert payload["merge_conflicts"] == {}

def test_ship_payload_includes_full_pr_checks_and_deployment_url_when_supplied(tmp_path: Path) -> None:
    context = ShipContext(project_name="Main", project_root=tmp_path / "project", repo_root=tmp_path, env={})
    context.project_root.mkdir()

    payload = ship_payload(
        context=context,
        git_root=tmp_path,
        branch="feature",
        status="checks_passed",
        started=0.0,
        checks={
            "state": "checks_passed",
            "passed_checks": [{"name": "pytest", "state": "SUCCESS"}],
            "pr_checks": [
                {"name": "pytest", "state": "SUCCESS"},
                {"name": "preview", "state": "NEUTRAL"},
            ],
            "deployment_url": "https://preview.test/pr-7",
        },
    )

    assert payload["pr_checks"] == [
        {"name": "pytest", "state": "SUCCESS"},
        {"name": "preview", "state": "NEUTRAL"},
    ]
    assert payload["deployment_url"] == "https://preview.test/pr-7"

def test_ship_payload_does_not_invent_deployment_url(tmp_path: Path) -> None:
    context = ShipContext(project_name="Main", project_root=tmp_path / "project", repo_root=tmp_path, env={})
    context.project_root.mkdir()

    payload = ship_payload(
        context=context,
        git_root=tmp_path,
        branch="feature",
        status="no_checks_reported",
        started=0.0,
        checks={"state": "no_checks_reported"},
    )

    assert payload["deployment_url"] == ""

def test_ship_result_human_output_includes_pr_creation_state(tmp_path: Path, capsys: Any) -> None:
    context = ShipContext(project_name="Main", project_root=tmp_path / "project", repo_root=tmp_path, env={})
    context.project_root.mkdir()
    payload = ship_payload(
        context=context,
        git_root=tmp_path,
        branch="feature",
        status="checks_passed",
        started=0.0,
        commit_sha="abc123",
        committed=True,
        pushed=True,
        pr_url="https://example.test/pr/1",
        pr_created=True,
        checks={"state": "checks_passed", "duration_seconds": 0.1},
    )

    code = print_ship_result(payload, json_output=False, ok=True)

    assert code == 0
    assert capsys.readouterr().out == "ship: checks_passed pr=created https://example.test/pr/1\n"

def test_ship_result_human_output_tolerates_malformed_operation_statuses(capsys: Any) -> None:
    code = print_ship_result(
        {
            "status": "checks_passed",
            "operation_statuses": "malformed",
            "pr_url": "https://example.test/pr/1",
        },
        json_output=False,
        ok=True,
    )

    assert code == 0
    assert capsys.readouterr().out == "ship: checks_passed https://example.test/pr/1\n"
