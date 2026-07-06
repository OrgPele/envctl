from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from envctl_engine.planning.plan_agent.constants import (
    _CODEX_QUEUE_MAX_TAB_ATTEMPTS,
    _CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS,
    _CODEX_QUEUE_READY_TIMEOUT_SECONDS,
)
from envctl_engine.planning.plan_agent.terminal_screen import (
    _codex_queue_message_needs_tab,
    _codex_queue_screen_confirms_queued,
    _codex_queue_screen_looks_ready,
    _prompt_picker_screen_looks_ready,
)


ReadScreen = Callable[[], str]
SendKey = Callable[[str], str | None]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


def wait_until_codex_queue_ready(
    *,
    read_screen: ReadScreen,
    monotonic: Clock = time.monotonic,
    sleep: Sleeper = time.sleep,
    timeout_seconds: float = _CODEX_QUEUE_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = _CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS,
) -> bool:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if _codex_queue_screen_looks_ready(read_screen()):
            return True
        sleep(poll_interval_seconds)
    return False


@dataclass(slots=True)
class CodexQueueMessageInteractor:
    read_screen: ReadScreen
    send_key: SendKey
    prompt_picker_enabled: bool = False
    monotonic: Clock = time.monotonic
    sleep: Sleeper = time.sleep
    timeout_seconds: float = _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    poll_interval_seconds: float = _CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS
    max_tab_attempts: int = _CODEX_QUEUE_MAX_TAB_ATTEMPTS

    def queue_message(self, text: str, *, require_text_match: bool = True) -> bool:
        deadline = self.monotonic() + self.timeout_seconds
        normalized_text = str(text).strip()
        picker_submitted = False
        tab_attempts = 0
        while self.monotonic() < deadline:
            screen = self.read_screen()
            picker_result = self._submit_prompt_picker_if_ready(
                screen,
                normalized_text=normalized_text,
                picker_submitted=picker_submitted,
            )
            if picker_result is False:
                return False
            if picker_result is True:
                picker_submitted = True
                continue
            if tab_attempts > 0 and _codex_queue_screen_confirms_queued(
                screen,
                text,
                require_text_match=require_text_match,
            ):
                return True
            if _codex_queue_message_needs_tab(screen, text, require_text_match=require_text_match):
                if tab_attempts >= self.max_tab_attempts:
                    return False
                if self.send_key("tab") is not None:
                    return False
                tab_attempts += 1
                self.sleep(self.poll_interval_seconds)
                continue
            self.sleep(self.poll_interval_seconds)
        return False

    def _submit_prompt_picker_if_ready(
        self,
        screen: str,
        *,
        normalized_text: str,
        picker_submitted: bool,
    ) -> bool | None:
        if (
            not self.prompt_picker_enabled
            or picker_submitted
            or not _codex_prompt_picker_command(normalized_text)
            or not _prompt_picker_screen_looks_ready("codex", screen, normalized_text)
        ):
            return None
        if self.send_key("enter") is not None:
            return False
        self.sleep(self.poll_interval_seconds)
        return True


def _codex_prompt_picker_command(text: str) -> bool:
    normalized = str(text).strip()
    return normalized.startswith("/") or normalized.startswith("$")
