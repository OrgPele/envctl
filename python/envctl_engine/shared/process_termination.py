from __future__ import annotations

import errno
import os
import signal
import time
from collections.abc import Callable
from typing import Any

_IDENTITY_UNSET = object()


def terminate_pid(
    pid: int | None,
    *,
    process_runner: object | None,
    term_timeout: float,
    kill_timeout: float,
) -> bool:
    """Terminate a PID without treating an attempted signal as proof of exit.

    Process-runner implementations get the first opportunity to terminate the
    process group and then the individual process.  A false result (or an
    exception) is not success: the raw-signal fallback confirms exit and
    escalates to SIGKILL when necessary.
    """

    if not isinstance(pid, int) or pid <= 0:
        return True
    if pid in {os.getpid(), os.getppid()}:
        return False
    if not pid_is_running(process_runner, pid):
        return True
    initial_identity = pid_identity(process_runner, pid)

    group_terminator = getattr(process_runner, "terminate_process_group", None)
    if callable(group_terminator):
        try:
            terminated = bool(group_terminator(pid, term_timeout=term_timeout, kill_timeout=kill_timeout))
        except Exception:  # noqa: BLE001
            if callable(getattr(process_runner, "_process_group_is_running", None)):
                return False
            if _pid_gone_or_replaced(process_runner, pid, initial_identity=initial_identity):
                return False
        else:
            if not terminated:
                # Killing only the recorded leader after group cleanup failed
                # can orphan descendants and must never be reported as success.
                return False
            return _pid_gone_or_replaced(process_runner, pid, initial_identity=initial_identity)

    terminator = getattr(process_runner, "terminate", None)
    if callable(terminator):
        try:
            terminated = bool(terminator(pid, term_timeout=term_timeout, kill_timeout=kill_timeout))
        except Exception:  # noqa: BLE001
            if _pid_gone_or_replaced(process_runner, pid, initial_identity=initial_identity):
                return True
        else:
            if _pid_gone_or_replaced(process_runner, pid, initial_identity=initial_identity):
                return True
            if terminated:
                # A capable runner that claims success while the same PID remains
                # alive is not proof.  Do not signal again: the PID may have raced
                # with reuse between the runner and this verification.
                return False

    return terminate_with_raw_signals(
        process_runner,
        pid,
        term_timeout=term_timeout,
        kill_timeout=kill_timeout,
        initial_identity=initial_identity,
    )


def terminate_with_raw_signals(
    process_runner: object | None,
    pid: int,
    *,
    term_timeout: float,
    kill_timeout: float,
    initial_identity: str | None | object = _IDENTITY_UNSET,
) -> bool:
    """Last-resort termination that proves the recorded process exited."""

    if initial_identity is _IDENTITY_UNSET:
        initial_identity = pid_identity(process_runner, pid)
    assert isinstance(initial_identity, str) or initial_identity is None
    if _pid_gone_or_replaced(process_runner, pid, initial_identity=initial_identity):
        return True
    term_sent = _send_signal(pid, signal.SIGTERM)
    if term_sent is None:
        return True
    if not term_sent:
        return not pid_is_running(process_runner, pid)
    if wait_for_pid_exit(
        process_runner,
        pid,
        timeout=term_timeout,
        initial_identity=initial_identity,
    ):
        return True
    kill_sent = _send_signal(pid, signal.SIGKILL)
    if kill_sent is None:
        return True
    if not kill_sent:
        return not pid_is_running(process_runner, pid)
    return wait_for_pid_exit(
        process_runner,
        pid,
        timeout=kill_timeout,
        initial_identity=initial_identity,
    )


def _pid_gone_or_replaced(
    process_runner: object | None,
    pid: int,
    *,
    initial_identity: str | None,
) -> bool:
    if not pid_is_running(process_runner, pid):
        return True
    if initial_identity is None:
        return False
    current_identity = pid_identity(process_runner, pid)
    return current_identity is None or current_identity != initial_identity


def wait_for_pid_exit(
    process_runner: object | None,
    pid: int,
    *,
    timeout: float,
    initial_identity: str | None,
) -> bool:
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        if not pid_is_running(process_runner, pid):
            return True
        if initial_identity is not None:
            current_identity = pid_identity(process_runner, pid)
            if current_identity is None or current_identity != initial_identity:
                return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def pid_is_running(process_runner: object | None, pid: int) -> bool:
    checker = getattr(process_runner, "is_pid_running", None)
    if callable(checker):
        try:
            return bool(checker(pid))
        except Exception:  # noqa: BLE001
            pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def pid_identity(process_runner: object | None, pid: int) -> str | None:
    identity_reader = getattr(process_runner, "_pid_identity", None)
    if not callable(identity_reader):
        return None
    try:
        identity = identity_reader(pid)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(identity, str):
        return None
    normalized = identity.strip()
    return normalized or None


def _send_signal(pid: int, requested_signal: signal.Signals) -> bool | None:
    sender: Callable[[int, signal.Signals], Any] = os.kill
    try:
        sender(pid, requested_signal)
    except ProcessLookupError:
        return None
    except OSError:
        return False
    return True
