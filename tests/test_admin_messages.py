import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fisochat.database.models import StoredGroupMessage
from fisochat.interfaces.web.admin_messages import AdminMessageHandler, _can_mention
from fisochat.logic.models import BotSentGroupMessage, GroupReplyContext


class FakeRequest:
    def __init__(self, payload, *, token="secret", remote="127.0.0.1"):
        self._payload = payload
        self.headers = {"Authorization": f"Bearer {token}"}
        self.remote = remote

    async def json(self):
        return self._payload


class FakeRepository:
    def __init__(self, context):
        self.context = context
        self.calls = []

    async def find_console_reply_context(self, group_id, *, message_id=None):
        self.calls.append((group_id, message_id))
        return self.context


class FakeSender:
    def __init__(self):
        self.calls = []
        self.proactive_calls = []

    async def send_text_reply(self, **kwargs):
        self.calls.append(kwargs)
        return BotSentGroupMessage(
            kwargs["group_id"],
            "bot-result",
            datetime.now(timezone.utc),
            True,
        )

    async def send_proactive_text(self, **kwargs):
        self.proactive_calls.append(kwargs)
        return BotSentGroupMessage(
            kwargs["group_id"],
            "bot-proactive",
            datetime.now(timezone.utc),
            True,
        )


class AdminMessageHandlerTests(unittest.IsolatedAsyncioTestCase):
    def context(self):
        return GroupReplyContext(
            "group-1",
            "user-message",
            2,
            datetime.now(timezone.utc) + timedelta(minutes=4),
        )

    async def test_valid_request_uses_context_and_console_origin(self):
        repository = FakeRepository(self.context())
        sender = FakeSender()
        handler = AdminMessageHandler(
            repository, sender, token="secret",
            sticker_store=object(), sticker_signer=object(),
        )
        response = await handler.send_group_message(
            FakeRequest(
                {
                    "group_openid": "group-1",
                    "content": " manual message ",
                    "reply_to_message_id": "user-message",
                }
            )
        )

        self.assertEqual(response.status, 200)
        body = json.loads(response.text)
        self.assertEqual(body["message_id"], "bot-result")
        self.assertEqual(sender.calls[0]["source_message_id"], "user-message")
        self.assertEqual(sender.calls[0]["msg_seq"], 2)
        self.assertEqual(sender.calls[0]["origin"], "console")

    async def test_opaque_reply_id_is_preserved_through_lookup_and_send(self):
        message_id = "A" * 60 + "." + "b" * 60 + "!opaque-id"
        context = GroupReplyContext(
            "group-1",
            message_id,
            1,
            datetime.now(timezone.utc) + timedelta(minutes=4),
        )
        repository = FakeRepository(context)
        sender = FakeSender()
        handler = AdminMessageHandler(
            repository, sender, token="secret",
            sticker_store=object(), sticker_signer=object(),
        )

        response = await handler.send_group_message(FakeRequest({
            "group_openid": "group-1",
            "content": "reply",
            "reply_to_message_id": message_id,
        }))

        self.assertEqual(response.status, 200)
        self.assertEqual(repository.calls, [("group-1", message_id)])
        self.assertEqual(sender.calls[0]["source_message_id"], message_id)

    async def test_invalid_reply_ids_fail_before_lookup_or_send(self):
        invalid_values = (
            None,
            123,
            "",
            "with space",
            "with\tspace",
            "control\0",
            "x" * 257,
        )
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                repository = FakeRepository(self.context())
                sender = FakeSender()
                handler = AdminMessageHandler(
                    repository, sender, token="secret",
                    sticker_store=object(), sticker_signer=object(),
                )

                response = await handler.send_group_message(FakeRequest({
                    "group_openid": "group-1",
                    "content": "reply",
                    "reply_to_message_id": value,
                }))

                self.assertEqual(response.status, 400)
                self.assertEqual(
                    json.loads(response.text)["error"]["code"],
                    "invalid_reply_context",
                )
                self.assertEqual(repository.calls, [])
                self.assertEqual(sender.calls, [])
                self.assertEqual(sender.proactive_calls, [])

    def test_member_openid_validation_remains_restrictive(self):
        common = {
            "record_id": 1,
            "message_id": "opaque.message!id",
            "event_id": "event-1",
            "event_type": "GROUP_MESSAGE_CREATE",
            "group_openid": "group-1",
            "username": "member",
            "member_role": "member",
            "is_bot": False,
            "content": "hello",
            "message_type": 0,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "received_at": datetime.now(timezone.utc).isoformat(),
            "payload": {},
        }
        self.assertTrue(
            _can_mention(
                StoredGroupMessage(member_openid="member-openid_1", **common)
            )
        )
        self.assertFalse(
            _can_mention(
                StoredGroupMessage(member_openid="member.openid!", **common)
            )
        )

    async def test_auth_and_loopback_are_required(self):
        handler = AdminMessageHandler(
            FakeRepository(self.context()), FakeSender(), token="secret",
            sticker_store=object(), sticker_signer=object(),
        )
        unauthorized = await handler.send_group_message(
            FakeRequest({}, token="wrong")
        )
        remote = await handler.send_group_message(
            FakeRequest({}, remote="203.0.113.4")
        )
        self.assertEqual(unauthorized.status, 401)
        self.assertEqual(remote.status, 403)

    async def test_missing_reply_id_sends_a_proactive_group_message(self):
        repository = FakeRepository(None)
        sender = FakeSender()
        handler = AdminMessageHandler(
            repository, sender, token="secret",
            sticker_store=object(), sticker_signer=object(),
        )

        response = await handler.send_group_message(
            FakeRequest({"group_openid": "group-1", "content": " hello "})
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(repository.calls, [])
        self.assertEqual(sender.calls, [])
        self.assertEqual(
            sender.proactive_calls,
            [{"group_id": "group-1", "content": "hello", "origin": "console"}],
        )

    async def test_missing_context_fails_without_sending(self):
        sender = FakeSender()
        handler = AdminMessageHandler(
            FakeRepository(None), sender, token="secret",
            sticker_store=object(), sticker_signer=object(),
        )
        response = await handler.send_group_message(
            FakeRequest(
                {
                    "group_openid": "group-1",
                    "content": "hello",
                    "reply_to_message_id": "missing-message",
                }
            )
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(sender.calls, [])
        self.assertEqual(sender.proactive_calls, [])


if __name__ == "__main__":
    unittest.main()
