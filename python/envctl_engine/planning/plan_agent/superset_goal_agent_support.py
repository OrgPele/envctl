from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree


SUPERSET_CODEX_GOAL_AGENT_ID = "0e19b1f7-51b4-45a1-84c1-0d9c5d6dbb5f"
SUPERSET_CODEX_GOAL_LAUNCHER = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
import tty


def _load_payload() -> tuple[str, str]:
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "", raw
    if not isinstance(payload, dict):
        return "", raw
    return str(payload.get("goal") or ""), str(payload.get("prompt") or "")


def _paste(fd: int, text: str) -> None:
    os.write(fd, b"\x1b[200~")
    os.write(fd, text.encode("utf-8", "replace"))
    os.write(fd, b"\x1b[201~")


def _resize_child(master_fd: int, source_fd: int) -> None:
    try:
        packed = fcntl.ioctl(source_fd, termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, xpix, ypix = struct.unpack("HHHH", packed)
    except OSError:
        rows, cols, xpix, ypix = 24, 120, 0, 0
    if rows <= 0:
        rows = 24
    if cols <= 0:
        cols = 120
    try:
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, xpix, ypix))
    except OSError:
        pass


def main() -> int:
    goal, prompt = _load_payload()
    pid, master_fd = pty.fork()
    if pid == 0:
        os.execvp("codex", ["codex", "--dangerously-bypass-approvals-and-sandbox"])

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    resize_requested = True

    def _request_resize(_signum: int, _frame: object) -> None:
        nonlocal resize_requested
        resize_requested = True

    signal.signal(signal.SIGWINCH, _request_resize)
    old_attrs = None
    if os.isatty(stdin_fd):
        old_attrs = termios.tcgetattr(stdin_fd)
        tty.setraw(stdin_fd)

    buffer = b""
    goal_typed = not goal
    goal_submit_attempts = 0
    goal_next_submit_at = 0.0
    prompt_pasted = not prompt
    prompt_submit_attempts = 0
    prompt_next_submit_at = 0.0
    start = time.monotonic()
    try:
        while True:
            if resize_requested:
                resize_requested = False
                _resize_child(master_fd, stdout_fd if os.isatty(stdout_fd) else stdin_fd)
            readable, _, _ = select.select([master_fd, stdin_fd], [], [], 0.05)
            if master_fd in readable:
                try:
                    data = os.read(master_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                os.write(stdout_fd, data)
                buffer = (buffer + data)[-20000:]

            if stdin_fd in readable:
                try:
                    data = os.read(stdin_fd, 65536)
                except OSError:
                    data = b""
                if data:
                    os.write(master_fd, data)

            now = time.monotonic()
            if not goal_typed and (b"OpenAI Codex" in buffer or b"Tip:" in buffer or now - start > 8.0):
                os.write(master_fd, f"/goal {goal}".encode("utf-8", "replace"))
                goal_typed = True
                goal_next_submit_at = now + 0.25

            if goal_typed and not prompt_pasted and b"Goal active" not in buffer and goal_submit_attempts < 6:
                if now >= goal_next_submit_at:
                    os.write(master_fd, b"\r")
                    os.write(master_fd, b"\n")
                    goal_submit_attempts += 1
                    goal_next_submit_at = now + 0.75

            if goal_typed and not prompt_pasted:
                if b"Goal active" in buffer:
                    _paste(master_fd, prompt)
                    prompt_pasted = True
                    prompt_next_submit_at = now + 0.25

            if prompt_pasted and prompt_submit_attempts < 6:
                if now >= prompt_next_submit_at:
                    os.write(master_fd, b"\r")
                    os.write(master_fd, b"\n")
                    prompt_submit_attempts += 1
                    prompt_next_submit_at = now + 0.75

            try:
                finished_pid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return 0
            if finished_pid == pid:
                if os.WIFEXITED(status):
                    return os.WEXITSTATUS(status)
                if os.WIFSIGNALED(status):
                    return 128 + os.WTERMSIG(status)
                return 0
    finally:
        if old_attrs is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attrs)
        try:
            os.kill(pid, signal.SIGHUP)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def ensure_superset_codex_goal_agent(runtime: Any, *, worktree: CreatedPlanWorktree) -> tuple[str, str | None]:
    env = getattr(runtime, "env", {}) or {}
    home = str(env.get("HOME") or os.environ.get("HOME") or "").strip()
    if not home:
        return "", "superset_home_unavailable"
    launcher, launcher_error = write_superset_codex_goal_launcher(Path(worktree.root))
    if launcher_error:
        return "", launcher_error
    host_db = superset_host_agent_db(Path(home))
    if host_db is None:
        return "", "superset_host_db_unavailable"
    now_ms = int(time.time() * 1000)
    try:
        with sqlite3.connect(host_db, timeout=1.0) as connection:
            connection.execute("pragma busy_timeout=1000")
            row = connection.execute(
                "select display_order from host_agent_configs where id = ? limit 1",
                (SUPERSET_CODEX_GOAL_AGENT_ID,),
            ).fetchone()
            if row:
                display_order = int(row[0] or 0)
            else:
                max_row = connection.execute(
                    "select coalesce(max(display_order), -1) from host_agent_configs"
                ).fetchone()
                display_order = int(max_row[0] if max_row else -1) + 1
            connection.execute(
                """
                insert or replace into host_agent_configs
                (
                    id, preset_id, label, command, args_json, prompt_transport,
                    prompt_args_json, env_json, display_order, created_at, updated_at
                )
                values (?, 'codex', 'Envctl Codex Goal', 'python3', ?, 'argv', '[]', '{}', ?, ?, ?)
                """,
                (
                    SUPERSET_CODEX_GOAL_AGENT_ID,
                    json.dumps([str(launcher)]),
                    display_order,
                    now_ms,
                    now_ms,
                ),
            )
            connection.commit()
    except sqlite3.Error as exc:
        return "", f"superset_host_agent_config_failed: {exc}"
    return SUPERSET_CODEX_GOAL_AGENT_ID, None


def write_superset_codex_goal_launcher(worktree_root: Path) -> tuple[Path, str | None]:
    state_dir = worktree_root / ".envctl-state"
    launcher = state_dir / "superset-codex-goal-launcher.py"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        current = launcher.read_text(encoding="utf-8") if launcher.exists() else ""
        if current != SUPERSET_CODEX_GOAL_LAUNCHER:
            launcher.write_text(SUPERSET_CODEX_GOAL_LAUNCHER, encoding="utf-8")
        launcher.chmod(0o700)
    except OSError as exc:
        return launcher, f"superset_codex_goal_launcher_write_failed: {exc}"
    return launcher, None


def superset_host_agent_db(home: Path) -> Path | None:
    host_root = home / ".superset" / "host"
    if not host_root.exists():
        return None
    candidates = [path for path in host_root.glob("*/host.db") if path.exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


__all__ = tuple(name for name in globals() if not name.startswith("_"))
