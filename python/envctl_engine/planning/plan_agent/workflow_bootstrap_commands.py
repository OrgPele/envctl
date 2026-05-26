from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


SendText = Callable[[str], str | None]
SendKey = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class CliBootstrapCommandTyper:
    send_text: SendText
    send_key: SendKey

    def type_bootstrap_commands(self, *, cwd: Path, cli_command: str) -> list[str | None]:
        typed_root = shlex.quote(str(cwd))
        return [
            self.send_text(f"cd {typed_root}"),
            self.send_key("enter"),
            self.send_text(cli_command),
            self.send_key("enter"),
        ]
