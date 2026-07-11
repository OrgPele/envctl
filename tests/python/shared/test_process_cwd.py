from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.shared.process_cwd import parse_lsof_cwd, process_cwd


class ProcessCwdTests(unittest.TestCase):
    def test_parse_lsof_cwd_ignores_pid_record_and_returns_name_record(self) -> None:
        self.assertEqual(parse_lsof_cwd("p123\nfcwd\nn/repo/backend\n"), "/repo/backend")
        self.assertIsNone(parse_lsof_cwd("p123\nfcwd\n"))

    def test_process_cwd_prefers_proc_symlink_without_spawning_lsof(self) -> None:
        with (
            patch("envctl_engine.shared.process_cwd.os.readlink", return_value="/repo/from-proc"),
            patch("envctl_engine.shared.process_cwd.subprocess.run") as run_mock,
        ):
            result = process_cwd(123)

        self.assertEqual(result, "/repo/from-proc")
        run_mock.assert_not_called()

    def test_process_cwd_falls_back_to_bounded_noninteractive_lsof(self) -> None:
        with (
            patch("envctl_engine.shared.process_cwd.os.readlink", side_effect=OSError),
            patch(
                "envctl_engine.shared.process_cwd.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="p123\nfcwd\nn/repo/from-lsof\n"),
            ) as run_mock,
        ):
            result = process_cwd(123)

        self.assertEqual(result, "/repo/from-lsof")
        self.assertEqual(
            run_mock.call_args.args[0],
            ["lsof", "-a", "-p", "123", "-d", "cwd", "-Fn"],
        )
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 1.0)
        self.assertIs(run_mock.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_process_cwd_returns_none_when_lsof_times_out(self) -> None:
        with (
            patch("envctl_engine.shared.process_cwd.os.readlink", side_effect=OSError),
            patch(
                "envctl_engine.shared.process_cwd.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["lsof"], 1.0),
            ),
        ):
            self.assertIsNone(process_cwd(123))


if __name__ == "__main__":
    unittest.main()
