# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.actions.actions_cli_test_support import *  # noqa: F403,F405


class ActionsCliReviewCompletionTests(unittest.TestCase):
    def test_review_completion_plain_output_hyperlinks_paths_when_enabled(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "review"
            output_dir.mkdir()
            summary_path = output_dir / "summary.md"
            bundle_path = output_dir / "all.md"
            summary_path.write_text("# Summary\n", encoding="utf-8")
            bundle_path.write_text("# Bundle\n", encoding="utf-8")
            context = domain.ActionProjectContext(
                repo_root=root,
                project_root=root,
                project_name="Main",
                env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            )

            class FakeText:
                def __init__(self, text: str = "", style: str | None = None) -> None:
                    self.plain = text
                    self.style = style

                @classmethod
                def assemble(cls, *parts):
                    return cls("".join(str(part[0]) for part in parts))

            class FakeTable:
                def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                    self.rows: list[tuple[object, ...]] = []

                @classmethod
                def grid(cls, *args, **kwargs):  # noqa: ANN002, ANN003
                    return cls()

                def add_column(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                    return None

                def add_row(self, *values: object) -> None:
                    self.rows.append(values)

            class FakePanel:
                def __init__(self, body: object, title: object, box: object, expand: bool) -> None:
                    self.body = body
                    self.title = title
                    self.box = box
                    self.expand = expand

            class FakeConsole:
                def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                    self.printed: list[object] = []

                def print(self, value: object) -> None:
                    self.printed.append(value)

            fake_rich = types.ModuleType("rich")
            fake_box = types.ModuleType("rich.box")
            fake_box.ROUNDED = object()
            fake_console = types.ModuleType("rich.console")
            fake_console.Console = FakeConsole
            fake_panel = types.ModuleType("rich.panel")
            fake_panel.Panel = FakePanel
            fake_table = types.ModuleType("rich.table")
            fake_table.Table = FakeTable
            fake_text = types.ModuleType("rich.text")
            fake_text.Text = FakeText

            buffer = _TtyStringIO()
            with (
                redirect_stdout(buffer),
                patch.dict(
                    "sys.modules",
                    {
                        "rich": fake_rich,
                        "rich.box": fake_box,
                        "rich.console": fake_console,
                        "rich.panel": fake_panel,
                        "rich.table": fake_table,
                        "rich.text": fake_text,
                    },
                    clear=False,
                ),
            ):
                domain._print_review_completion(
                    context,
                    mode="single",
                    scope="all",
                    output_dir=output_dir,
                    summary_path=summary_path,
                    all_in_one_path=bundle_path,
                    stats=[],
                    tree_count=1,
                )

        output = buffer.getvalue()
        self.assertIn("\x1b]8;;file://", output)
        self.assertIn("Review Ready: Main", strip_ansi(output))
        self.assertIn(str(summary_path), strip_ansi(output))
        self.assertIn(str(bundle_path), strip_ansi(output))

    def test_review_completion_rich_output_uses_link_styled_text(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "review"
            output_dir.mkdir()
            summary_path = output_dir / "summary.md"
            bundle_path = output_dir / "all.md"
            summary_path.write_text("# Summary\n", encoding="utf-8")
            bundle_path.write_text("# Bundle\n", encoding="utf-8")
            context = domain.ActionProjectContext(
                repo_root=root,
                project_root=root,
                project_name="Main",
                env={"ENVCTL_UI_HYPERLINK_MODE": "on", "ENVCTL_ACTION_FORCE_RICH": "1"},
            )

            captured: dict[str, object] = {}

            class FakeText:
                def __init__(self, text: str = "", style: str | None = None) -> None:
                    self.plain = text
                    self.style = style

                @classmethod
                def assemble(cls, *parts):
                    return cls("".join(str(part[0]) for part in parts))

            class FakeTable:
                def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                    self.rows: list[tuple[object, ...]] = []

                @classmethod
                def grid(cls, *args, **kwargs):  # noqa: ANN002, ANN003
                    return cls()

                def add_column(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                    return None

                def add_row(self, *values: object) -> None:
                    self.rows.append(values)

            class FakePanel:
                def __init__(self, body: object, title: object, box: object, expand: bool) -> None:
                    self.body = body
                    self.title = title
                    self.box = box
                    self.expand = expand

            class FakeConsole:
                def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                    self.printed: list[object] = []
                    captured["console"] = self

                def print(self, value: object) -> None:
                    self.printed.append(value)

            fake_rich = types.ModuleType("rich")
            fake_box = types.ModuleType("rich.box")
            fake_box.ROUNDED = object()
            fake_console = types.ModuleType("rich.console")
            fake_console.Console = FakeConsole
            fake_panel = types.ModuleType("rich.panel")
            fake_panel.Panel = FakePanel
            fake_table = types.ModuleType("rich.table")
            fake_table.Table = FakeTable
            fake_text = types.ModuleType("rich.text")
            fake_text.Text = FakeText

            with patch.dict(
                "sys.modules",
                {
                    "rich": fake_rich,
                    "rich.box": fake_box,
                    "rich.console": fake_console,
                    "rich.panel": fake_panel,
                    "rich.table": fake_table,
                    "rich.text": fake_text,
                },
                clear=False,
            ):
                rendered = domain._print_review_completion_rich(
                    context,
                    mode="single",
                    scope="all",
                    output_dir=output_dir,
                    summary_path=summary_path,
                    all_in_one_path=bundle_path,
                    stats=[],
                    tree_count=1,
                )

        self.assertTrue(rendered)
        console = captured["console"]
        assert isinstance(console, FakeConsole)
        panel = console.printed[0]
        assert isinstance(panel, FakePanel)
        details = panel.body.rows[0][0]
        assert isinstance(details, FakeTable)
        summary_row = next(row for row in details.rows if row[0] == "Summary")
        bundle_row = next(row for row in details.rows if row[0] == "Bundle")
        self.assertEqual(summary_row[1].style, f"link {summary_path.as_uri()}")
        self.assertEqual(bundle_row[1].style, f"link {bundle_path.as_uri()}")
