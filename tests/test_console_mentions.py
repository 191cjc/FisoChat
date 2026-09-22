import unittest

from fisochat.console import FisoChatApp
from fisochat.console_commands import CommandInput
from fisochat.console_mentions import MentionMember, MentionSpan, edited_mentions
from tests.test_console import FakeClient


class MentionClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.mention_requests = []
        for record in self.records["group-a"]:
            record.update(username="张三丰", sender_key="person-a", can_mention=True)
        self.records["group-a"][-1].update(username="张三宝", sender_key="person-b")
        self.records["group-b"][-1].update(sender_key="person-c", can_mention=True)

    async def send(self, group, content, *, reply_to=None, mentions=None):
        self.mention_requests.append(mentions or [])
        return await super().send(group, content, reply_to=reply_to)


class MentionEditTests(unittest.TestCase):
    def test_edits_shift_selected_mentions_and_remove_edited_names(self):
        member = MentionMember(1, "sender", "Alice", "Al…")
        original = "@Al… hello @Al…"
        spans = [MentionSpan(0, 4, member), MentionSpan(11, 15, member)]
        prefixed = "before " + original
        shifted = edited_mentions(original, prefixed, spans)
        self.assertEqual([(span.start, span.end) for span in shifted], [(7, 11), (18, 22)])
        changed = prefixed.replace("hello", "x")
        shifted = edited_mentions(prefixed, changed, shifted)
        self.assertEqual([(span.start, span.end) for span in shifted], [(7, 11), (14, 18)])
        changed_name = changed.replace("@Al…", "@Bob", 1)
        remaining = edited_mentions(changed, changed_name, shifted)
        self.assertEqual([(span.start, span.end) for span in remaining], [(14, 18)])
        self.assertEqual(edited_mentions(changed_name, "", remaining), [])


class MentionConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_historical_speaker_outside_loaded_messages_is_searchable(self):
        client = MentionClient()
        client.records["group-a"][0].update(
            username="很久以前的成员",
            sender_key="historical-person",
            can_mention=True,
        )
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)

            self.assertNotIn(1, app.messages)
            await pilot.press("@", "很", "久")

            self.assertEqual(
                [member.sender_key for member in composer.mention_matches],
                ["historical-person"],
            )
            await pilot.press("enter")
            self.assertEqual(composer.mentions[0].member.record_id, 1)

    async def test_live_messages_add_and_rename_persistent_members_in_place(self):
        client = MentionClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            client.records["group-a"].append({
                **client.records["group-a"][-1],
                "record_id": 82,
                "message_id": "new-speaker",
                "username": "新成员",
                "sender_key": "live-person",
            })

            await app._refresh()

            live = next(member for member in composer.members if member.sender_key == "live-person")
            self.assertEqual((live.record_id, live.username), (82, "新成员"))
            client.records["group-a"].append({
                **client.records["group-a"][-1],
                "record_id": 83,
                "message_id": "renamed-speaker",
                "username": "新昵称",
            })

            await app._refresh()

            matching = [member for member in composer.members if member.sender_key == "live-person"]
            self.assertEqual(len(matching), 1)
            self.assertEqual((matching[0].record_id, matching[0].username), (83, "新昵称"))

    async def test_group_switch_replaces_persistent_member_directory(self):
        client = MentionClient()
        client.records["group-a"][0].update(
            username="甲群旧成员", sender_key="group-a-historical", can_mention=True
        )
        client.records["group-b"][-1].update(username="乙群成员")
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            self.assertIn("group-a-historical", {member.sender_key for member in composer.members})

            await app.command("/use 2")

            self.assertEqual(
                [(member.sender_key, member.username) for member in composer.members],
                [("person-c", "乙群成员")],
            )

    async def test_other_bot_can_be_selected_and_sent_while_own_messages_are_excluded(self):
        client = MentionClient()
        client.records["group-a"][-2].update(
            username="FisoChat", is_bot=True, sender_key="own-bot", can_mention=False,
        )
        client.records["group-a"][-1].update(
            username="群助手", is_bot=True, sender_key="other-bot", can_mention=True,
        )
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await pilot.press("@")
            keys = {member.sender_key for member in composer.mention_matches}
            self.assertIn("other-bot", keys)
            self.assertNotIn("own-bot", keys)
            await pilot.press("群", "enter")
            self.assertEqual(composer.mentions[0].member.sender_key, "other-bot")
            await pilot.press("你", "好", "enter")
            await app.workers.wait_for_complete()
            self.assertEqual(client.mention_requests, [[{"record_id": 80, "start": 0, "end": 4}]])
            self.assertEqual(client.sent, [("group-a", "@群助… 你好", None)])
            await app.command("/at 79")
            self.assertEqual(composer.mentions, [])
            await app.command("/at 80")
            self.assertEqual(composer.mentions[0].member.sender_key, "other-bot")

    async def test_at_filters_members_and_enter_selects_before_sending(self):
        client = MentionClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await pilot.press("@")
            self.assertEqual(len(composer.mention_matches), 2)
            self.assertIn("张三宝〔张三…·2〕", composer.command_hint.plain)
            self.assertIn("张三丰〔张三…〕", composer.command_hint.plain)
            await pilot.press("down")
            client.records["group-a"].append(dict(client.records["group-a"][0], record_id=82,
                                                   message_id="new-member", username="赵六", sender_key="new-person"))
            await app._refresh()
            self.assertEqual(composer.mention_matches[composer.command_index].sender_key, "person-a")
            await pilot.press("张", "三", "丰", "enter")
            self.assertEqual(composer.value, "@张三… ")
            self.assertEqual(composer.mentions[0].member.sender_key, "person-a")
            self.assertEqual(client.sent, [])
            await pilot.press("你", "好", "enter")
            await app.workers.wait_for_complete()
            self.assertEqual(client.sent, [("group-a", "@张三… 你好", None)])
            self.assertEqual(client.mention_requests, [[{"record_id": 79, "start": 0, "end": 4}]])
            self.assertEqual(composer.mentions, [])

    async def test_multiple_mentions_survive_surrounding_edits_and_trim(self):
        client = MentionClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await app.command("/at 80")
            await app.command("/at 79")
            self.assertEqual(len(composer.mentions), 2)
            composer.value = "  请看 " + composer.value
            composer.value += "谢谢  "
            composer.cursor_position = len(composer.value)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            sent = client.sent[0][1]
            spans = client.mention_requests[0]
            self.assertEqual([item["record_id"] for item in spans], [80, 79])
            self.assertEqual([sent[item["start"]:item["end"]] for item in spans], ["@张三…·2", "@张三…"])

    async def test_drafts_and_failed_send_preserve_targets_in_their_group(self):
        client = MentionClient()
        client.failure = True
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await app.command("/at 80")
            await pilot.press("h", "i", "enter")
            await app.workers.wait_for_complete()
            draft = composer.value
            spans = list(composer.mentions)
            self.assertEqual(len(spans), 1)
            await app.command("/use 2")
            self.assertEqual(composer.mentions, [])
            self.assertEqual([member.sender_key for member in composer.members], ["person-c"])
            await app.command("/use 1")
            self.assertEqual(composer.value, draft)
            self.assertEqual(composer.mentions, spans)
            client.failure = False
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            self.assertEqual(client.mention_requests[0], client.mention_requests[1])

    async def test_editing_or_removing_a_name_cancels_its_mention(self):
        app = FisoChatApp(MentionClient())
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await app.command("/at 80")
            composer.value = composer.value.replace("张", "李")
            composer.cursor_position = len(composer.value)
            self.assertEqual(composer.mentions, [])
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            self.assertEqual(app.client.mention_requests, [[]])
            await app.command("/at 79")
            await pilot.press("ctrl+u")
            self.assertEqual(composer.mentions, [])

    async def test_email_unknown_and_unavailable_members_do_not_create_mentions(self):
        client = MentionClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            for command in ("/at 81", "/at 999", "/at bad"):
                await app.command(command)
                self.assertEqual(composer.mentions, [])
            composer.value = "mail@example.com"
            composer.cursor_position = len(composer.value)
            self.assertEqual(composer.mention_matches, ())
            self.assertIsNone(composer.command_hint)
            composer.value = "@未发言成员"
            composer.cursor_position = len(composer.value)
            self.assertEqual(composer.mention_matches, ())
            self.assertIn("没有匹配", composer.command_hint.plain)
            await pilot.press("escape")
            self.assertEqual(composer.value, "@未发言成员")
            self.assertEqual(composer.mentions, [])
            self.assertEqual(client.sent, [])

    async def test_reply_mode_and_escaped_slash_keep_mention_offsets(self):
        app = FisoChatApp(MentionClient())
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            await app.command("/reply 80")
            await pilot.press("/", "/", "space", "@", "tab", "h", "i", "enter")
            await app.workers.wait_for_complete()
            self.assertEqual(app.client.sent[0][2], "message-80")
            self.assertTrue(app.client.sent[0][1].startswith("/ @"))
            self.assertEqual(app.client.mention_requests[0][0]["start"], 2)

    async def test_mention_completion_after_line_break_uses_flat_offsets(self):
        client = MentionClient()
        app = FisoChatApp(client)
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            composer.value = "第一行\n@"
            composer.cursor_position = len(composer.value)

            await pilot.press("tab", "h", "i", "enter")
            await app.workers.wait_for_complete()

            sent = client.sent[0][1]
            mention = client.mention_requests[0][0]
            self.assertEqual(mention["start"], len("第一行\n"))
            self.assertEqual(sent[mention["start"]:mention["end"]], "@张三…·2")

    async def test_over_limit_mention_completion_is_rejected_as_one_edit(self):
        app = FisoChatApp(MentionClient())
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            composer.value = "x" * 1999 + "@"
            composer.cursor_position = len(composer.value)
            original = composer.value

            await pilot.press("tab")

            self.assertEqual(composer.value, original)
            self.assertEqual(composer.mentions, [])


if __name__ == "__main__":
    unittest.main()
