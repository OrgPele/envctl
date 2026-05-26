from __future__ import annotations

import unittest

from envctl_engine.runtime import command_alias_catalog, command_catalog, command_flag_catalog


class CommandCatalogOwnerTests(unittest.TestCase):
    def test_facade_reexports_alias_and_flag_catalog_contracts(self) -> None:
        self.assertIs(command_catalog.COMMAND_ALIASES, command_alias_catalog.COMMAND_ALIASES)
        self.assertIs(command_catalog.SUPPORTED_COMMANDS, command_alias_catalog.SUPPORTED_COMMANDS)
        self.assertIs(command_catalog.BOOLEAN_FLAGS, command_flag_catalog.BOOLEAN_FLAGS)
        self.assertIs(command_catalog.VALUE_FLAGS, command_flag_catalog.VALUE_FLAGS)
        self.assertIs(command_catalog.PAIR_FLAGS, command_flag_catalog.PAIR_FLAGS)
        self.assertIs(command_catalog.SPECIAL_FLAGS, command_flag_catalog.SPECIAL_FLAGS)
        self.assertIs(command_catalog.MODE_TREE_TOKENS, command_flag_catalog.MODE_TREE_TOKENS)

    def test_supported_flag_listing_includes_alias_mode_and_parser_only_flags(self) -> None:
        flags = set(command_catalog.list_supported_flag_tokens())

        self.assertIn("--plan", flags)
        self.assertIn("--tree", flags)
        self.assertIn("--project", flags)
        self.assertIn("--command", flags)
        self.assertIn("--no-copy-db-storage", flags)

    def test_supported_command_listing_is_copy_of_sorted_inventory(self) -> None:
        commands = command_catalog.list_supported_commands()

        self.assertEqual(commands, sorted(commands))
        self.assertEqual(commands, command_alias_catalog.list_supported_commands())
        commands.append("mutated")
        self.assertNotIn("mutated", command_catalog.SUPPORTED_COMMANDS)


if __name__ == "__main__":
    unittest.main()
