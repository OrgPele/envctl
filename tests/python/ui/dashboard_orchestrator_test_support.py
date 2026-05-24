from __future__ import annotations

from io import StringIO
import sys
import unittest
from types import SimpleNamespace

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.dashboard.pr_flow import PrFlowResult
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.target_selector import TargetSelection


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class _RuntimeStub:
    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.config = SimpleNamespace(raw={}, base_dir=base_dir or REPO_ROOT)
        self.env: dict[str, str] = {}
        self.selection_calls: list[dict[str, object]] = []
        self.last_dispatched_route: Route | None = None
        self._latest_state: RunState | None = None
        self.next_selection = TargetSelection(project_names=["Main"])
        self.next_selections: list[TargetSelection] = []
        self.dispatch_code: int = 0
        self.read_prompts: list[str] = []
        self.read_responses: list[str] = []
        self.text_input_prompts: list[dict[str, str]] = []
        self.text_input_responses: list[str | None] = []
        self.confirm_prompts: list[dict[str, str]] = []
        self.confirm_responses: list[bool | None] = []
        self.pr_flow_calls: list[dict[str, object]] = []
        self.next_pr_flow_result: PrFlowResult | None = PrFlowResult(project_names=["Main"], base_branch="main")
        self.startup_orchestrator = object()
        self.dispatched_routes: list[Route] = []

    @staticmethod
    def _emit(*_args, **_kwargs):  # noqa: ANN001
        return None

    @staticmethod
    def _project_name_from_service(name: str) -> str:
        trimmed = str(name).strip()
        for suffix in (" Backend", " Frontend"):
            if trimmed.endswith(suffix):
                return trimmed[: -len(suffix)].strip()
        return "Main" if name.startswith("Main ") else ""

    @staticmethod
    def _projects_for_services(_services: list[str]) -> set[str]:
        return {"Main"}

    @staticmethod
    def _selectors_from_passthrough(_args):  # noqa: ANN001
        return set()

    def dispatch(self, route: Route) -> int:
        self.last_dispatched_route = route
        self.dispatched_routes.append(route)
        return self.dispatch_code

    def _try_load_existing_state(self, *, mode: str, strict_mode_match: bool = True):  # noqa: ANN001, ARG002
        if self._latest_state is None:
            return None
        return self._latest_state

    def _select_grouped_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        services: list[str],
        allow_all: bool,
        multi: bool,
    ) -> TargetSelection:
        self.selection_calls.append(
            {
                "selector": "grouped",
                "prompt": prompt,
                "projects": [getattr(project, "name", "") for project in projects],
                "services": list(services),
                "allow_all": allow_all,
                "multi": multi,
            }
        )
        return self._pop_selection()

    def _select_project_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
        initial_project_names: list[str] | None = None,
        exclusive_project_name: str | None = None,
    ) -> TargetSelection:
        self.selection_calls.append(
            {
                "selector": "project",
                "prompt": prompt,
                "projects": [getattr(project, "name", "") for project in projects],
                "allow_all": allow_all,
                "allow_untested": allow_untested,
                "multi": multi,
                "initial_project_names": list(initial_project_names or []),
                "exclusive_project_name": exclusive_project_name,
            }
        )
        return self._pop_selection()

    def _pop_selection(self) -> TargetSelection:
        if self.next_selections:
            return self.next_selections.pop(0)
        return self.next_selection

    def _read_interactive_command_line(self, prompt: str) -> str:
        self.read_prompts.append(prompt)
        if self.read_responses:
            return self.read_responses.pop(0)
        return ""

    def _prompt_text_input(
        self,
        *,
        title: str,
        help_text: str,
        placeholder: str,
        initial_value: str,
        default_button_label: str,
    ) -> str | None:
        self.text_input_prompts.append(
            {
                "title": title,
                "help_text": help_text,
                "placeholder": placeholder,
                "initial_value": initial_value,
                "default_button_label": default_button_label,
            }
        )
        if self.text_input_responses:
            return self.text_input_responses.pop(0)
        return ""

    def _prompt_yes_no(self, *, title: str, prompt: str) -> bool | None:
        self.confirm_prompts.append({"title": title, "prompt": prompt})
        if self.confirm_responses:
            return self.confirm_responses.pop(0)
        return False


class _RuntimeStubMissingProjectResolver(_RuntimeStub):
    @staticmethod
    def _project_name_from_service(name: str) -> str:
        _ = name
        return ""


class _DashboardOrchestratorTestCase(unittest.TestCase):
    @staticmethod
    def _state_with_active_frontend_and_project_configured_services(
        configured_services: list[str],
        *,
        stopped_services: list[dict[str, str]] | None = None,
    ) -> RunState:
        metadata: dict[str, object] = {
            "project_roots": {"Main": "."},
            "dashboard_project_configured_services": {"Main": configured_services},
        }
        if stopped_services is not None:
            metadata["dashboard_stopped_services"] = stopped_services
        return RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
            metadata=metadata,
        )

