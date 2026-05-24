from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess


def default_git_state_components(project_root: Path) -> tuple[str, str, int]:
    head = ""
    status = ""
    try:
        head_proc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if head_proc.returncode == 0:
            head = (head_proc.stdout or "").strip()
        status_proc = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain=1"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status_proc.returncode == 0:
            status = status_proc.stdout or ""
    except Exception:
        head = ""
        status = ""
    status_hash = hashlib.sha1(status.encode("utf-8")).hexdigest()
    status_lines = len([line for line in status.splitlines() if line.strip()])
    return head, status_hash, status_lines
