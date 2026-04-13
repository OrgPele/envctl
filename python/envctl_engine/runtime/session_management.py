from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess


def _session_history_file(runtime_root: Path) -> Path:
    return runtime_root / ".envctl-sessions.jsonl"


def list_sessions(runtime_root: Path) -> list[dict[str, str]]:
    history_file = _session_history_file(runtime_root)
    if not history_file.is_file():
        return []
    records: list[dict[str, str]] = []
    try:
        for line in history_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return records[-100:]


def list_tmux_sessions(prefix: str = "envctl-") -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if result.returncode != 0:
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    sessions: list[dict[str, str]] = []
    for name in result.stdout.strip().splitlines():
        name = name.strip()
        if name.startswith(prefix):
            windows_result = subprocess.run(
                ["tmux", "list-windows", "-t", name, "-F", "#{window_name}"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            windows = [w.strip() for w in windows_result.stdout.strip().splitlines() if w.strip()]
            attach_cmd = f"tmux attach-session -t {shlex.quote(name)}"
            kill_cmd = f"tmux kill-session -t {shlex.quote(name)}"
            sessions.append({
                "name": name,
                "windows": ", ".join(windows) if windows else "unknown",
                "attach": attach_cmd,
                "kill": kill_cmd,
            })
    return sessions


def print_session_list(runtime_root: Path) -> None:
    tmux_sessions = list_tmux_sessions()
    history = list_sessions(runtime_root)

    if not tmux_sessions and not history:
        print("No envctl sessions found.")
        return

    if tmux_sessions:
        print("Active tmux sessions:")
        for s in tmux_sessions:
            print(f"  {s['name']} (windows: {s['windows']})")
            print(f"    attach: {s['attach']}")
            print(f"    kill:   {s['kill']}")
        print()

    if history:
        print("Session history (last 20):")
        for rec in history[-20:]:
            ts = rec.get("ts", "unknown")
            run_id = rec.get("run_id", "unknown")
            session_id = rec.get("session_id", "unknown")
            command = rec.get("command", "")
            print(f"  [{ts}] run={run_id} session={session_id} cmd={command}")


def print_attach_command(session_name: str) -> bool:
    tmux_sessions = list_tmux_sessions()
    for s in tmux_sessions:
        if s["name"] == session_name:
            print(s["attach"])
            return True
    print(f"Session '{session_name}' not found.")
    for s in tmux_sessions:
        print(f"  Available: {s['name']}")
    return False


def kill_session(session_name: str) -> bool:
    try:
        result = subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if result.returncode == 0:
            print(f"Killed session: {session_name}")
            return True
        print(f"Failed to kill session: {result.stderr.strip()}")
        return False
    except FileNotFoundError:
        print("tmux not found")
        return False
    except subprocess.TimeoutExpired:
        print(f"Timeout killing session: {session_name}")
        return False
