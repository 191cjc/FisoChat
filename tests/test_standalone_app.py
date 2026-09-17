"""Exercise real HTTP routes and SQLite with only the QQ network boundary mocked."""

import asyncio
import base64
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from botpy.errors import ServerError

from fisochat.config import AppConfig
from fisochat.console_client import ConsoleClient, ConsoleError
from fisochat.interfaces.qq.client import ChatRecorderClient
from fisochat.interfaces.qq.gateway import MonitoredBotWebSocket
from fisochat.main import create_read_only_application
from fisochat.send import main as send_main


def authorization(username="管理员", password="测试口令"):
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def event(message_id, *, group="group-1", content="收到的群消息"):
    return {
        "op": 0,
        "t": "GROUP_MESSAGE_CREATE",
        "d": {
            "id": message_id,
            "group_openid": group,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "author": {"username": "小明", "member_openid": "member-1"},
            "attachments": [{"url": "https://example.com/photo.jpg", "content_type": "image/jpeg"}],
            "msg_elements": [{"content": "引用文本"}],
            "message_scene": {"token": "must-not-render"},
        },
    }


class StandaloneAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = AppConfig.from_env({
            "QQ_BOT_APPID": "test-id",
            "QQ_BOT_SECRET": "test-secret",
            "FISOCHAT_VIEW_USERNAME": "管理员",
            "FISOCHAT_VIEW_PASSWORD": "测试口令",
            "FISOCHAT_ADMIN_TOKEN": "local-token",
            "FISOCHAT_DB": str(Path(self.temporary.name) / "messages.db"),
        })
        self.recorder = ChatRecorderClient(self.config)
        self.addAsyncCleanup(self.recorder.close)
        await self.recorder.repository.initialize()
        self.client = TestClient(TestServer(self.recorder.web_application))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.qq_send = AsyncMock(side_effect=lambda **kw: {
            "id": f"bot-{self.qq_send.call_count}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.send_patch = patch.object(self.recorder.api, "post_group_message", self.qq_send)
        self.send_patch.start()
        self.addCleanup(self.send_patch.stop)

    async def capture(self, payload):
        socket = MonitoredBotWebSocket(
            {}, SimpleNamespace(parser={}),
            on_connected=lambda _resumed: None,
            on_disconnected=lambda _code, _message: None,
            on_group_message=self.recorder._handle_raw_group_message,
        )
        with patch("fisochat.interfaces.qq.gateway.BotWebSocket.on_message", new=AsyncMock()):
            await socket.on_message(None, json.dumps(payload))

    async def test_gateway_to_viewer_and_outbound_round_trip(self):
        message = event("incoming", content='<script>alert("x")</script>')
        await self.capture(message)
        await self.capture(message)
        self.assertEqual(len(await self.recorder.repository.recent("group-1")), 1)
        self.qq_send.assert_not_called()
        response = await self.client.get("/group-messages")
        self.assertEqual(response.status, 401)
        response = await self.client.get("/group-messages", headers=authorization())
        body = await response.text()
        self.assertEqual(response.status, 200)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>", body)
        self.assertNotIn("must-not-render", body)
        self.assertIn("引用文本", body)
        self.assertIn("https://example.com/photo.jpg", body)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', body).group(1)
        response = await self.client.post("/group-messages", headers=authorization(), data={
            "csrf_token": csrf, "group_openid": "group-1", "content": "管理员发送",
        }, allow_redirects=False)
        self.assertEqual(response.status, 303)
        self.assertIn("send=sent", response.headers["Location"])
        self.qq_send.assert_awaited_once()
        records = await self.recorder.repository.recent("group-1")
        self.assertEqual([record.content for record in records], ["管理员发送", message["d"]["content"]])
        self.assertTrue(records[0].is_bot)
        self.assertEqual(records[0].payload["origin"], "message_viewer")

    async def test_console_read_api_is_authenticated_and_only_returns_display_fields(self):
        await self.capture(event("incoming"))
        for route in ("/internal/groups", "/internal/group-messages?group=group-1"):
            self.assertEqual((await self.client.get(route)).status, 401)
        headers = {"Authorization": "Bearer local-token"}
        response = await self.client.get("/internal/groups", headers=headers)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["groups"][0]["group_openid"], "group-1")
        response = await self.client.get("/internal/group-messages?group=group-1", headers=headers)
        data = await response.json()
        self.assertEqual(data["messages"][0]["content"], "收到的群消息")
        self.assertEqual(data["messages"][0]["quotes"], ["引用文本"])
        self.assertNotIn("must-not-render", json.dumps(data))
        self.assertNotIn("payload", data["messages"][0])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_incoming_mentions_display_names_without_rewriting_stored_history(self):
        incoming = event("display-mentions", content='<@target> 和 <@!second>、<qqbot-at-user id="target" />，未知 <@unknown>，例子 &lt;@target&gt;')
        incoming["d"]["mentions"] = [
            {"id": "target", "member_openid": "target", "username": "小明<script>"},
            {"member_openid": "second", "username": "小红"},
        ]
        incoming["d"]["msg_elements"] = [{
            "content": "引用 <@target>",
            "msg_elements": [{
                "content": "嵌套 <@target>",
                "mentions": [{"id": "target", "username": "引用时的名字"}],
            }],
        }]
        await self.capture(incoming)
        headers = {"Authorization": "Bearer local-token"}
        response = await self.client.get("/internal/group-messages?group=group-1", headers=headers)
        shown = (await response.json())["messages"][0]
        expected = "@小明<script> 和 @小红、@小明<script>，未知 <@unknown>，例子 &lt;@target&gt;"
        self.assertEqual(shown["content"], expected)
        self.assertEqual(shown["quotes"], ["引用 @小明<script>", "嵌套 @引用时的名字"])
        response = await self.client.get("/internal/groups", headers=headers)
        group = (await response.json())["groups"][0]
        self.assertEqual(group["latest_content"], expected)
        self.assertNotIn("latest_payload", group)
        response = await self.client.get("/group-messages?group=group-1", headers=authorization())
        page = await response.text()
        self.assertIn("@小明&lt;script&gt;", page)
        self.assertIn("嵌套 @引用时的名字", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("&lt;@target&gt;", page)
        saved = (await self.recorder.repository.recent("group-1"))[0]
        self.assertEqual(saved.content, incoming["d"]["content"])
        self.assertEqual(saved.payload, incoming["d"])

    async def test_unresolved_historical_tags_remain_literal_and_names_stay_message_scoped(self):
        known = event("known-mention", content="<@target>")
        known["d"]["mentions"] = [{"id": "target", "username": "当前昵称"}]
        await self.capture(known)
        await self.recorder.repository.add_bot_message(
            message_id="old-send", group_openid="group-1", username="FisoChat", content="<@target>",
            message_type=0, sent_at=datetime.now(timezone.utc).isoformat(), payload={"content": "<@target>"},
        )
        other = event("other-group-mention", group="group-2", content="<@target>")
        other["d"]["mentions"] = [{"id": "target", "username": "其他群昵称"}]
        await self.capture(other)
        headers = {"Authorization": "Bearer local-token"}
        response = await self.client.get("/internal/group-messages?group=group-1", headers=headers)
        self.assertEqual([m["content"] for m in (await response.json())["messages"]], ["@当前昵称", "<@target>"])
        response = await self.client.get("/internal/group-messages?group=group-2", headers=headers)
        self.assertEqual((await response.json())["messages"][0]["content"], "@其他群昵称")

    async def test_console_incremental_pages_do_not_skip_large_message_bursts(self):
        for index in range(125):
            await self.capture(event(f"message-{index}"))
        headers = {"Authorization": "Bearer local-token"}
        first = await self.client.get("/internal/group-messages?group=group-1&after=1&limit=100", headers=headers)
        first_page = (await first.json())["messages"]
        second = await self.client.get(f"/internal/group-messages?group=group-1&after={first_page[-1]['record_id']}&limit=100", headers=headers)
        second_page = (await second.json())["messages"]
        self.assertEqual([message["record_id"] for message in first_page + second_page], list(range(2, 126)))
        older = await self.client.get("/internal/group-messages?group=group-1&before=5", headers=headers)
        self.assertEqual([message["record_id"] for message in (await older.json())["messages"]], [1, 2, 3, 4])

    async def test_console_sender_keys_are_stable_without_exposing_member_openids(self):
        first = event("first")
        second = event("second")
        second["d"]["author"]["member_openid"] = "another-member"
        renamed = event("renamed")
        renamed["d"]["author"]["username"] = "新的昵称"
        for payload in (first, second, renamed):
            await self.capture(payload)
        response = await self.client.get("/internal/group-messages?group=group-1", headers={"Authorization": "Bearer local-token"})
        records = (await response.json())["messages"]
        self.assertEqual(records[0]["sender_key"], records[2]["sender_key"])
        self.assertNotEqual(records[0]["sender_key"], records[1]["sender_key"])
        for record in records:
            self.assertNotIn("member_openid", record)
            self.assertNotIn(record["sender_key"], {"member-1", "another-member"})

    async def test_console_rejects_invalid_cursors_and_group_ids(self):
        headers = {"Authorization": "Bearer local-token"}
        for query in ("group=group-1&before=-1", "group=group-1&after=abc", "group=group-1&after=1&before=2", "group=group-1&limit=1000", "group=group-1&after=9999999999999999999", "group="):
            response = await self.client.get("/internal/group-messages?" + query, headers=headers)
            self.assertEqual(response.status, 400, query)

    async def test_selected_mentions_use_markdown_and_record_readable_names(self):
        first = event("mention-first")
        first["t"] = "GROUP_AT_MESSAGE_CREATE"
        second = event("mention-second")
        second["d"]["author"] = {"username": "王小明", "member_openid": "member-2"}
        await self.capture(first)
        await self.capture(second)
        console = ConsoleClient(str(self.client.make_url("/")), "local-token")
        await console.open()
        try:
            records = await console.messages("group-1")
            self.assertTrue(all(record["can_mention"] for record in records))
            content = "  @小明 和 @王小… 请看一下  "
            mentions = [
                {"record_id": records[0]["record_id"], "start": 2, "end": 5},
                {"record_id": records[1]["record_id"], "start": 8, "end": 12},
            ]
            for reply in (None, "mention-first"):
                result = await console.send("group-1", content, reply_to=reply, mentions=mentions)
                self.assertTrue(result["recorded"])
                request = self.qq_send.call_args.kwargs
                self.assertEqual(request["markdown"]["content"], '<qqbot-at-user id="member-1" /> 和 <qqbot-at-user id="member-2" /> 请看一下')
                self.assertEqual(request["msg_type"], 2)
                self.assertNotIn("content", request)
                self.assertEqual(request.get("msg_id"), reply)
                latest = (await console.messages("group-1"))[-1]
                self.assertEqual(latest["content"], "@小明 和 @王小明 请看一下")
                self.assertFalse(latest["can_mention"])
                self.assertNotIn("member-", json.dumps(latest))
        finally:
            await console.close()

    async def test_mention_tag_reaches_the_installed_qq_sdk_http_payload(self):
        incoming = event("mention-sdk")
        incoming["t"] = "GROUP_AT_MESSAGE_CREATE"
        await self.capture(incoming)
        self.send_patch.stop()
        response_data = {"id": "bot-mention-sdk", "timestamp": datetime.now(timezone.utc).isoformat()}
        with patch.object(self.recorder.api._http, "request", new=AsyncMock(return_value=response_data)) as http:
            for reply in (None, "mention-sdk"):
                with self.subTest(reply=reply):
                    http.reset_mock()
                    response = await self.client.post("/internal/group-messages", headers={"Authorization": "Bearer local-token"}, json={
                        "group_openid": "group-1", "content": "@小明 你好",
                        "reply_to_message_id": reply,
                        "mentions": [{"record_id": 1, "start": 0, "end": 3}],
                    })
                    self.assertEqual(response.status, 200)
                    http.assert_awaited_once()
                    wire = http.call_args.kwargs["json"]
                    self.assertEqual(wire["msg_type"], 2)
                    self.assertIsNone(wire["content"])
                    self.assertEqual(wire["markdown"], {"content": '<qqbot-at-user id="member-1" /> 你好'})
                    self.assertEqual(wire["msg_id"], reply)
        records = await self.recorder.repository.recent("group-1")
        self.assertEqual(records[0].content, "@小明 你好")

    async def test_mention_body_stays_literal_in_markdown(self):
        await self.capture(event("mention-formatting"))
        content = '# **原样** `@小明`\n![图片](https://example.com/a.png) <qqbot-at-user id="other" /> <@other> &lt; * _ ~ \\末尾'
        start = content.index("@小明")
        response = await self.client.post("/internal/group-messages", headers={"Authorization": "Bearer local-token"}, json={
            "group_openid": "group-1", "content": content,
            "mentions": [{"record_id": 1, "start": start, "end": start + 3}],
        })
        self.assertEqual(response.status, 200)
        wire = self.qq_send.call_args.kwargs
        self.assertEqual(wire["msg_type"], 2)
        self.assertEqual(wire["markdown"]["content"],
                         '\\# \\*\\*原样\\*\\* \\`<qqbot-at-user id="member-1" />\\`\n'
                         '\\!\\[图片\\]\\(https://example\\.com/a\\.png\\) '
                         '&lt;qqbot\\-at\\-user id="other" /&gt; &lt;@other&gt; &amp;lt; \\* \\_ \\~ \\\\末尾')
        saved = (await self.recorder.repository.recent("group-1"))[0]
        self.assertEqual(saved.content, content)
        self.assertEqual(saved.message_type, 2)

    async def test_unselected_at_text_still_uses_plain_text(self):
        content = '@小明 **原样** <qqbot-at-user id="other" />'
        response = await self.client.post("/internal/group-messages", headers={"Authorization": "Bearer local-token"}, json={
            "group_openid": "group-1", "content": content,
        })
        self.assertEqual(response.status, 200)
        self.assertEqual(self.qq_send.call_args.kwargs["msg_type"], 0)
        self.assertEqual(self.qq_send.call_args.kwargs["content"], content)
        self.assertNotIn("markdown", self.qq_send.call_args.kwargs)

    async def test_failed_mention_is_not_retried_as_literal_text_or_recorded(self):
        await self.capture(event("mention-failed"))
        self.qq_send.side_effect = ServerError("markdown rejected")
        response = await self.client.post("/internal/group-messages", headers={"Authorization": "Bearer local-token"}, json={
            "group_openid": "group-1", "content": "@小明 你好",
            "mentions": [{"record_id": 1, "start": 0, "end": 3}],
        })
        self.assertEqual(response.status, 502)
        self.assertEqual((await response.json())["error"]["code"], "qq_send_failed")
        self.qq_send.assert_awaited_once()
        self.assertEqual(self.qq_send.call_args.kwargs["msg_type"], 2)
        records = await self.recorder.repository.recent("group-1")
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].is_bot)

    async def test_mentions_allow_incoming_bots_and_exclude_own_sends(self):
        incoming = event("other-bot-message")
        incoming["d"]["author"] = {"username": "群助手", "member_openid": "other-bot", "bot": True}
        await self.capture(incoming)
        await self.recorder.repository.add_bot_message(
            message_id="own-message", group_openid="group-1", username="FisoChat", content="自己的消息",
            message_type=0, sent_at=datetime.now(timezone.utc).isoformat(), payload={},
        )
        headers = {"Authorization": "Bearer local-token"}
        response = await self.client.get("/internal/group-messages?group=group-1", headers=headers)
        records = (await response.json())["messages"]
        self.assertTrue(records[0]["is_bot"])
        self.assertTrue(records[0]["can_mention"])
        self.assertTrue(records[1]["is_bot"])
        self.assertFalse(records[1]["can_mention"])
        response = await self.client.post("/internal/group-messages", headers=headers, json={
            "group_openid": "group-1", "content": "@群助手 你好",
            "mentions": [{"record_id": records[0]["record_id"], "start": 0, "end": 4}],
        })
        self.assertEqual(response.status, 200)
        self.qq_send.assert_awaited_once()
        wire = self.qq_send.call_args.kwargs
        self.assertEqual(wire["msg_type"], 2)
        self.assertEqual(wire["markdown"]["content"], '<qqbot-at-user id="other-bot" /> 你好')
        self.assertEqual((await self.recorder.repository.recent("group-1"))[0].content, "@群助手 你好")
        self.qq_send.reset_mock()
        response = await self.client.post("/internal/group-messages", headers=headers, json={
            "group_openid": "group-1", "content": "@自己",
            "mentions": [{"record_id": records[1]["record_id"], "start": 0, "end": 3}],
        })
        self.assertEqual(response.status, 400)
        self.qq_send.assert_not_called()

    async def test_mentions_reject_other_groups_own_sends_and_unavailable_members(self):
        await self.capture(event("valid-member"))
        await self.capture(event("other-member", group="group-2"))
        missing = event("missing-member-id")
        missing["d"]["author"].pop("member_openid")
        await self.capture(missing)
        await self.recorder.repository.add_bot_message(
            message_id="existing-bot", group_openid="group-1", username="Bot", content="hello",
            message_type=0, sent_at=datetime.now(timezone.utc).isoformat(), payload={},
        )
        for record_id in (2, 3, 4, 9999):
            response = await self.client.post("/internal/group-messages", headers={"Authorization": "Bearer local-token"}, json={
                "group_openid": "group-1", "content": "@小明 hello",
                "mentions": [{"record_id": record_id, "start": 0, "end": 3}],
            })
            self.assertEqual(response.status, 400)
        self.qq_send.assert_not_called()

    async def test_mentions_validate_spans_and_expanded_message_length(self):
        await self.capture(event("valid-member"))
        valid = {"record_id": 1, "start": 0, "end": 3}
        invalid = [None, "member-1", [True], [dict(valid, start=True)], [dict(valid, record_id=True)],
                   [dict(valid, start=-1)], [dict(valid, end=999)], [dict(valid, end=0)],
                   [dict(valid, start=1)], [dict(valid, extra="value")], [valid, valid], [valid] * 21]
        for mentions in invalid:
            response = await self.client.post("/internal/group-messages", headers={"Authorization": "Bearer local-token"}, json={
                "group_openid": "group-1", "content": "@小明 hello", "mentions": mentions,
            })
            self.assertEqual(response.status, 400, mentions)
        response = await self.client.post("/internal/group-messages", headers={"Authorization": "Bearer local-token"}, json={
            "group_openid": "group-1", "content": "@小明" + "x" * 1997, "mentions": [valid],
        })
        self.assertEqual(response.status, 400)
        self.qq_send.assert_not_called()

    async def test_console_http_transport_reads_and_sends_through_existing_service(self):
        await self.capture(event("transport-message"))
        console = ConsoleClient(str(self.client.make_url("/")), "local-token")
        await console.open()
        try:
            self.assertEqual((await console.groups())[0]["group_openid"], "group-1")
            self.assertEqual((await console.messages("group-1"))[0]["message_id"], "transport-message")
            self.assertFalse((await console.health())["qq_gateway"]["connected"])
            sent = await console.send("group-1", "终端接口联调")
            self.assertTrue(sent["recorded"])
            self.qq_send.assert_awaited_once()
            self.assertEqual((await console.messages("group-1", after=1))[0]["content"], "终端接口联调")
        finally:
            await console.close()
        denied = ConsoleClient(str(self.client.make_url("/")), "wrong-token")
        await denied.open()
        try:
            with self.assertRaisesRegex(ConsoleError, "Token"):
                await denied.groups()
        finally:
            await denied.close()

    async def test_pagination_stays_in_selected_group(self):
        for index in range(55):
            await self.recorder.repository.add_gateway_event("GROUP_MESSAGE_CREATE", event(f"m{index}"))
        await self.capture(event("another", group="other-group", content="另一群记录"))
        response = await self.client.get("/group-messages?group=group-1", headers=authorization())
        body = await response.text()
        self.assertEqual(body.count('<article class="message">'), 50)
        self.assertIn("查看更早消息", body)
        before = re.search(r'group=group-1&amp;before=(\d+)', body).group(1)
        older = await self.client.get(f"/group-messages?group=group-1&before={before}", headers=authorization())
        self.assertEqual((await older.text()).count('<article class="message">'), 5)

    async def test_invalid_auth_csrf_and_group_do_not_send(self):
        await self.capture(event("m1"))
        for token in ("wrong", "非ASCII令牌"):
            response = await self.client.post("/group-messages", headers=authorization(), data={
                "csrf_token": token, "group_openid": "group-1", "content": "消息",
            })
            self.assertEqual(response.status, 403)
        response = await self.client.get("/group-messages", headers=authorization(password="错误"))
        self.assertEqual(response.status, 401)
        page = await self.client.get("/group-messages", headers=authorization())
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', await page.text()).group(1)
        response = await self.client.post("/group-messages", headers=authorization(), data={
            "csrf_token": csrf, "group_openid": "unknown", "content": "消息",
        }, allow_redirects=False)
        self.assertIn("invalid_group", response.headers["Location"])
        self.qq_send.assert_not_called()

    async def test_admin_reply_uses_recorded_context_and_increments_sequence(self):
        message = event("question")
        message["t"] = "GROUP_AT_MESSAGE_CREATE"
        await self.capture(message)
        headers = {"Authorization": "Bearer local-token"}
        for sequence in (1, 2):
            response = await self.client.post("/internal/group-messages", headers=headers, json={
                "group_openid": "group-1", "reply_to_message_id": "question", "content": "指定回复",
            })
            self.assertEqual(response.status, 200)
            self.assertTrue((await response.json())["recorded"])
            self.assertEqual(self.qq_send.call_args.kwargs["msg_seq"], sequence)
        response = await self.client.post("/internal/group-messages", headers=headers, json={
            "group_openid": "another-group", "reply_to_message_id": "question", "content": "禁止串群",
        })
        self.assertEqual(response.status, 409)
        self.assertEqual(self.qq_send.call_count, 2)

    async def test_cli_calls_local_api_and_records_result(self):
        endpoint = str(self.client.make_url("/internal/group-messages"))
        output = io.StringIO()
        with patch.dict(os.environ, {"FISOCHAT_ADMIN_TOKEN": "local-token"}, clear=True), redirect_stdout(output):
            result = await asyncio.to_thread(send_main, [
                "--env-file", str(Path(self.temporary.name) / "absent.env"),
                "--endpoint", endpoint, "--group", "group-1", "--text", "命令行消息",
            ])
        self.assertEqual(result, 0)
        self.assertIn("发送成功", output.getvalue())
        record = (await self.recorder.repository.recent("group-1"))[0]
        self.assertEqual(record.content, "命令行消息")
        self.assertEqual(record.payload["origin"], "console")

    async def test_qq_error_does_not_create_a_record_or_retry(self):
        self.qq_send.side_effect = TimeoutError("unknown delivery outcome")
        response = await self.client.post("/internal/group-messages", headers={"Authorization": "Bearer local-token"}, json={
            "group_openid": "group-1", "content": "消息",
        })
        self.assertEqual(response.status, 502)
        self.qq_send.assert_awaited_once()
        self.assertEqual(await self.recorder.repository.recent("group-1"), ())

    async def test_recording_failure_reports_sent_without_retry(self):
        await self.capture(event("m1"))
        page = await self.client.get("/group-messages", headers=authorization())
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', await page.text()).group(1)
        with patch.object(self.recorder.repository, "add_bot_message", side_effect=OSError):
            response = await self.client.post("/group-messages", headers=authorization(), data={
                "csrf_token": csrf, "group_openid": "group-1", "content": "消息",
            }, allow_redirects=False)
        self.assertIn("send=sent_unrecorded", response.headers["Location"])
        self.qq_send.assert_awaited_once()

    async def test_gateway_health_transitions_and_reconnect_cancels_watchdog(self):
        self.assertEqual((await self.client.get("/health")).status, 503)
        self.recorder._mark_gateway_connected(False)
        self.assertEqual((await self.client.get("/health")).status, 200)
        self.recorder._mark_gateway_disconnected(4009, "disconnected")
        watchdog = self.recorder._gateway_watchdog
        self.assertEqual((await self.client.get("/health")).status, 503)
        self.recorder._mark_gateway_connected(True)
        await asyncio.gather(watchdog, return_exceptions=True)
        self.assertTrue(watchdog.cancelled())
        self.assertIsNone(self.recorder._gateway_watchdog)

    async def test_web_only_hides_composer_and_blocks_all_sending(self):
        await self.capture(event("m1"))
        application = create_read_only_application(self.config)
        async with TestClient(TestServer(application)) as client:
            response = await client.get("/group-messages", headers=authorization())
            body = await response.text()
            self.assertIn("收到的群消息", body)
            self.assertIn("只读模式", body)
            self.assertNotIn('<textarea', body)
            self.assertEqual((await client.post("/group-messages", headers=authorization())).status, 503)
            self.assertEqual((await client.post("/internal/group-messages")).status, 404)
            health = await client.get("/health")
            self.assertEqual(health.status, 200)
            self.assertEqual((await health.json())["mode"], "web_only")
        self.qq_send.assert_not_called()

    async def test_http_service_starts_before_qq_login_and_closes_on_failure(self):
        client = ChatRecorderClient(replace(self.config, web_port=0))

        async def failed_login(*_args, **_kwargs):
            self.assertTrue(client.repository.is_open)
            self.assertIsNotNone(client._web_runner)
            raise RuntimeError("login failed")

        with patch("botpy.Client.start", side_effect=failed_login):
            with self.assertRaisesRegex(RuntimeError, "login failed"):
                async with client:
                    await client.start("fake-id", "fake-secret")
        self.assertFalse(client.repository.is_open)
        self.assertTrue(client.is_closed())
        self.assertIsNone(client._web_runner)


if __name__ == "__main__":
    unittest.main()
