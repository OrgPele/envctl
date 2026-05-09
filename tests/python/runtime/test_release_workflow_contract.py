from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _release_workflow() -> str:
    return (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def test_release_workflow_runs_shipability_gate_before_version_bump() -> None:
    workflow = _release_workflow()

    gate_index = workflow.index("scripts/release_shipability_gate.py --repo .")
    bump_index = workflow.index("python scripts/prepare_release.py apply")

    assert gate_index < bump_index


def test_release_workflow_opens_pr_instead_of_pushing_release_commit_to_main() -> None:
    workflow = _release_workflow()

    assert "git push origin \"HEAD:main\"" not in workflow
    assert "branch=\"release/envctl-${NEW_VERSION}\"" in workflow
    assert "gh pr create" in workflow
    assert "--base main" in workflow


def test_release_workflow_publishes_only_after_release_pr_merge() -> None:
    workflow = _release_workflow()

    publish_index = workflow.index("publish:")
    guard_index = workflow.index("startsWith(github.event.pull_request.head.ref, 'release/envctl-')")
    tag_index = workflow.index("git tag -a \"$NEW_VERSION\"")

    assert publish_index < guard_index < tag_index


def test_release_workflow_cleans_dist_before_uploading_artifacts() -> None:
    workflow = _release_workflow()

    clean_index = workflow.rindex("rm -rf dist build ./*.egg-info")
    build_index = workflow.rindex(".venv/bin/python -m build --wheel --sdist")
    release_index = workflow.index("gh release create")

    assert clean_index < build_index < release_index
