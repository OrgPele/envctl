from __future__ import annotations

import sys


_completed_nodeids: set[str] = set()
_total = 0


def _emit_total(total: int) -> None:
    sys.stderr.write(f"ENVCTL_TEST_TOTAL:{total}\n")
    sys.stderr.flush()


def _emit_progress(current: int, total: int) -> None:
    sys.stderr.write(f"ENVCTL_TEST_PROGRESS:{current}/{total}\n")
    sys.stderr.flush()


def pytest_collection_finish(session) -> None:  # noqa: ANN001
    global _completed_nodeids, _total
    _completed_nodeids = set()
    _total = len(getattr(session, "items", []))
    _emit_total(_total)


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001
    nodeid = str(getattr(report, "nodeid", "")).strip()
    if not nodeid or nodeid in _completed_nodeids:
        return
    when = str(getattr(report, "when", "")).strip()
    outcome_failed = bool(getattr(report, "failed", False))
    outcome_skipped = bool(getattr(report, "skipped", False))
    if when == "call" or (when in {"setup", "teardown"} and (outcome_failed or outcome_skipped)):
        _completed_nodeids.add(nodeid)
        _emit_progress(len(_completed_nodeids), _total)
