from __future__ import annotations

import json
import os
import sys
import termios
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.ui.selection_types import TargetSelection
from envctl_engine.ui.textual.screens.selector import (
    select_grouped_targets_textual,
    select_project_targets_textual,
)


def _debug_path() -> Path | None:
    raw = str(os.environ.get("ENVCTL_UI_SELECTOR_SUBPROCESS_DEBUG_PATH", "")).strip()
    if not raw:
        return None
    return Path(raw)


def _tty_snapshot(fd: int) -> dict[str, object]:
    try:
        attrs = termios.tcgetattr(fd)
        lflag = int(attrs[3])
        pendin = int(getattr(termios, "PENDIN", 0))
        return {
            "fd": fd,
            "isatty": os.isatty(fd),
            "ttyname": os.ttyname(fd) if os.isatty(fd) else None,
            "lflag": lflag,
            "icanon": bool(lflag & int(termios.ICANON)),
            "echo": bool(lflag & int(termios.ECHO)),
            "isig": bool(lflag & int(termios.ISIG)),
            "pendin": bool(pendin and (lflag & pendin)),
        }
    except Exception as exc:
        return {"fd": fd, "error": repr(exc)}


def _emit(event: str, **payload: object) -> None:
    path = _debug_path()
    if path is None:
        return
    record = {"event": event, **payload}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass


def _write_result(path: Path, selection: TargetSelection) -> None:
    payload = {
        "all_selected": bool(selection.all_selected),
        "untested_selected": bool(selection.untested_selected),
        "project_names": list(selection.project_names),
        "service_names": list(selection.service_names),
        "cancelled": bool(selection.cancelled),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: selector_subprocess_entry <payload.json> <result.json>", file=sys.stderr)
        return 2
    payload_path = Path(args[0])
    result_path = Path(args[1])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    kind = str(payload.get("kind", "")).strip().lower()
    prompt = str(payload.get("prompt", "") or "")
    multi = bool(payload.get("multi", False))
    allow_all = bool(payload.get("allow_all", False))
    _emit(
        "selector_subprocess.begin",
        pid=os.getpid(),
        kind=kind,
        prompt=prompt,
        stdout=_tty_snapshot(1),
        stderr=_tty_snapshot(2),
    )
    if kind == "grouped":
        project_names = [str(name) for name in payload.get("project_names", [])]
        projects = [SimpleNamespace(name=name) for name in project_names]
        services = [str(name) for name in payload.get("services", [])]
        selection = select_grouped_targets_textual(
            prompt=prompt,
            projects=projects,
            services=services,
            allow_all=allow_all,
            multi=multi,
            emit=_emit,
        )
    elif kind == "project":
        project_names = [str(name) for name in payload.get("project_names", [])]
        projects = [SimpleNamespace(name=name) for name in project_names]
        selection = select_project_targets_textual(
            prompt=prompt,
            projects=projects,
            allow_all=allow_all,
            allow_untested=bool(payload.get("allow_untested", False)),
            multi=multi,
            emit=_emit,
            initial_project_names=[str(name) for name in payload.get("initial_project_names", [])],
            exclusive_project_name=str(payload.get("exclusive_project_name", "") or "").strip() or None,
        )
    else:
        print(f"unsupported selector payload kind: {kind}", file=sys.stderr)
        return 2
    _write_result(result_path, selection)
    _emit(
        "selector_subprocess.end",
        pid=os.getpid(),
        kind=kind,
        cancelled=bool(selection.cancelled),
        service_count=len(selection.service_names),
        project_count=len(selection.project_names),
        stdout=_tty_snapshot(1),
        stderr=_tty_snapshot(2),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
