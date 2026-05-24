# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.planning_worktree_setup_test_support import *


class PlanningWorktreeSetupCodeIntelligenceTests(PlanningWorktreeSetupTestCase):
    def test_setup_worktree_can_disable_code_intelligence_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text('project_name: "repo"\n', encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CODE_INTELLIGENCE": "off"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertFalse((target_root / ".serena" / "project.yml").exists())

    def test_setup_worktree_can_run_cgc_index_for_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            cgc_calls: list[tuple[list[str], Path | None]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append((command, cwd))
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="created\n", stderr="")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append((command, cwd))
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(len(cgc_calls), 2)
            self.assertEqual(
                cgc_calls[0][0],
                ["cgc", "context", "create", "Repo-feature-a-1", "--database", "kuzudb"],
            )
            self.assertEqual(cgc_calls[0][1].resolve() if cgc_calls[0][1] else None, target_root.resolve())
            self.assertEqual(cgc_calls[1][0][:3], ["cgc", "index", str(target_root.resolve())])
            self.assertEqual(cgc_calls[1][0][3:], ["--context", "Repo-feature-a-1"])
            self.assertEqual(cgc_calls[1][1].resolve() if cgc_calls[1][1] else None, target_root.resolve())
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata.get("cgc_index_requested"))
            self.assertTrue(metadata.get("cgc_context_created"))
            self.assertTrue(metadata.get("cgc_index_succeeded"))
            self.assertEqual(metadata.get("cgc_database"), "kuzudb")
            self.assertEqual(
                [item.get("command") for item in metadata.get("cgc_commands", [])],
                [
                    ["cgc", "context", "create", "Repo-feature-a-1", "--database", "kuzudb"],
                    ["cgc", "index", str(target_root.resolve()), "--context", "Repo-feature-a-1"],
                ],
            )

    def test_setup_worktree_rewrites_serena_project_name_and_preserves_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature.a/with spaces" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text(
                "project_name: envctl\n"
                "language: python\n"
                "ignored_paths:\n"
                "  - trees/**\n",
                encoding="utf-8",
            )

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature.a/with spaces", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(
                (target_root / ".serena" / "project.yml").read_text(encoding="utf-8"),
                "project_name: envctl-feature-a_with_spaces-1\n"
                "language: python\n"
                "ignored_paths:\n"
                "  - trees/**\n",
            )

    def test_setup_worktree_prepends_serena_project_name_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text("language: python\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(
                (target_root / ".serena" / "project.yml").read_text(encoding="utf-8"),
                "project_name: repo-feature-a-1\nlanguage: python\n",
            )

    def test_setup_worktree_code_intelligence_templates_override_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text("project_name: repo\n", encoding="utf-8")
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")

            engine = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_WORKTREE_CGC_CONTEXT_TEMPLATE": "ctx_{project}_{feature}_{iteration}",
                    "ENVCTL_WORKTREE_SERENA_PROJECT_TEMPLATE": "serena_{worktree}",
                    "ENVCTL_WORKTREE_CGC_DATABASE": "custom db",
                    "ENVCTL_WORKTREE_CGC_INDEX": "true",
                },
            )
            cgc_calls: list[list[str]] = []

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(
                (target_root / ".serena" / "project.yml").read_text(encoding="utf-8"),
                "project_name: serena_feature-a-1\n",
            )
            self.assertEqual(cgc_calls[0], ["cgc", "context", "create", "ctx_Repo_feature-a_1", "--database", "custom_db"])
            self.assertEqual(
                cgc_calls[1],
                ["cgc", "index", str(target_root.resolve()), "--context", "ctx_Repo_feature-a_1"],
            )

    def test_setup_worktree_forced_cgc_index_skips_when_cgc_is_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text('project_name: "repo"\n', encoding="utf-8")
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=False):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(cgc_calls, [])
            self.assertEqual(
                (target_root / ".serena" / "project.yml").read_text(encoding="utf-8"),
                'project_name: "repo-feature-a-1"\n',
            )
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata.get("cgc_index_requested"))
            self.assertFalse(metadata.get("cgc_available"))
            self.assertEqual(metadata.get("cgc_database"), "kuzudb")

    def test_setup_worktree_auto_cgc_reuses_verified_source_context_without_reindexing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text("project_name: envctl\n", encoding="utf-8")
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            emitted: list[dict[str, object]] = []
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime)
            engine._emit = lambda event, **payload: emitted.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command == ["cgc", "list", "--context", "Envctl"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout=f"envctl {repo.resolve()} Project\n",
                        stderr="",
                    )
                if command[:3] == ["cgc", "context", "create"] or command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(cgc_calls, [["cgc", "list", "--context", "Envctl"]])
            self.assertTrue(
                any(
                    event.get("event") == "setup.worktree.code_intelligence.cgc_reuse"
                    and event.get("source_context") == "Envctl"
                    and event.get("success") is True
                    for event in emitted
                )
            )
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("cgc_context"), "Envctl-feature-a-1")
            self.assertEqual(metadata.get("cgc_active_context"), "Envctl")
            self.assertEqual(metadata.get("cgc_source_context"), "Envctl")
            self.assertEqual(metadata.get("cgc_index_mode"), "auto")
            self.assertFalse(metadata.get("cgc_index_requested"))
            self.assertFalse(metadata.get("cgc_context_managed"))
            self.assertEqual(metadata.get("cgc_index_skipped_reason"), "source_context_reused")

    def test_setup_worktree_auto_cgc_indexes_when_source_context_cannot_be_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text("project_name: envctl\n", encoding="utf-8")
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command == ["cgc", "list", "--context", "Envctl"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="/other/repo\n", stderr="")
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="created\n", stderr="")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(
                cgc_calls,
                [
                    ["cgc", "list", "--context", "Envctl"],
                    ["cgc", "context", "create", "Envctl-feature-a-1", "--database", "kuzudb"],
                    ["cgc", "index", str(target_root.resolve()), "--context", "Envctl-feature-a-1"],
                ],
            )
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("cgc_index_mode"), "auto")
            self.assertTrue(metadata.get("cgc_index_requested"))
            self.assertTrue(metadata.get("cgc_context_managed"))
            self.assertTrue(metadata.get("cgc_index_succeeded"))
            self.assertEqual(metadata.get("cgc_source_context"), "Envctl")
            self.assertEqual(metadata.get("cgc_active_context"), "Envctl-feature-a-1")

    def test_setup_worktree_cgc_launch_failure_does_not_fail_worktree_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            emitted: list[dict[str, object]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})
            engine._emit = lambda event, **payload: emitted.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    raise FileNotFoundError("cgc")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertTrue(target_root.is_dir())
            self.assertTrue(
                any(
                    event.get("event") == "setup.worktree.code_intelligence.cgc_context"
                    and event.get("target") == str(target_root.resolve())
                    and event.get("context") == "Repo-feature-a-1"
                    and event.get("success") is False
                    and event.get("error") == "cgc"
                    for event in emitted
                )
            )

    def test_setup_worktree_existing_cgc_context_message_continues_to_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            emitted: list[dict[str, object]] = []
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})
            engine._emit = lambda event, **payload: emitted.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="context already exists")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(len(cgc_calls), 2)
            self.assertTrue(
                any(
                    item.get("event") == "setup.worktree.code_intelligence.cgc_context"
                    and item.get("already_exists") is True
                    and item.get("success") is True
                    for item in emitted
                )
            )
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata.get("cgc_context_created"))
            self.assertTrue(metadata.get("cgc_context_already_exists"))
            self.assertTrue(metadata.get("cgc_index_succeeded"))

    def test_setup_worktree_cgc_context_failure_skips_index_but_preserves_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            emitted: list[dict[str, object]] = []
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})
            engine._emit = lambda event, **payload: emitted.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=2, stdout="", stderr="database failed")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(cgc_calls, [["cgc", "context", "create", "Repo-feature-a-1", "--database", "kuzudb"]])
            self.assertTrue(
                any(
                    item.get("event") == "setup.worktree.code_intelligence.cgc_context"
                    and item.get("success") is False
                    and item.get("returncode") == 2
                    and item.get("stderr") == "database failed"
                    for item in emitted
                )
            )
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata.get("cgc_index_succeeded"))
            self.assertEqual(metadata.get("cgc_context_returncode"), 2)
            self.assertEqual(metadata.get("cgc_database"), "kuzudb")

    def test_setup_worktree_without_serena_or_cgc_config_does_not_fail_or_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(cgc_calls, [])
            self.assertFalse((target_root / ".serena").exists())
            self.assertFalse((target_root / ".cgcignore").exists())

    def test_setup_worktree_real_git_smoke_writes_isolated_code_intelligence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            bin_dir = root / "bin"
            cgc_log = root / "cgc.log"
            repo.mkdir(parents=True, exist_ok=True)
            bin_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "README.md").write_text("# repo\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text("project_name: repo\nlanguage: python\n", encoding="utf-8")
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            cgc = bin_dir / "cgc"
            cgc.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {cgc_log}\n"
                "exit 0\n",
                encoding="utf-8",
            )
            cgc.chmod(0o755)

            env = {
                "ENVCTL_WORKTREE_CGC_INDEX": "true",
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            engine = self._runtime(repo, runtime, env=env)

            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            target = repo / "trees" / "feature-a" / "1"
            self.assertIsNone(error)
            self.assertTrue((target / ".git").exists())
            self.assertEqual(
                (target / ".serena" / "project.yml").read_text(encoding="utf-8"),
                "project_name: repo-feature-a-1\nlanguage: python\n",
            )
            self.assertEqual((target / ".cgcignore").read_text(encoding="utf-8"), ".git/\n")
            metadata = json.loads((target / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("serena_project_name"), "repo-feature-a-1")
            self.assertEqual(metadata.get("cgc_context"), "Repo-feature-a-1")
            self.assertEqual(metadata.get("cgc_database"), "kuzudb")
            self.assertTrue(metadata.get("cgc_index_succeeded"))
            self.assertEqual(
                cgc_log.read_text(encoding="utf-8").splitlines(),
                [
                    "context create Repo-feature-a-1 --database kuzudb",
                    f"index {target.resolve()} --context Repo-feature-a-1",
                ],
            )
