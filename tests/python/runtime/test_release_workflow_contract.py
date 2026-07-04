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


def test_release_workflow_merges_release_metadata_through_pr_rule() -> None:
    workflow = _release_workflow()

    assert "pull_request:" not in workflow
    assert "pull-requests: write" in workflow
    assert 'branch="release/envctl-${NEW_VERSION}"' in workflow
    assert "gh pr create" in workflow
    assert "gh pr merge" in workflow
    assert 'git push origin "HEAD:main"' not in workflow
    assert "gh release create" in workflow


def test_release_workflow_uses_release_token_for_pr_merge_and_github_release() -> None:
    workflow = _release_workflow()

    assert "secrets.ENVCTL_RELEASE_TOKEN || secrets.ENVCTL_RELEASE_PR_TOKEN || secrets.GITHUB_TOKEN" in workflow
    assert "GH_TOKEN: ${{ secrets.ENVCTL_RELEASE_TOKEN || secrets.ENVCTL_RELEASE_PR_TOKEN || secrets.GITHUB_TOKEN }}" in workflow


def test_release_workflow_prefers_checked_in_release_notes_file_before_generated_notes() -> None:
    workflow = _release_workflow()

    release_notes_index = workflow.index('release_notes="docs/changelog/RELEASE_NOTES_${NEW_VERSION}.md"')
    copy_index = workflow.index('cp "$release_notes" .release-tmp/notes-body.md')
    api_index = workflow.index("releases/generate-notes")
    assert release_notes_index < copy_index < api_index
    assert 'if [ -s "$release_notes" ]; then' in workflow
    assert "--- checked-in release notes preview ---" in workflow
    assert "--- generated notes preview ---" in workflow


def test_release_workflow_merges_release_pr_before_tagging_and_publishing() -> None:
    workflow = _release_workflow()

    commit_index = workflow.index("git commit -m \"Release envctl ${NEW_VERSION}\"")
    branch_index = workflow.index("HEAD:refs/heads/${branch}")
    merge_index = workflow.index("gh pr merge")
    fetch_index = workflow.index("git fetch origin main --tags")
    tag_index = workflow.index("git tag -a \"$NEW_VERSION\"")
    release_index = workflow.index("gh release create")

    assert commit_index < branch_index < merge_index < fetch_index < tag_index < release_index


def test_release_workflow_can_resume_after_metadata_already_merged() -> None:
    workflow = _release_workflow()

    assert 'gh release view "$new"' in workflow
    assert 'echo "tag_exists=$tag_exists"' in workflow
    assert "release metadata is already committed" in workflow
    assert 'tag_commit=$(git rev-list -n 1 "$NEW_VERSION")' in workflow
    assert 'expected ${release_commit}' in workflow


def test_release_workflow_cleans_dist_before_uploading_artifacts() -> None:
    workflow = _release_workflow()

    clean_index = workflow.rindex("rm -rf dist build ./*.egg-info")
    build_index = workflow.rindex("uv run --extra dev python -m build --wheel --sdist")
    release_index = workflow.index("gh release create")

    assert clean_index < build_index < release_index
