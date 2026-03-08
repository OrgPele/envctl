from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable


CommandExists = Callable[[str], bool]


def load_package_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def detect_package_manager(base_dir: Path, *, command_exists: CommandExists | None = None) -> str | None:
    exists = command_exists or (lambda name: bool(shutil.which(name)))
    if (base_dir / "bun.lockb").is_file() or (base_dir / "bun.lock").is_file():
        if exists("bun"):
            return "bun"
    if (base_dir / "pnpm-lock.yaml").is_file():
        if exists("pnpm"):
            return "pnpm"
    if (base_dir / "yarn.lock").is_file():
        if exists("yarn"):
            return "yarn"
    if exists("npm"):
        return "npm"
    return None


def detect_python_bin(*roots: Path, command_exists: CommandExists | None = None) -> str | None:
    exists = command_exists or (lambda name: bool(shutil.which(name)))
    seen: set[Path] = set()
    for root in roots:
        for candidate in (
            root / ".venv" / "bin" / "python",
            root / "venv" / "bin" / "python",
        ):
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.is_file():
                return str(candidate)
        for candidate in sorted(root.glob(".venv*/bin/python")):
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.is_file():
                return str(candidate)

    for exe in ("python3.12", "python3", "python"):
        if exists(exe):
            return exe
    return None
