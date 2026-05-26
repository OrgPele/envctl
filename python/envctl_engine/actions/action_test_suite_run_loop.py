from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class TestSuiteRunLoop:
    __test__: ClassVar[bool] = False

    execution_specs: Sequence[Any]
    parallel: bool
    parallel_workers: int
    futures_module: Any
    run_spec: Callable[[Any], tuple[int, str]]
    failure_label: Callable[[Any], str]
    cancel_interrupted: Callable[[Any | None, dict[Any, Any]], None]
    shutdown_executor: Callable[[Any | None], None]

    def run(self) -> list[str]:
        executor: Any | None = None
        future_map: dict[Any, Any] = {}
        try:
            if self.parallel:
                pool = self.futures_module.ThreadPoolExecutor(max_workers=self.parallel_workers)
                executor = pool
                future_map = {pool.submit(self.run_spec, spec): spec for spec in self.execution_specs}
                return self._parallel_failures(future_map)
            return self._sequential_failures()
        except KeyboardInterrupt:
            self.cancel_interrupted(executor, future_map)
            raise
        finally:
            self.shutdown_executor(executor)

    def _parallel_failures(self, future_map: dict[Any, Any]) -> list[str]:
        failures: list[str] = []
        for future in self.futures_module.as_completed(future_map):
            execution = future_map[future]
            code, error = future.result()
            if code != 0:
                failures.append(self._failure_message(execution, error))
        return failures

    def _sequential_failures(self) -> list[str]:
        failures: list[str] = []
        for execution in self.execution_specs:
            code, error = self.run_spec(execution)
            if code != 0:
                failures.append(self._failure_message(execution, error))
                break
        return failures

    def _failure_message(self, execution: Any, error: str) -> str:
        return f"{self.failure_label(execution)}: {error or 'unknown test failure'}"
