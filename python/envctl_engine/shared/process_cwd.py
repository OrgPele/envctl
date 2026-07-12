from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from typing import Any


def process_cwd(
    pid: int,
    *,
    run_probe: Callable[[Sequence[str]], Any] | None = None,
) -> str | None:
    """Read a process CWD portably, returning only explicit probe evidence."""

    if pid <= 0:
        return None
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        pass

    command = ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"]
    try:
        completed = (
            run_probe(command)
            if run_probe is not None
            else subprocess.run(  # noqa: S603
                command,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=1.0,
                check=False,
            )
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        returncode = int(getattr(completed, "returncode", 1))
    except (TypeError, ValueError):
        return None
    if returncode != 0:
        return None
    return parse_lsof_cwd(str(getattr(completed, "stdout", "") or ""))


def parse_lsof_cwd(output: str) -> str | None:
    for line in output.splitlines():
        if line.startswith("n") and len(line) > 1:
            return line[1:]
    return None
