#!/usr/bin/env bash

# Helpers for create-pr.sh.

create_pr_print_usage() {
    cat <<'EOF'
Create a GitHub PR from the current branch.

Usage:
  utils/create-pr.sh [options]

Options:
  --workdir PATH         Run in this git worktree (default: repo root)
  --base BRANCH          Base branch (default: origin/HEAD or dev)
  --head BRANCH          Head branch (default: current branch)
  --title TEXT           PR title (default: first commit subject)
  --body TEXT            PR body
  --body-file PATH       PR body file (overrides --body)
  --template PATH        Template file (default: .github/PULL_REQUEST_TEMPLATE.md or docs/PR_TEMPLATE.md)
  --draft                Create draft PR
  --no-draft             Create non-draft PR
  --no-push              Do not push branch
  --push                 Push branch (default)
  --reviewers a,b        Add reviewers (comma-separated)
  --labels a,b           Add labels (comma-separated)
  --assignees a,b        Add assignees (comma-separated)
  --no-commits           Do not include commit list in the body
  --help                 Show help

Notes:
  - Uncommitted changes are committed before PR creation using MAIN_TASK.md,
    or you will be prompted for a commit message if it is missing.
  - MAIN_TASK.md is appended to the PR body (or replaces {{MAIN_TASK}} if present).

Env:
  PR_BASE_BRANCH, PR_HEAD_BRANCH, PR_TITLE, PR_BODY, PR_BODY_FILE,
  PR_TEMPLATE_FILE, PR_REMOTE, PR_WORKDIR
EOF
}
