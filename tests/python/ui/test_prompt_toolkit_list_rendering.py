from __future__ import annotations

import unittest

from envctl_engine.ui import prompt_toolkit_list


class PromptToolkitListRenderingTests(unittest.TestCase):
    def test_visible_window_tracks_cursor_without_rendering_entire_long_list(self) -> None:
        start, end = prompt_toolkit_list.visible_row_window(total=40, cursor=20, height=10, status_error=False)

        self.assertEqual(end - start, 5)
        self.assertLess(start, 20)
        self.assertGreater(end, 20)

    def test_visible_window_reserves_space_for_status_error(self) -> None:
        without_error = prompt_toolkit_list.visible_row_window(total=40, cursor=20, height=16, status_error=False)
        with_error = prompt_toolkit_list.visible_row_window(total=40, cursor=20, height=16, status_error=True)

        self.assertLess(with_error[1] - with_error[0], without_error[1] - without_error[0])


if __name__ == "__main__":
    unittest.main()
