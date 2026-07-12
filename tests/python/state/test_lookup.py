from __future__ import annotations

import unittest

from envctl_engine.state.lookup import call_state_loader


class StateLookupTests(unittest.TestCase):
    def test_passes_all_supported_selection_arguments(self) -> None:
        captured: dict[str, object] = {}

        def loader(
            *,
            mode: str | None,
            strict_mode_match: bool,
            project_names: tuple[str, ...] | None,
        ) -> str:
            captured.update(
                mode=mode,
                strict_mode_match=strict_mode_match,
                project_names=project_names,
            )
            return "selected"

        result = call_state_loader(
            loader,
            mode="trees",
            strict_mode_match=True,
            project_names=("feature-a",),
        )

        self.assertEqual(result, "selected")
        self.assertEqual(
            captured,
            {
                "mode": "trees",
                "strict_mode_match": True,
                "project_names": ("feature-a",),
            },
        )

    def test_omits_unsupported_compatibility_keywords_for_untargeted_lookup(self) -> None:
        calls = 0

        def legacy_loader() -> str:
            nonlocal calls
            calls += 1
            return "legacy"

        self.assertEqual(call_state_loader(legacy_loader, mode="main"), "legacy")
        self.assertEqual(calls, 1)

    def test_targeted_lookup_fails_closed_when_loader_cannot_select_projects(self) -> None:
        called = False

        def legacy_loader(*, mode: str | None = None) -> str:
            nonlocal called
            called = True
            return str(mode)

        with self.assertRaisesRegex(TypeError, "accepts project_names"):
            call_state_loader(legacy_loader, mode="trees", project_names=("feature-a",))
        self.assertFalse(called)

    def test_var_keyword_loader_receives_selection_arguments(self) -> None:
        captured: dict[str, object] = {}

        def flexible_loader(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return captured

        self.assertIs(
            call_state_loader(
                flexible_loader,
                mode="trees",
                strict_mode_match=True,
                project_names=("feature-a",),
            ),
            captured,
        )
        self.assertEqual(captured["project_names"], ("feature-a",))


if __name__ == "__main__":
    unittest.main()
