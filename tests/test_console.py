import asyncio
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from rich.text import Text
from textual import events
from textual.widgets import ListView, RichLog

from fisochat.cli import main as cli_main
from fisochat.console import (
    FisoChatApp,
    GroupPicker,
    HelpScreen,
    SelectableRichLog,
    message_text,
    safe_text,
)
from fisochat.console_client import ConsoleClient, ConsoleError
from fisochat.console_commands import CommandInput
from fisochat.console_mentions import MentionMember, MentionSpan


def message(record_id, content="普通消息", *, bot=False):
    return {"record_id": record_id, "message_id": f"message-{record_id}",
            "username": "FisoChat" if bot else "小明", "is_bot": bot,
            "content": content, "sent_at": "2026-09-16T12:00:00+08:00",
            "quotes": [], "attachments": [], "recalled": False}


class FakeClient:
    def __init__(self):
        self.records = {"group-a": [message(index) for index in range(1, 81)],
                        "group-b": [message(81, "另一个群的消息")]}
        self.sent = []
        self.closed = False
        self.failure = False
        self.send_gate = None
        self.online = True
        self.alerts = {}
        self.alert_calls = []

    async def open(self):
        pass

    async def close(self):
        self.closed = True

    async def groups(self):
        if not self.online:
            raise ConsoleError("无法连接后台")
        return [{"group_openid": group, "message_count": len(records),
                 "latest_content": records[-1]["content"], "latest_username": "小明",
                 "latest_record_id": records[-1]["record_id"]}
                for group, records in self.records.items()]

    async def health(self):
        return {"qq_gateway": {"connected": True}}

    async def messages(self, group, *, before=None, after=None):
        records = self.records[group]
        if before is not None:
            records = [record for record in records if record["record_id"] < before]
        if after is not None:
            return deepcopy([record for record in records if record["record_id"] > after][:100])
        return deepcopy(records[-50:])

    async def mention_alerts(self, after, *, limit=100):
        if not self.online:
            raise ConsoleError("无法连接后台")
        self.alert_calls.append((after, limit))
        records = sorted(
            (
                record
                for group_records in self.records.values()
                for record in group_records
                if record["record_id"] > after
            ),
            key=lambda record: record["record_id"],
        )[:limit]
        return {
            "mentions": [
                deepcopy(self.alerts[record["record_id"]])
                for record in records
                if record["record_id"] in self.alerts
            ],
            "next_after": records[-1]["record_id"] if records else after,
            "has_more": len(records) == limit,
        }

    async def send(self, group, content, *, reply_to=None, mentions=None):
        self.sent.append((group, content, reply_to))
        if self.send_gate:
            await self.send_gate.wait()
        if self.failure:
            raise ConsoleError("模拟发送失败")
        record_id = max(record["record_id"] for records in self.records.values() for record in records) + 1
        self.records[group].append(message(record_id, content, bot=True))
        return {"recorded": True, "message_id": f"message-{record_id}"}


class ConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiline_paste_normalizes_line_endings_and_sends_once(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)

            app.post_message(events.Paste("first\r\nsecond\rthird"))
            await pilot.pause()

            self.assertEqual(composer.value, "first\nsecond\nthird")
            self.assertEqual(client.sent, [])
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            self.assertEqual(client.sent, [("group-a", "first\nsecond\nthird", None)])

    async def test_clipboard_paste_normalizes_line_endings(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            app.copy_to_clipboard("first\r\nsecond\rthird")

            await pilot.press("ctrl+v")

            self.assertEqual(composer.value, "first\nsecond\nthird")
            self.assertEqual(app.client.sent, [])

    async def test_shift_enter_inserts_newline_and_composer_grows_to_five_rows(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            self.assertEqual(composer.size.height, 1)

            await pilot.press("a", "shift+enter", "b")
            self.assertEqual(composer.value, "a\nb")
            self.assertEqual(client.sent, [])
            composer.value = "1\n2\n3\n4\n5\n6\n7"
            await pilot.pause()
            self.assertEqual(composer.size.height, 5)
            self.assertGreater(composer.max_scroll_y, 0)

    async def test_arrow_keys_move_between_lines_without_completion_candidates(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            composer.value = "ab\ncd"

            await pilot.press("up")
            self.assertEqual(composer.cursor_location, (0, 2))
            await pilot.press("down")
            self.assertEqual(composer.cursor_location, (1, 2))

    async def test_over_limit_keyboard_and_paste_edits_are_rejected_atomically(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            composer.value = "x" * 1999

            await pilot.press("a", "b")
            self.assertEqual(composer.value, "x" * 1999 + "a")
            app.post_message(events.Paste("y\r\nz"))
            await pilot.pause()
            self.assertEqual(composer.value, "x" * 1999 + "a")
            self.assertEqual(app.client.sent, [])

    async def test_read_only_and_disabled_composer_reject_edits_and_submission(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            composer.value = "keep"
            app.copy_to_clipboard(" pasted")

            composer.read_only = True
            composer.action_paste()
            composer.insert_mention(MentionMember(1, "member", "name", "alias"))
            await composer.action_submit()
            self.assertEqual(composer.value, "keep")
            self.assertEqual(composer.mentions, [])
            self.assertEqual(client.sent, [])

            composer.read_only = False
            composer.disabled = True
            composer.action_paste()
            await composer.action_submit()
            self.assertEqual(composer.value, "keep")
            self.assertEqual(client.sent, [])

    async def test_dragging_chat_history_copies_without_changing_the_draft(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            log = app.query_one(SelectableRichLog)
            messages = deepcopy(app.messages)
            composer.value = "保留草稿"
            composer.cursor_position = 2
            log.clear().write(Text("ab中文cd", style="bold cyan"), scroll_end=False)
            log.scroll_home(animate=False)
            await pilot.pause()
            scroll_y = log.scroll_y

            await pilot.mouse_down(log, offset=(2, 0))
            await pilot.mouse_up(log, offset=(6, 0))
            await pilot.pause()

            self.assertIsNotNone(log.text_selection)
            selected_segments = [
                segment for segment in log.render_line(0)
                if "中文" in segment.text
            ]
            self.assertEqual(len(selected_segments), 1)
            self.assertEqual(
                selected_segments[0].style.bgcolor,
                log.selection_style.bgcolor,
            )
            await pilot.press("ctrl+c")
            self.assertEqual(app.clipboard, "中文")
            self.assertTrue(app.is_running)
            self.assertTrue(composer.has_focus)
            self.assertEqual(composer.value, "保留草稿")
            self.assertEqual(composer.cursor_position, 2)
            self.assertEqual(log.scroll_y, scroll_y)
            self.assertEqual(app.messages, messages)
            self.assertEqual(client.sent, [])

            await pilot.press("shift+left", "ctrl+c")
            self.assertEqual(app.clipboard, "留")
            self.assertEqual(composer.value, "保留草稿")

    async def test_copying_blank_chat_history_space_is_a_no_op(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            log = app.query_one(SelectableRichLog)
            log.clear().write(Text("only line"), scroll_end=False)
            app.copy_to_clipboard("unchanged")
            await pilot.pause()

            await pilot.mouse_down(log, offset=(0, 0))
            await pilot.mouse_up(log, offset=(20, 0))
            await pilot.press("ctrl+c")
            self.assertEqual(app.clipboard, "only line")

            await pilot.mouse_down(log, offset=(2, 3))
            await pilot.mouse_up(log, offset=(7, 5))
            await pilot.press("ctrl+c")

            self.assertTrue(app.is_running)
            self.assertEqual(app.clipboard, "only line")

    async def test_copy_across_wrapped_lines_omits_visual_line_boundaries(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            log = app.query_one(SelectableRichLog)
            log.clear().write(Text("abcdefghij"), width=5, scroll_end=False)
            await pilot.pause()

            await pilot.mouse_down(log, offset=(2, 0))
            await pilot.mouse_up(log, offset=(3, 1))
            await pilot.press("ctrl+c")

            self.assertEqual(app.clipboard, "cdefgh")

    async def test_copy_across_separate_writes_retains_logical_newline(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            log = app.query_one(SelectableRichLog)
            log.clear().write(Text("abcde"), width=5, scroll_end=False)
            log.write(Text("fghij"), width=5, scroll_end=False)
            await pilot.pause()

            await pilot.mouse_down(log, offset=(2, 0))
            await pilot.mouse_up(log, offset=(3, 1))
            await pilot.press("ctrl+c")

            self.assertEqual(app.clipboard, "cde\nfgh")

    async def test_copy_boundaries_follow_deferred_clear_and_max_lines(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            log = app.query_one(SelectableRichLog)
            log.clear()
            log.max_lines = 3
            log._size_known = False
            log.write(Text("abcde"), width=3, scroll_end=False)
            log.write(Text("fghij"), width=3, scroll_end=False)
            self.assertEqual(log.lines, [])
            self.assertEqual(log._logical_line_starts, [])

            log._size_known = True
            while log._deferred_renders:
                log.write(*log._deferred_renders.popleft())
            self.assertEqual(len(log.lines), 3)
            self.assertEqual(log._logical_line_starts, [False, True, False])

            await pilot.mouse_down(log, offset=(0, 0))
            await pilot.mouse_up(log, offset=(2, 2))
            await pilot.press("ctrl+c")
            self.assertEqual(app.clipboard, "de\nfghij")

            log.clear().write(Text("abcdefghij"), width=3, scroll_end=False)
            self.assertEqual(log._logical_line_starts, [False, False, False])
            await pilot.mouse_down(log, offset=(0, 0))
            await pilot.mouse_up(log, offset=(1, 2))
            await pilot.press("ctrl+c")
            self.assertEqual(app.clipboard, "defghij")

    async def test_copy_after_horizontal_scroll_accounts_for_wide_characters(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(50, 20)) as pilot:
            await pilot.pause()
            log = app.query_one(SelectableRichLog)
            log.clear().write(Text("0123456789中文ABCDEFGHIJ" * 6), scroll_end=False)
            await pilot.pause()
            log.scroll_to(x=20, animate=False)
            await pilot.pause()
            self.assertTrue(log.render_line(0).text.startswith("GHIJ012345"))

            await pilot.mouse_down(log, offset=(0, 0))
            await pilot.mouse_up(log, offset=(10, 0))
            await pilot.press("ctrl+c")

            self.assertEqual(app.clipboard, "GHIJ012345")
            self.assertTrue(app.is_running)

    async def test_ctrl_q_remains_an_explicit_exit_shortcut(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+q")
            self.assertFalse(app.is_running)
        self.assertTrue(client.closed)

    async def test_clicking_chat_regions_keeps_typing_at_the_draft_cursor(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            log = app.query_one(RichLog)
            log.scroll_home(animate=False)
            await pilot.pause()
            for selector in ("#messages", "#brand", "#connection", "#group-title", "#notice", "#prompt", None):
                with self.subTest(selector=selector):
                    composer.value = "abcd"
                    composer.cursor_position = 2
                    app.screen.set_focus(None)
                    await pilot.click(selector)
                    self.assertTrue(composer.has_focus)
                    await pilot.press("x")
                    self.assertEqual(composer.value, "abxcd")
                    self.assertEqual(log.scroll_y, 0)
            self.assertEqual(client.sent, [])

    async def test_input_click_places_cursor_and_hint_click_keeps_completion_usable(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            composer.value = "abcdef"
            composer.cursor_position = 6
            await pilot.click("#input", offset=(2, 0))
            await pilot.press("x")
            self.assertEqual(composer.value, "abxcdef")
            composer.value = "/re"
            composer.cursor_position = 3
            await pilot.pause()
            await pilot.click("#command-hints", offset=(3, 1))
            await pilot.press("down", "tab")
            self.assertEqual(composer.value, "/reply ")
            self.assertTrue(composer.has_focus)

    async def test_window_focus_restores_composer_but_preserves_group_picker_controls(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            composer.value = "abcd"
            composer.cursor_position = 2
            app.screen.set_focus(None)
            app.post_message(events.AppBlur())
            await pilot.pause()
            app.post_message(events.AppFocus())
            await pilot.pause()
            await pilot.press("x")
            self.assertEqual(composer.value, "abxcd")
            await pilot.press("ctrl+g")
            await pilot.click("#picker-title")
            app.post_message(events.AppBlur())
            await pilot.pause()
            app.post_message(events.AppFocus())
            await pilot.pause()
            self.assertIsInstance(app.focused, ListView)
            await pilot.press("down", "enter")
            await pilot.pause()
            self.assertEqual(app.selected_group, "group-b")
            self.assertTrue(composer.has_focus)
            self.assertEqual(app.drafts["group-a"], "abxcd")

    async def test_message_stream_uses_full_width_without_a_persistent_group_list(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            self.assertEqual(len(app.query("#sidebar")), 0)
            self.assertEqual(len(app.query(ListView)), 0)
            self.assertGreaterEqual(app.query_one(RichLog).size.width, 66)
            self.assertEqual(len(app.query_one(RichLog).lines), 50)

    async def test_name_expands_all_loaded_authors_and_escape_restores_abbreviations(self):
        client = FakeClient()
        for record in client.records["group-a"]:
            record["username"] = "张三丰" if record["record_id"] % 2 else "张三宝"
            record["sender_key"] = "one" if record["record_id"] % 2 else "two"
        app = FisoChatApp(client)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            first = app.messages[31]
            second = app.messages[32]
            self.assertEqual(app.author_alias(first), "张三…")
            self.assertEqual(app.author_alias(second), "张三…·2")
            self.assertNotIn("张三丰", app.render_message(first).plain)
            app.query_one(CommandInput).value = "/name"
            await pilot.press("enter")
            self.assertTrue(app.show_names)
            self.assertIn("张三丰〔张三…〕", app.render_message(first).plain)
            self.assertIn("张三宝〔张三…·2〕", app.render_message(second).plain)
            await app._older()
            self.assertTrue(app.show_names)
            self.assertIn("张三丰", app.render_message(app.messages[1]).plain)
            app.query_one(CommandInput).value = "保留输入内容"
            await pilot.press("escape")
            self.assertFalse(app.show_names)
            self.assertNotIn("张三丰", app.render_message(first).plain)
            self.assertEqual(app.query_one(CommandInput).value, "保留输入内容")
            self.assertEqual(client.sent, [])
            await app.command("/name")
            await app.command("/name")
            self.assertFalse(app.show_names)

    async def test_aliases_distinguish_identical_nicknames_and_survive_history_and_group_switch(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            first = dict(message(100), username="同名用户", sender_key="person-a")
            second = dict(message(101), username="同名用户", sender_key="person-b")
            first_alias = app.author_alias(first)
            self.assertNotEqual(first_alias, app.author_alias(second))
            app._merge_messages([first, second])
            await app._older()
            self.assertEqual(app.author_alias(first), first_alias)
            await app.command("/name")
            await app.command("/use 2")
            self.assertFalse(app.show_names)
            await app.command("/use 1")
            self.assertEqual(app.author_alias(first), first_alias)
            renamed = dict(first, username="修改后的昵称")
            self.assertEqual(app.author_alias(renamed), first_alias)

    async def test_groups_is_a_temporary_picker_and_enter_returns_to_the_message_stream(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            app.query_one(CommandInput).value = "/groups"
            await pilot.press("enter")
            self.assertIsInstance(app.screen, GroupPicker)
            self.assertEqual(app.screen.query_one(ListView).index, 0)
            await app._refresh()
            await pilot.press("down", "enter")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, GroupPicker)
            self.assertEqual(app.selected_group, "group-b")
            self.assertEqual(len(app.query(ListView)), 0)
            self.assertTrue(app.query_one(CommandInput).has_focus)
            self.assertEqual(client.sent, [])

    async def test_canceling_group_picker_keeps_group_and_unsent_draft(self):
        app = FisoChatApp(FakeClient())
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            app.query_one(CommandInput).value = "当前群的草稿"
            await pilot.press("ctrl+g")
            self.assertIsInstance(app.screen, GroupPicker)
            await pilot.press("down", "escape")
            self.assertEqual(app.selected_group, "group-a")
            self.assertEqual(app.query_one(CommandInput).value, "当前群的草稿")
            self.assertTrue(app.query_one(CommandInput).has_focus)
            await pilot.press("ctrl+g")
            await pilot.press("ctrl+g")
            self.assertNotIsInstance(app.screen, GroupPicker)

    async def test_empty_group_picker_can_be_dismissed(self):
        client = FakeClient()
        client.records = {}
        app = FisoChatApp(client)
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            await app.command("/groups")
            self.assertIsInstance(app.screen, GroupPicker)
            await pilot.press("escape")
            self.assertTrue(app.query_one(CommandInput).has_focus)
            self.assertIsNone(app.selected_group)

    def test_message_is_one_logical_line_with_short_author_and_literal_content(self):
        record = dict(message(1, "第一行\n第二行"), username="Alice Smith",
                      quotes=["引用\n原文"], attachments=[{"filename": "照片.jpg", "url": "https://example.com/photo.jpg"}])
        compact = message_text(record).plain
        self.assertIn("Al… › 第一行 ↵ 第二行", compact)
        self.assertNotIn("\n", compact)
        self.assertNotIn("Alice Smith", compact)
        self.assertIn("照片.jpg", compact)
        self.assertIn("https://example.com/photo.jpg", compact)
        self.assertIn("Alice Smith", message_text(record, show_names=True).plain)

    async def test_initial_load_switch_drafts_and_older_records(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            self.assertEqual(app.selected_group, "group-a")
            self.assertEqual(len(app.messages), 50)
            app.query_one(CommandInput).value = "未发送\n草稿"
            await app.command("/use 2")
            self.assertEqual(app.selected_group, "group-b")
            self.assertEqual(app.query_one(CommandInput).value, "")
            await app.command("/use 1")
            self.assertEqual(app.query_one(CommandInput).value, "未发送\n草稿")
            await app._older()
            self.assertEqual(len(app.messages), 80)
            self.assertEqual(min(app.messages), 1)
            self.assertEqual(client.sent, [])
        self.assertTrue(client.closed)

    async def test_enter_sends_once_and_receives_new_record(self):
        client = FakeClient()
        client.send_gate = asyncio.Event()
        app = FisoChatApp(client)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            app.query_one(CommandInput).value = "终端发送"
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(app.query_one(CommandInput).disabled)
            await pilot.click("#messages")
            await pilot.press("enter")
            self.assertEqual(len(client.sent), 1)
            client.send_gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertFalse(app.query_one(CommandInput).disabled)
            self.assertEqual(app.query_one(CommandInput).value, "")
            self.assertEqual(client.sent[0], ("group-a", "终端发送", None))
            self.assertIn("终端发送", [record["content"] for record in app.messages.values()])

    async def test_failed_send_preserves_draft_and_reply_mode(self):
        client = FakeClient()
        client.failure = True
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            await app.command("/reply 80")
            app.query_one(CommandInput).value = "回复\n正文"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            self.assertEqual(app.query_one(CommandInput).value, "回复\n正文")
            self.assertEqual(app.reply_to["record_id"], 80)
            self.assertEqual(client.sent, [("group-a", "回复\n正文", "message-80")])
            await app.command("/cancel")
            self.assertIsNone(app.reply_to)

    async def test_live_refresh_deduplicates_and_recovers_after_disconnect(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            client.online = False
            await app._refresh()
            self.assertTrue(app._last_error)
            client.online = True
            client.records["group-a"].extend(message(index) for index in range(82, 305))
            await app._refresh()
            self.assertFalse(app._last_error)
            self.assertEqual(app.latest_record_id, 304)
            self.assertEqual(len(app.messages), 273)
            await app._refresh()
            self.assertEqual(len(app.messages), 273)

    async def test_cross_group_mention_popup_is_live_only_and_preserves_state(self):
        client = FakeClient()
        client.alerts[81] = {
            "record_id": 81,
            "group_openid": "group-b",
            "username": "历史用户",
            "content": "历史 @ 消息",
            "sent_at": "2026-09-16T12:00:00+08:00",
        }
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 26)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(client.alert_calls, [])
            self.assertEqual(list(app._notifications), [])
            await app._older()
            await app.select_group("group-b")
            await app.select_group("group-a")
            self.assertEqual(client.alert_calls, [])
            self.assertEqual(list(app._notifications), [])

            composer = app.query_one(CommandInput)
            member = MentionMember(80, "member-80", "小明", "小明")
            composer.value = "@小明\n保留草稿"
            composer.restore_mentions([MentionSpan(0, 3, member)])
            composer.selection = type(composer.selection)((0, 1), (1, 2))
            selection = composer.selection
            selected_text = composer.selected_text
            app.reply_to = app.messages[80]
            log = app.query_one(SelectableRichLog)
            log.scroll_to(y=4, animate=False)
            composer.focus()
            await pilot.pause()
            scroll_y = log.scroll_y

            client.records["group-b"].append(message(82, "后台群的新消息"))
            client.alerts[82] = {
                "record_id": 82,
                "group_openid": "group-b\n伪造第二行" + "g" * 80,
                "username": "提醒者\x1b[31m" + "n" * 40,
                "content": "请处理\n第二行\u202e" + "x" * 220,
                "sent_at": "2026-09-16T12:01:00+08:00",
            }
            with patch.object(app, "bell") as bell:
                await app._refresh()
                await pilot.pause()
                bell.assert_not_called()

            notifications = list(app._notifications)
            self.assertEqual(len(notifications), 1)
            notification = notifications[0]
            self.assertEqual(notification.title, "群聊 @ 提醒")
            self.assertEqual(notification.severity, "information")
            self.assertEqual(notification.timeout, 8)
            self.assertFalse(notification.markup)
            self.assertIn("group-b ↵ 伪造第二行", notification.message)
            self.assertIn("#82", notification.message)
            self.assertNotIn("\n", notification.message)
            self.assertNotIn("\x1b", notification.message)
            self.assertNotIn("\u202e", notification.message)

            self.assertEqual(app.selected_group, "group-a")
            self.assertEqual(composer.value, "@小明\n保留草稿")
            self.assertEqual(composer.selection, selection)
            self.assertEqual(composer.selected_text, selected_text)
            self.assertEqual(composer.mentions, [MentionSpan(0, 3, member)])
            self.assertEqual(app.reply_to["record_id"], 80)
            self.assertTrue(composer.has_focus)
            self.assertEqual(log.scroll_y, scroll_y)
            self.assertEqual(client.sent, [])

            live_alerts = client.mention_alerts
            client.mention_alerts = AsyncMock(return_value={
                "mentions": [deepcopy(client.alerts[82])],
                "next_after": 82,
                "has_more": False,
            })
            await app._refresh()
            await pilot.pause()
            self.assertEqual(len(list(app._notifications)), 1)
            client.mention_alerts = live_alerts

            client.records["group-b"].append(message(83, "断线时的新消息"))
            client.alerts[83] = {
                "record_id": 83,
                "group_openid": "group-b",
                "username": "恢复用户",
                "content": "断线恢复后提醒",
                "sent_at": "2026-09-16T12:02:00+08:00",
            }
            client.online = False
            await app._refresh()
            self.assertEqual(app._mention_cursor, 82)
            client.online = True
            await app._refresh()
            await pilot.pause()
            self.assertEqual(app._mention_cursor, 83)
            self.assertEqual(len(list(app._notifications)), 2)
            self.assertEqual(client.sent, [])

    async def test_current_group_mention_advances_cursor_without_popup(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 26)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(app.selected_group, "group-a")

            composer = app.query_one(CommandInput)
            composer.value = "当前群草稿"
            composer.cursor_position = 3
            app.reply_to = app.messages[80]
            composer.focus()
            client.records["group-a"].append(message(82, "当前群 @ 消息"))
            client.alerts[82] = {
                "record_id": 82,
                "group_openid": "group-a",
                "username": "当前群用户",
                "content": "请查看当前群",
                "sent_at": "2026-09-16T12:01:00+08:00",
            }

            await app._refresh()
            await pilot.pause()

            self.assertEqual(app._mention_cursor, 82)
            self.assertEqual(list(app._notifications), [])
            self.assertEqual(app._mention_notifications, {})
            self.assertEqual(app.selected_group, "group-a")
            self.assertEqual(composer.value, "当前群草稿")
            self.assertEqual(composer.cursor_position, 3)
            self.assertEqual(app.reply_to["record_id"], 80)
            self.assertTrue(composer.has_focus)
            self.assertEqual(client.sent, [])

            await app.select_group("group-b")
            await app.select_group("group-a")
            await app._refresh()
            await pilot.pause()
            self.assertEqual(list(app._notifications), [])
            self.assertEqual(app._mention_cursor, 82)

    async def test_selecting_group_dismisses_only_its_mention_popups(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 26)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            client.records["group-b"].append(message(82, "group-b @"))
            client.records["group-a"].append(message(83, "group-c @"))
            client.alerts[82] = {
                "record_id": 82,
                "group_openid": "group-b",
                "username": "B 群用户",
                "content": "B 群提醒",
                "sent_at": "2026-09-16T12:01:00+08:00",
            }
            client.alerts[83] = {
                "record_id": 83,
                "group_openid": "group-c",
                "username": "C 群用户",
                "content": "C 群提醒",
                "sent_at": "2026-09-16T12:02:00+08:00",
            }

            await app._refresh()
            self.assertEqual(app._mention_cursor, 83)
            self.assertEqual(set(app._mention_notifications), {"group-b", "group-c"})

            await app.select_group("group-b")
            await pilot.pause()

            notifications = list(app._notifications)
            self.assertEqual(len(notifications), 1)
            self.assertIn("C 群提醒", notifications[0].message)
            self.assertEqual(set(app._mention_notifications), {"group-c"})
            self.assertEqual(app.selected_group, "group-b")
            self.assertEqual(client.sent, [])

            await app.select_group("group-a")
            await app._refresh()
            await pilot.pause()
            self.assertEqual(len(list(app._notifications)), 1)
            self.assertEqual(app._mention_cursor, 83)
            self.assertEqual(client.sent, [])

    async def test_immediate_group_switch_dismisses_new_mention_without_race(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 26)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            client.records["group-b"].append(message(82, "group-b @"))
            client.alerts[82] = {
                "record_id": 82,
                "group_openid": "group-b",
                "username": "B 群用户",
                "content": "立即切换",
                "sent_at": "2026-09-16T12:01:00+08:00",
            }

            await app._refresh()
            await app.select_group("group-b")

            self.assertEqual(app.selected_group, "group-b")
            self.assertEqual(list(app._notifications), [])
            self.assertEqual(app._mention_notifications, {})
            self.assertEqual(app._mention_cursor, 82)
            self.assertEqual(client.sent, [])

    async def test_mention_notification_tracking_prunes_expired_alerts_on_refresh(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 26)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            client.records["group-b"].append(message(82, "group-b @"))
            client.alerts[82] = {
                "record_id": 82,
                "group_openid": "group-b",
                "username": "B 群用户",
                "content": "会过期",
                "sent_at": "2026-09-16T12:01:00+08:00",
            }

            await app._refresh()
            self.assertEqual(set(app._mention_notifications), {"group-b"})
            for notification in app._mention_notifications["group-b"]:
                notification.raised_at -= notification.timeout + 1

            await app._refresh()

            self.assertEqual(app._mention_notifications, {})

    async def test_invalid_mention_projection_does_not_advance_cursor(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(app._mention_cursor, 81)
            invalid_pages = (
                [],
                {
                    "mentions": [{
                        "record_id": "82",
                        "group_openid": "group-b",
                        "username": "member",
                        "content": "bad record id",
                        "sent_at": "2026-09-16T12:01:00+08:00",
                    }],
                    "next_after": 82,
                    "has_more": False,
                },
            )
            for page in invalid_pages:
                with self.subTest(page=page):
                    client.mention_alerts = AsyncMock(return_value=page)
                    await app._refresh()
                    self.assertEqual(app._mention_cursor, 81)
                    self.assertEqual(list(app._notifications), [])
                    self.assertTrue(app._last_error)
                    self.assertEqual(client.sent, [])

    async def test_help_unknown_command_and_slash_text(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause()
            await app.command("/help")
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("ctrl+c")
            self.assertIsInstance(app.screen, HelpScreen)
            self.assertTrue(app.is_running)
            await pilot.press("escape")
            await app.command("/not-a-command")
            self.assertEqual(client.sent, [])
            app.query_one(CommandInput).value = "//hello"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            self.assertEqual(client.sent, [("group-a", "/hello", None)])

    async def test_quit_command_remains_an_explicit_exit_path(self):
        client = FakeClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            await app.command("/quit")
            await pilot.pause()
            self.assertFalse(app.is_running)
        self.assertTrue(client.closed)

    async def test_empty_service_does_not_send_without_a_group(self):
        client = FakeClient()
        client.records = {}
        app = FisoChatApp(client)
        async with app.run_test(size=(70, 24)) as pilot:
            await pilot.pause()
            self.assertIsNone(app.selected_group)
            app.query_one(CommandInput).value = "不能发送"
            await pilot.press("enter")
            self.assertEqual(client.sent, [])

    def test_untrusted_chat_text_is_literal_and_cannot_control_terminal(self):
        content = "[red]文字[/red]\x1b]52;c;clipboard\x07\u202e"
        rendered = message_text(message(1, content))
        self.assertIn("[red]文字[/red]", rendered.plain)
        self.assertNotIn("\x1b", rendered.plain)
        self.assertNotIn("\x07", rendered.plain)
        self.assertNotIn("\u202e", rendered.plain)
        self.assertEqual(safe_text("正常\n换行"), "正常\n换行")

    def test_default_entry_is_console_and_service_mode_is_explicit(self):
        with patch("fisochat.console.main", return_value=0) as console:
            self.assertEqual(cli_main([]), 0)
            console.assert_called_once_with([])
        with patch("fisochat.main.main", return_value=0) as serve:
            self.assertEqual(cli_main(["serve"]), 0)
            serve.assert_called_once_with([])

    def test_remote_or_credentialed_console_endpoints_are_rejected(self):
        for endpoint in ("https://example.com", "http://localhost:8789", "http://user:pass@127.0.0.1", "http://127.0.0.1:99999"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                ConsoleClient(endpoint, "token")


if __name__ == "__main__":
    unittest.main()
