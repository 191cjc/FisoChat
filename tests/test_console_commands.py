import unittest

from textual.widgets import Static

from fisochat.console import FisoChatApp, GroupPicker
from fisochat.console_commands import COMMANDS, CommandInput
from tests.test_console import FakeClient


class CommandCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_slash_filters_commands_and_tab_preserves_input_focus(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            panel = app.query_one("#command-hints", Static)
            composer = app.query_one(CommandInput)
            self.assertFalse(panel.display)
            await pilot.press("/", "r")
            self.assertTrue(panel.display)
            self.assertEqual([command.name for command in composer.matches], ["/refresh", "/reply"])
            await pilot.press("down", "tab")
            self.assertEqual(composer.value, "/reply ")
            self.assertTrue(composer.has_focus)
            self.assertIn("用法：/reply 记录号", composer.command_hint.plain)
            self.assertIn("/reply 31", composer.command_hint.plain)
            self.assertIsNone(app.reply_to)
            await pilot.press("8", "0", "enter")
            self.assertEqual(app.reply_to["record_id"], 80)
            self.assertFalse(panel.display)
            self.assertEqual(app.client.sent, [])

    async def test_enter_completes_partial_command_then_executes_full_command(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await pilot.press("/", "n", "enter")
            self.assertEqual(composer.value, "/name")
            self.assertFalse(app.show_names)
            await pilot.press("enter")
            self.assertTrue(app.show_names)
            self.assertEqual(composer.value, "")
            await pilot.press("/", "i", "m", "tab")
            self.assertEqual(composer.value, "/image ")
            self.assertIn("[记录号 [图片序号]]", composer.command_hint.plain)
            self.assertIn("省略参数查看最近一张", composer.command_hint.plain)
            await pilot.press("enter")
            self.assertEqual(composer.value, "")
            self.assertIn("没有可预览的图片", str(app.query_one("#notice", Static).render()))
            self.assertEqual(app.client.sent, [])

    async def test_escape_hides_hints_without_losing_draft_or_name_state(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            await app.command("/name")
            composer = app.query_one(CommandInput)
            await pilot.press("/", "r", "escape")
            self.assertIsNone(composer.command_hint)
            self.assertEqual(composer.value, "/r")
            self.assertTrue(app.show_names)
            await app._refresh()
            await pilot.pause()
            self.assertIsNone(composer.command_hint)
            await pilot.press("escape")
            self.assertFalse(app.show_names)
            self.assertEqual(composer.value, "/r")
            await pilot.press("e")
            self.assertIsNotNone(composer.command_hint)

    async def test_menu_navigates_all_commands_and_fits_small_terminal(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await pilot.press("/")
            self.assertEqual(len(composer.matches), len(COMMANDS))
            await pilot.press("up")
            self.assertEqual(composer.matches[composer.command_index].name, "/quit")
            self.assertIn("› /quit", composer.command_hint.plain)
            self.assertNotIn("/name", composer.command_hint.plain)
            self.assertLess(composer.region.bottom, 21)
            await pilot.press("down", "down", "shift+tab")
            self.assertEqual(composer.command_index, 0)
            await pilot.resize_terminal(45, 18)
            await pilot.pause()
            self.assertLessEqual(app.query_one("#command-hints").size.height, 7)
            self.assertGreater(composer.size.width, 0)
            self.assertEqual(composer.value, "/")
            self.assertEqual(app.client.sent, [])

    async def test_group_picker_keeps_keys_and_returns_to_partial_command(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(80, 28)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await pilot.press("/", "r", "ctrl+g")
            self.assertIsInstance(app.screen, GroupPicker)
            self.assertFalse(app.query_one("#command-hints").display)
            await pilot.press("down", "escape")
            self.assertEqual(composer.value, "/r")
            self.assertTrue(app.query_one("#command-hints").display)
            await pilot.press("ctrl+g")
            await pilot.press("down", "enter")
            await pilot.pause()
            self.assertEqual(app.selected_group, "group-b")
            self.assertEqual(composer.value, "")
            await app.command("/use 1")
            self.assertEqual(composer.value, "/r")
            self.assertEqual(app.client.sent, [])

    async def test_plain_text_double_slash_and_cursor_editing_are_not_completed(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(80, 28)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await pilot.press("h", "i")
            self.assertIsNone(composer.command_hint)
            await pilot.press("ctrl+u", "/", "/", "r")
            self.assertIsNone(composer.command_hint)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            self.assertEqual(app.client.sent, [("group-a", "/r", None)])
            await pilot.press("/", "r", "left")
            self.assertIsNone(composer.command_hint)
            await pilot.press("right")
            self.assertIsNotNone(composer.command_hint)
            await pilot.press("ctrl+u", "/", "z", "z")
            self.assertEqual(composer.matches, ())
            self.assertIn("没有匹配", composer.command_hint.plain)
            await pilot.press("enter")
            self.assertEqual(len(app.client.sent), 1)


if __name__ == "__main__":
    unittest.main()
