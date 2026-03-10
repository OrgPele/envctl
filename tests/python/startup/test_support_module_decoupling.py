from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.startup.resume_restore_support import restore_missing  # noqa: E402
from envctl_engine.startup.startup_execution_support import _maybe_prewarm_docker  # noqa: E402
from envctl_engine.startup.startup_selection_support import _tree_preselected_projects_from_state  # noqa: E402
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord  # noqa: E402


class _SpinnerStub:
    def __enter__(self) -> "_SpinnerStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, message: str) -> None:
        _ = message

    def fail(self, message: str) -> None:
        _ = message

    def succeed(self, message: str) -> None:
        _ = message


class _PortAllocatorStub:
    def reserve_next(self, preferred: int, *, owner: str) -> int:
        _ = owner
        return preferred

    def update_final_port(self, plan: object, final_port: int, *, source: str) -> None:
        _ = (plan, final_port, source)

    def release(self, port: int) -> None:
        _ = port


class StartupSupportModuleDecouplingTests(unittest.TestCase):
    def test_tree_preselected_projects_uses_local_state_helpers(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Feature Backend": ServiceRecord(name="Feature Backend", type="backend", cwd="."),
            },
            requirements={
                "Main": RequirementsResult(project="Main", components={}, health="healthy", failures=[]),
            },
        )
        runtime = SimpleNamespace(
            _try_load_existing_state=lambda **kwargs: state,
            _project_name_from_service=lambda name: name.split()[0],
        )
        project_contexts = [
            SimpleNamespace(name="Main"),
            SimpleNamespace(name="Feature"),
            SimpleNamespace(name="Missing"),
        ]

        result = _tree_preselected_projects_from_state(
            SimpleNamespace(runtime=runtime),
            runtime=runtime,
            project_contexts=project_contexts,
        )

        self.assertEqual(result, ["Feature", "Main"])

    def test_maybe_prewarm_docker_does_not_require_orchestrator_wrapper_methods(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            _requirement_enabled=lambda requirement_id, mode, route: requirement_id == "postgres",
            _command_exists=lambda command: command == "docker",
            process_runner=SimpleNamespace(
                run=lambda command, timeout: SimpleNamespace(returncode=0, stderr="", stdout="")
            ),
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        _maybe_prewarm_docker(SimpleNamespace(runtime=runtime), route=None, mode="main")

        self.assertEqual(events[-1][0], "requirements.docker_prewarm")
        self.assertEqual(events[-1][1]["used"], True)
        self.assertEqual(events[-1][1]["success"], True)
        self.assertEqual(events[-1][1]["command"], ["docker", "ps"])

    def test_restore_missing_uses_runtime_port_allocator_without_resume_wrappers(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            port_planner=_PortAllocatorStub(),
            env={},
            config=SimpleNamespace(raw={}, base_dir=Path("/tmp")),
            _project_name_from_service=lambda name: "Main",
            _requirements_ready=lambda requirements: True,
            _emit=lambda event, **payload: events.append((event, payload)),
            _tree_parallel_startup_config=lambda **kwargs: (False, 1),
            _resume_context_for_project=lambda state, project: None,
        )
        state = RunState(run_id="run-1", mode="main", services={}, requirements={})

        errors = restore_missing(
            SimpleNamespace(runtime=runtime),
            state,
            ["Main Backend"],
            spinner_factory=lambda *args, **kwargs: _SpinnerStub(),
            spinner_enabled_fn=lambda env: False,
            use_spinner_policy_fn=lambda policy: nullcontext(),
            emit_spinner_policy_fn=lambda emit, policy, context: None,
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich", style="dots"),
        )

        self.assertEqual(errors, ["Main: project root not found"])
        self.assertEqual(events[0][0], "resume.restore.execution")
        self.assertEqual(events[-1][0], "resume.restore.timing")


if __name__ == "__main__":
    unittest.main()
