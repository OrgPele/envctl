from __future__ import annotations

import sys
import unittest
from typing import Any


def _emit_total(total: int) -> None:
    print(f"ENVCTL_TEST_TOTAL:{total}", file=sys.stderr, flush=True)


def _emit_progress(current: int, total: int) -> None:
    print(f"ENVCTL_TEST_PROGRESS:{current}/{total}", file=sys.stderr, flush=True)


class _ProgressTextTestResult(unittest.TextTestResult):
    def __init__(self, *args: Any, total: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._completed = 0
        self._total = max(0, int(total))

    def stopTest(self, test: unittest.case.TestCase) -> None:  # noqa: N802
        super().stopTest(test)
        self._completed += 1
        _emit_progress(min(self._completed, self._total), self._total)


class _ProgressTextTestRunner(unittest.TextTestRunner):
    resultclass = _ProgressTextTestResult

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._total = 0
        super().__init__(*args, **kwargs)

    def run(self, test: Any) -> unittest.result.TestResult:
        self._total = int(getattr(test, "countTestCases", lambda: 0)())
        _emit_total(self._total)
        return super().run(test)

    def _makeResult(self) -> _ProgressTextTestResult:  # noqa: N802
        return self.resultclass(self.stream, self.descriptions, self.verbosity, total=self._total)


def main(argv: list[str] | None = None) -> int:
    program = unittest.main(
        module=None,
        argv=["unittest", *(list(sys.argv[1:] if argv is None else argv))],
        exit=False,
        testRunner=_ProgressTextTestRunner,
    )
    result = getattr(program, "result", None)
    return 0 if getattr(result, "wasSuccessful", lambda: False)() else 1


if __name__ == "__main__":
    raise SystemExit(main())
