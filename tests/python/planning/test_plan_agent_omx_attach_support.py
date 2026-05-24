from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, _OmxSessionRecord
from envctl_engine.planning.plan_agent.omx_attach_support import (
    attach_discovery_diagnostics,
    attach_target_state_check,
    find_omx_tmux_panes_for_worktree,
    omx_session_records_for_worktree,
    read_omx_session_ids,
)


class PlanAgentOmxAttachSupportTests(unittest.TestCase):
    def test_session_records_read_selected_root_and_legacy_worktree_root_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "repo"
            selected_root = Path(tmpdir) / "omx-root"
            worktree_root.mkdir()
            selected_state = selected_root / ".omx" / "state" / "session.json"
            legacy_state = worktree_root / ".omx" / "state" / "session.json"
            selected_state.parent.mkdir(parents=True)
            legacy_state.parent.mkdir(parents=True)
            selected_state.write_text(json.dumps({"session_id": "omx-new", "cwd": str(worktree_root)}) + "\n")
            legacy_state.write_text(json.dumps({"session_id": "omx-legacy", "cwd": str(worktree_root)}) + "\n")
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")

            records = omx_session_records_for_worktree(
                SimpleNamespace(),
                worktree,
                omx_runtime_root_for_worktree_fn=lambda _runtime, _worktree: selected_root,
            )

            self.assertEqual([record.payload["session_id"] for record in records], ["omx-new", "omx-legacy"])
            self.assertEqual(read_omx_session_ids(records=records, worktree=worktree), ("omx-new", "omx-legacy"))

    def test_attach_state_check_separates_current_and_wrong_worktree_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "repo"
            other_root = Path(tmpdir) / "other"
            worktree_root.mkdir()
            other_root.mkdir()
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            records = [
                _OmxSessionRecord(
                    omx_root=Path(tmpdir) / "omx-root",
                    state_path=Path(tmpdir) / "state-a.json",
                    payload={"session_id": "omx-current", "native_session_id": "current-native", "cwd": str(worktree_root)},
                ),
                _OmxSessionRecord(
                    omx_root=Path(tmpdir) / "other-omx-root",
                    state_path=Path(tmpdir) / "state-b.json",
                    payload={"session_id": "omx-other", "native_session_id": "other-native", "cwd": str(other_root)},
                ),
            ]

            state_ok, diagnostics = attach_target_state_check(
                session_name="other-native",
                worktree=worktree,
                records=records,
                omx_payload_candidates_fn=lambda record, _worktree: [
                    str(record.payload["native_session_id"]),
                    str(record.payload["session_id"]),
                ],
            )

            self.assertFalse(state_ok)
            self.assertEqual(diagnostics["omx_session_candidates"], ["current-native", "omx-current"])
            self.assertEqual(diagnostics["omx_wrong_worktree_candidates"], ["other-native", "omx-other"])
            self.assertEqual(diagnostics["omx_session_records_checked"], 2)
            self.assertEqual(diagnostics["omx_wrong_worktree_records"], 1)

    def test_find_panes_filters_by_prefix_and_nested_worktree_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            nested = repo / "subdir"
            nested.mkdir(parents=True)
            worktree = CreatedPlanWorktree(name="Feature A/1", root=repo, plan_file="a.md")
            runtime = SimpleNamespace(config=SimpleNamespace(base_dir=tmpdir))
            stdout = "\n".join(
                [
                    f"omx-feature-a-1-main-abc|||ENVCTL_TMUX_PANE|||%77|||ENVCTL_TMUX_PATH|||{nested}",
                    f"other-session|||ENVCTL_TMUX_PANE|||%78|||ENVCTL_TMUX_PATH|||{nested}",
                    "malformed",
                ]
            )

            panes = find_omx_tmux_panes_for_worktree(
                runtime,
                worktree,
                run_tmux_probe_fn=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=stdout),
                omx_worktree_tmux_prefixes_fn=lambda _worktree: ("omx-feature-a-1-",),
            )

            self.assertEqual(panes, [("omx-feature-a-1-main-abc", "%77")])

    def test_attach_diagnostics_include_state_roots_and_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "repo"
            selected_root = Path(tmpdir) / "omx-root"
            worktree_root.mkdir()
            state_path = selected_root / ".omx" / "state" / "session.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps({"session_id": "omx-abc", "native_session_id": "native-abc", "cwd": str(worktree_root)})
                + "\n"
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")

            diagnostics = attach_discovery_diagnostics(
                SimpleNamespace(),
                worktree,
                omx_runtime_root_for_worktree_fn=lambda _runtime, _worktree: selected_root,
                find_omx_tmux_panes_for_worktree_fn=lambda _runtime, _worktree: [("pane-session", "%42")],
                omx_payload_candidates_fn=lambda _record, _worktree: ["native-abc", "omx-feature-a-1-main-abc"],
            )

            self.assertEqual(diagnostics["omx_root"], str(selected_root))
            self.assertEqual(diagnostics["omx_roots"], [str(selected_root), str(worktree_root.resolve())])
            self.assertTrue(diagnostics["session_state_exists"])
            self.assertTrue(diagnostics["session_id_present"])
            self.assertEqual(
                diagnostics["tmux_candidates_checked"],
                ["native-abc", "omx-feature-a-1-main-abc", "pane-session"],
            )
            self.assertEqual(diagnostics["worktree_panes_found"], 1)


if __name__ == "__main__":
    unittest.main()
