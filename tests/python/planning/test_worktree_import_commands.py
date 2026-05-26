from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from envctl_engine.planning.worktree_import_commands import (
    ImportedBranchRef,
    build_fetch_remote_branch_command,
    build_import_worktree_add_command,
    build_update_imported_worktree_command,
    imported_branch_slug,
    normalize_import_branch_ref,
)


class WorktreeImportCommandsTests(unittest.TestCase):
    def test_normalize_import_branch_ref_accepts_origin_forms(self) -> None:
        self.assertEqual(
            normalize_import_branch_ref("feature/foo"),
            ImportedBranchRef(
                remote="origin",
                branch="feature/foo",
                remote_ref="origin/feature/foo",
                remote_ref_path="refs/remotes/origin/feature/foo",
            ),
        )
        self.assertEqual(normalize_import_branch_ref("origin/feature/foo").branch, "feature/foo")
        self.assertEqual(normalize_import_branch_ref("refs/remotes/origin/feature/foo").branch, "feature/foo")

    def test_normalize_import_branch_ref_rejects_unsafe_or_unsupported_refs(self) -> None:
        invalid = (
            "",
            " ",
            "../feature",
            "feature/..",
            "feature/*",
            "refs/heads/feature/foo",
            "upstream/feature/foo",
            "0123456789abcdef0123456789abcdef01234567",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_import_branch_ref(value)

    def test_imported_branch_slug_is_stable_for_slashy_branch_names(self) -> None:
        self.assertEqual(imported_branch_slug("feature/foo"), "feature-foo")
        self.assertEqual(imported_branch_slug("bugfix/JIRA-123_remote"), "bugfix-jira-123-remote")

    def test_fetch_command_updates_only_the_remote_tracking_ref(self) -> None:
        ref = normalize_import_branch_ref("feature/foo")

        self.assertEqual(
            build_fetch_remote_branch_command(repo_root=Path("/repo"), branch_ref=ref),
            [
                "git",
                "-C",
                "/repo",
                "fetch",
                "origin",
                "feature/foo:refs/remotes/origin/feature/foo",
            ],
        )

    def test_worktree_add_command_tracks_remote_without_force_reset(self) -> None:
        ref = normalize_import_branch_ref("feature/foo")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            target = Path(tmpdir) / "repo" / "trees" / "imported" / "feature-foo"

            self.assertEqual(
                build_import_worktree_add_command(
                    repo_root=repo_root,
                    target=target,
                    branch_ref=ref,
                    git_hooks_disabled=True,
                ),
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "add",
                    "--track",
                    "-b",
                    "feature/foo",
                    str(target),
                    "origin/feature/foo",
                ],
            )

    def test_update_command_uses_ff_only_merge(self) -> None:
        ref = normalize_import_branch_ref("feature/foo")

        self.assertEqual(
            build_update_imported_worktree_command(worktree_root=Path("/repo/trees/imported/feature-foo"), branch_ref=ref),
            ["git", "-C", "/repo/trees/imported/feature-foo", "merge", "--ff-only", "origin/feature/foo"],
        )

    def test_git_backed_import_commands_create_tracking_worktree_and_fail_on_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            origin = root / "origin.git"
            source = root / "source"
            clone = root / "clone"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "dev@example.test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Dev"], check=True)
            (source / "README.md").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push", "origin", "HEAD:main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "switch", "-c", "feature/foo"], check=True, capture_output=True)
            (source / "feature.txt").write_text("remote\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "feature.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "feature"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(source), "push", "-u", "origin", "feature/foo"],
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(clone), "remote", "set-url", "origin", str(origin)], check=True)

            ref = normalize_import_branch_ref("feature/foo")
            subprocess.run(build_fetch_remote_branch_command(repo_root=clone, branch_ref=ref), check=True)
            target = clone / "trees" / "imported" / imported_branch_slug(ref.branch)
            subprocess.run(
                build_import_worktree_add_command(
                    repo_root=clone,
                    target=target,
                    branch_ref=ref,
                    git_hooks_disabled=False,
                ),
                check=True,
            )

            branch = subprocess.check_output(["git", "-C", str(target), "branch", "--show-current"], text=True).strip()
            upstream = subprocess.check_output(
                ["git", "-C", str(target), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                text=True,
            ).strip()
            self.assertEqual(branch, "feature/foo")
            self.assertEqual(upstream, "origin/feature/foo")

            subprocess.run(["git", "-C", str(target), "config", "user.email", "dev@example.test"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Dev"], check=True)
            (target / "local.txt").write_text("local\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "add", "local.txt"], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-m", "local"], check=True, capture_output=True)
            (source / "remote.txt").write_text("remote\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "remote.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "remote"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push"], check=True, capture_output=True)
            subprocess.run(build_fetch_remote_branch_command(repo_root=clone, branch_ref=ref), check=True)

            result = subprocess.run(build_update_imported_worktree_command(worktree_root=target, branch_ref=ref))
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
