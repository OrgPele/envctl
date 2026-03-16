from __future__ import annotations

import importlib.util
import os
import pty
import select
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"


def _run_in_pty(
    script: str,
    key_bytes: bytes,
    *,
    selector_impl: str | None = None,
    warmup_seconds: float = 0.8,
) -> str:
    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PYTHON_ROOT)
    if selector_impl is None:
        env.pop("ENVCTL_UI_SELECTOR_IMPL", None)
    else:
        env["ENVCTL_UI_SELECTOR_IMPL"] = selector_impl
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", script],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        close_fds=True,
        text=False,
    )
    os.close(slave_fd)

    try:
        time.sleep(max(0.1, warmup_seconds))
        if key_bytes:
            try:
                os.write(master_fd, key_bytes)
            except OSError:
                pass
        output = bytearray()
        deadline = time.time() + 12.0
        while time.time() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master_fd, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            if proc.poll() is not None and not ready:
                break
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3)
        return output.decode("utf-8", errors="ignore")
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass


def _run_in_pty_timed(
    script: str,
    writes: list[tuple[float, bytes]],
    *,
    selector_impl: str | None = None,
    timeout_seconds: float = 12.0,
) -> str:
    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PYTHON_ROOT)
    if selector_impl is None:
        env.pop("ENVCTL_UI_SELECTOR_IMPL", None)
    else:
        env["ENVCTL_UI_SELECTOR_IMPL"] = selector_impl
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", script],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        close_fds=True,
        text=False,
    )
    os.close(slave_fd)

    try:
        output = bytearray()
        start = time.time()
        write_index = 0
        deadline = start + timeout_seconds
        while time.time() < deadline:
            elapsed = time.time() - start
            while write_index < len(writes) and elapsed >= writes[write_index][0]:
                try:
                    os.write(master_fd, writes[write_index][1])
                except OSError:
                    break
                write_index += 1
            ready, _, _ = select.select([master_fd], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(master_fd, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            if proc.poll() is not None and write_index >= len(writes) and not ready:
                break
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3)
        return output.decode("utf-8", errors="ignore")
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass


class SelectorKeyThroughputPtyTests(unittest.TestCase):
    @staticmethod
    def _prompt_toolkit_available() -> bool:
        return importlib.util.find_spec("prompt_toolkit") is not None

    @staticmethod
    def _textual_available() -> bool:
        return importlib.util.find_spec("textual") is not None

    def test_project_selector_consumes_repeated_down_keys_in_pty_default_textual(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        if not self._textual_available():
            self.skipTest("textual is not installed")
        script = textwrap.dedent(
            """
            from envctl_engine.ui.textual.screens.selector import select_project_targets_textual

            class P:
                def __init__(self, name):
                    self.name = name

            projects = [P("alpha"), P("beta"), P("gamma"), P("delta")]
            selection = select_project_targets_textual(
                prompt="Test targets",
                projects=projects,
                allow_all=False,
                allow_untested=False,
                multi=False,
                emit=None,
            )
            print("RESULT_PROJECTS=" + ",".join(selection.project_names))
            print("RESULT_CANCELLED=" + str(selection.cancelled))
            """
        )
        # Default textual selector clamps at the final row.
        output = _run_in_pty(script, b"\x1b[B" * 10 + b"\r", selector_impl=None)
        self.assertRegex(output, r"RESULT_CANCELLED=False")
        self.assertRegex(output, r"RESULT_PROJECTS=delta")

    def test_grouped_selector_consumes_repeated_down_keys_in_pty_default_textual(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        if not self._textual_available():
            self.skipTest("textual is not installed")
        script = textwrap.dedent(
            """
            from envctl_engine.ui.textual.screens.selector import select_grouped_targets_textual

            class P:
                def __init__(self, name):
                    self.name = name

            projects = [P("Main")]
            services = ["Main Backend", "Main Frontend", "Main Worker", "Main Admin"]
            selection = select_grouped_targets_textual(
                prompt="Restart",
                projects=projects,
                services=services,
                allow_all=False,
                multi=False,
                emit=None,
            )
            print("RESULT_SERVICES=" + ",".join(selection.service_names))
            print("RESULT_PROJECTS=" + ",".join(selection.project_names))
            print("RESULT_CANCELLED=" + str(selection.cancelled))
            """
        )
        output = _run_in_pty(script, b"\x1b[B" * 10 + b"\r", selector_impl=None)
        self.assertRegex(output, r"RESULT_CANCELLED=False")
        # Grouped selector includes 4 services + 1 project-group row; repeated downs clamp to project-group.
        self.assertRegex(output, r"RESULT_PROJECTS=Main")

    def test_grouped_selector_consumes_early_repeated_down_keys_in_pty_default_textual(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        if not self._textual_available():
            self.skipTest("textual is not installed")
        script = textwrap.dedent(
            """
            from envctl_engine.ui.textual.screens.selector import select_grouped_targets_textual

            class P:
                def __init__(self, name):
                    self.name = name

            projects = [P("Main")]
            services = ["Main Backend", "Main Frontend", "Main Worker", "Main Admin"]
            selection = select_grouped_targets_textual(
                prompt="Restart",
                projects=projects,
                services=services,
                allow_all=False,
                multi=False,
                emit=None,
            )
            print("RESULT_SERVICES=" + ",".join(selection.service_names))
            print("RESULT_PROJECTS=" + ",".join(selection.project_names))
            print("RESULT_CANCELLED=" + str(selection.cancelled))
            """
        )
        output = _run_in_pty(script, b"\x1b[B" * 10 + b"\r", selector_impl=None, warmup_seconds=0.2)
        self.assertRegex(output, r"RESULT_CANCELLED=False")
        self.assertRegex(output, r"RESULT_PROJECTS=Main")

    def test_dashboard_to_grouped_selector_handoff_preserves_immediate_arrow_burst(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        if not self._textual_available():
            self.skipTest("textual is not installed")
        script = textwrap.dedent(
            """
            from envctl_engine.ui.terminal_session import TerminalSession
            from envctl_engine.ui.textual.screens.selector import select_grouped_targets_textual

            class P:
                def __init__(self, name):
                    self.name = name

            session = TerminalSession({}, prefer_basic_input=True)
            command = session.read_command_line("Enter command: ")
            print("CMD=" + repr(command), flush=True)
            if command != "t":
                print("RESULT_BAD_COMMAND", flush=True)
            else:
                projects = [P("Main")]
                services = ["Main Backend", "Main Frontend", "Main Worker", "Main Admin"]
                selection = select_grouped_targets_textual(
                    prompt="Run tests for",
                    projects=projects,
                    services=services,
                    allow_all=False,
                    multi=False,
                    emit=None,
                )
                print("RESULT_SERVICES=" + ",".join(selection.service_names), flush=True)
                print("RESULT_PROJECTS=" + ",".join(selection.project_names), flush=True)
                print("RESULT_CANCELLED=" + str(selection.cancelled), flush=True)
            """
        )
        output = _run_in_pty_timed(
            script,
            [
                (0.2, b"t\r"),
                (0.3, b"\x1b[B" * 3),
                (1.0, b"\r"),
            ],
            selector_impl=None,
        )
        self.assertIn("CMD='t'", output)
        self.assertRegex(output, r"RESULT_CANCELLED=False")
        self.assertRegex(output, r"RESULT_SERVICES=Main Admin")

    def test_background_service_launch_does_not_steal_selector_input_in_fresh_handoff(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        if not self._textual_available():
            self.skipTest("textual is not installed")
        script = textwrap.dedent(
            """
            import os
            import shutil
            import sys
            import tempfile
            import time
            from envctl_engine.shared.process_runner import ProcessRunner
            from envctl_engine.ui.terminal_session import TerminalSession
            from envctl_engine.ui.textual.screens.selector import select_grouped_targets_textual

            class P:
                def __init__(self, name):
                    self.name = name

            tmpdir = tempfile.mkdtemp(prefix="envctl-pty-launch-")
            child_log = os.path.join(tmpdir, "child.log")
            child_cmd = [
                sys.executable,
                "-c",
                (
                    "import sys,time;"
                    "first=sys.stdin.read(1);"
                    "sys.stdout.write('FIRST=' + repr(first) + '\\\\n');"
                    "sys.stdout.flush();"
                    "time.sleep(2.5)"
                ),
            ]
            runner = ProcessRunner()
            child = runner.start_background(child_cmd, stdout_path=child_log, stderr_path=child_log)
            time.sleep(0.2)
            session = TerminalSession({}, prefer_basic_input=True)
            command = session.read_command_line("Enter command: ")
            print("CMD=" + repr(command), flush=True)
            if command != "t":
                print("RESULT_BAD_COMMAND", flush=True)
            else:
                projects = [P("Main")]
                services = ["Main Backend", "Main Frontend", "Main Worker", "Main Admin"]
                selection = select_grouped_targets_textual(
                    prompt="Run tests for",
                    projects=projects,
                    services=services,
                    allow_all=False,
                    multi=False,
                    emit=None,
                )
                print("RESULT_SERVICES=" + ",".join(selection.service_names), flush=True)
                print("RESULT_PROJECTS=" + ",".join(selection.project_names), flush=True)
                print("RESULT_CANCELLED=" + str(selection.cancelled), flush=True)
            try:
                child.terminate()
            except Exception:
                pass
            try:
                child.wait(timeout=1.0)
            except Exception:
                pass
            try:
                with open(child_log, "r", encoding="utf-8") as handle:
                    print("CHILD_LOG=" + handle.read().strip(), flush=True)
            except OSError:
                pass
            shutil.rmtree(tmpdir, ignore_errors=True)
            """
        )
        output = _run_in_pty_timed(
            script,
            [
                (0.2, b"t\r"),
                (0.3, b"\x1b[B" * 3),
                (1.0, b"\r"),
            ],
            selector_impl=None,
        )
        self.assertIn("CMD='t'", output)
        self.assertRegex(output, r"RESULT_CANCELLED=False")
        self.assertRegex(output, r"RESULT_SERVICES=Main Admin")
        self.assertIn("CHILD_LOG=FIRST=''", output)

    def test_project_selector_consumes_repeated_down_keys_in_pty_planning_style_rollback(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        script = textwrap.dedent(
            """
            from envctl_engine.ui.textual.screens.selector import select_project_targets_textual

            class P:
                def __init__(self, name):
                    self.name = name

            projects = [P("alpha"), P("beta"), P("gamma"), P("delta")]
            selection = select_project_targets_textual(
                prompt="Test targets",
                projects=projects,
                allow_all=False,
                allow_untested=False,
                multi=False,
                emit=None,
            )
            print("RESULT_PROJECTS=" + ",".join(selection.project_names))
            print("RESULT_CANCELLED=" + str(selection.cancelled))
            """
        )
        # planning_style rollback wraps cursor; 10 downs over 4 rows lands on gamma.
        output = _run_in_pty(script, b"\x1b[B" * 10 + b"\r", selector_impl="planning_style")
        self.assertRegex(output, r"RESULT_CANCELLED=False")
        self.assertRegex(output, r"RESULT_PROJECTS=gamma")


if __name__ == "__main__":
    unittest.main()
