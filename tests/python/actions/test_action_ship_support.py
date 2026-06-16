from __future__ import annotations

import inspect

from envctl_engine.actions.action_ship_checks import normalize_github_pr_checks as normalize_checks_from_owner
from envctl_engine.actions.action_ship_check_results import (
    normalize_github_pr_checks as normalize_checks_from_result_owner,
)
from envctl_engine.actions.action_ship_conflicts import parse_merge_tree_conflicts as parse_conflicts_from_owner
from envctl_engine.actions.action_ship_contract import ship_payload as ship_payload_from_owner
import envctl_engine.actions.action_ship_support as ship_support
from envctl_engine.actions.action_ship_support import (
    normalize_github_pr_checks,
    parse_merge_tree_conflicts,
    run_ship_workflow,
    ship_payload,
)


def test_public_run_ship_workflow_is_thin_compatibility_wrapper() -> None:
    source = inspect.getsource(run_ship_workflow)
    assert "ShipWorkflowRunner" in source
    assert len(source.splitlines()) <= 35


def test_ship_workflow_runner_exposes_named_phases() -> None:
    runner_cls = getattr(ship_support, "ShipWorkflowRunner", None)
    assert runner_cls is not None
    for phase in (
        "_reject_unavailable_git",
        "_resolve_branch",
        "_reject_existing_merge_conflicts",
        "_run_commit_phase",
        "_run_pr_phase",
        "_run_pr_label_phase",
        "_reject_predicted_merge_conflicts",
        "_run_checks_phase",
    ):
        assert hasattr(runner_cls, phase), phase


def test_ship_workflow_dependencies_group_injected_collaborators() -> None:
    dependencies_cls = getattr(ship_support, "ShipWorkflowDependencies", None)
    assert dependencies_cls is not None
    field_names = set(getattr(dependencies_cls, "__dataclass_fields__", {}))
    assert field_names == {
        "resolve_git_root",
        "git_available",
        "git_output",
        "run_git",
        "resolve_base_branch",
        "resolve_base_ref",
        "run_commit_action",
        "run_pr_action",
        "add_ship_pr_label",
        "probe_dirty_worktree",
        "existing_pr_url",
        "partition_envctl_protected_paths",
        "ordered_unique_paths",
        "github_pr_checks",
    }

    runner_fields = set(getattr(ship_support.ShipWorkflowRunner, "__dataclass_fields__", {}))
    assert runner_fields == {"context", "dependencies"}


def test_ship_support_reexports_cohesive_owner_modules() -> None:
    assert ship_payload is ship_payload_from_owner
    assert parse_merge_tree_conflicts is parse_conflicts_from_owner
    assert normalize_checks_from_owner is normalize_checks_from_result_owner
    assert normalize_github_pr_checks is normalize_checks_from_owner
