from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence


def default_legacy_engine_path() -> Path:
    return Path(__file__).resolve().parents[2] / "lib" / "engine" / "main.sh"


def run_legacy_engine(argv: Sequence[str], *, env: dict[str, str] | None = None, engine_path: str | None = None) -> int:
    cmd = [engine_path or str(default_legacy_engine_path()), *argv]
    merged_env = os.environ.copy()
    merged_env["ENVCTL_ENGINE_PYTHON_V1"] = "false"
    if env:
        merged_env.update(env)
    completed = subprocess.run(cmd, env=merged_env, check=False)
    return completed.returncode
