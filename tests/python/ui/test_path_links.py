from __future__ import annotations

import io
import unittest

from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.path_links import render_path_for_terminal, resolve_path_link, rich_path_text


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class _NonTtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return False


class _FakeText:
    def __init__(self, text: str, style: str | None = None) -> None:
        self.plain = text
        self.style = style


class PathLinksTests(unittest.TestCase):
    def test_hyperlink_mode_respects_auto_on_and_off(self) -> None:
        supported_env = {"TERM_PROGRAM": "iTerm.app"}
        auto_link = resolve_path_link(
            "/tmp/example.txt",
            env={"ENVCTL_UI_HYPERLINK_MODE": "auto", **supported_env},
            stream=_TtyStringIO(),
        )
        forced_on = resolve_path_link(
            "/tmp/example.txt",
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            stream=_TtyStringIO(),
        )
        forced_off = resolve_path_link(
            "/tmp/example.txt",
            env={"ENVCTL_UI_HYPERLINK_MODE": "off", **supported_env},
            stream=_TtyStringIO(),
        )

        self.assertTrue(auto_link.enabled)
        self.assertTrue(forced_on.enabled)
        self.assertFalse(forced_off.enabled)

    def test_non_tty_falls_back_to_plain_text_even_when_forced_on(self) -> None:
        rendered = render_path_for_terminal(
            "/tmp/example.txt",
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            stream=_NonTtyStringIO(),
        )

        self.assertEqual(rendered, "/tmp/example.txt")

    def test_private_tmp_paths_normalize_in_display_and_uri(self) -> None:
        link = resolve_path_link(
            "/private/tmp/example.txt",
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            stream=_TtyStringIO(),
        )

        self.assertEqual(link.display_text, "/tmp/example.txt")
        self.assertEqual(link.uri, "file:///tmp/example.txt")

    def test_strip_ansi_preserves_visible_path_text(self) -> None:
        rendered = render_path_for_terminal(
            "/tmp/example.txt",
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            stream=_TtyStringIO(),
        )

        self.assertIn("\x1b]8;;file:///tmp/example.txt", rendered)
        self.assertEqual(strip_ansi(rendered), "/tmp/example.txt")

    def test_rich_path_text_uses_link_style_when_enabled(self) -> None:
        rendered = rich_path_text(
            "/tmp/example.txt",
            text_cls=_FakeText,
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            stream=_TtyStringIO(),
        )

        self.assertEqual(rendered.plain, "/tmp/example.txt")
        self.assertEqual(rendered.style, "link file:///tmp/example.txt")
