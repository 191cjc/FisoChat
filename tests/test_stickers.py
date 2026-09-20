import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

from aiohttp import web
from multidict import MultiDict
from PIL import Image
from textual.widgets import ListView, Static

from fisochat.console import FisoChatApp, ImageScreen, StickerPicker
from fisochat.console_client import ConsoleError
from fisochat.console_commands import CommandInput
from fisochat.database.models import StoredGroupMessage
from fisochat.interfaces.web.admin_messages import AdminMessageHandler
from fisochat.logic.models import BotSentGroupMessage
from fisochat.services.images import MAX_IMAGE_BYTES, ImageError, inspect_sticker
from fisochat.services.stickers import (
    StickerError,
    StickerNotFound,
    StickerSigner,
    StickerStore,
)
from tests.test_console import FakeClient, message


def encoded_image(image_format="PNG", size=(24, 16)):
    output = BytesIO()
    with Image.new("RGB", size, "#19a974") as image:
        image.save(output, format=image_format)
    return output.getvalue()


def incoming_record(*, bot=False, recalled=""):
    return StoredGroupMessage(
        record_id=7,
        message_id="incoming-7",
        event_id="event-7",
        event_type="GROUP_MESSAGE_CREATE",
        group_openid="group-a",
        member_openid="member-a",
        username="小明",
        member_role="member",
        is_bot=bot,
        content="[图片]",
        message_type=7,
        sent_at="2026-09-17T12:00:00+08:00",
        received_at="2026-09-17T12:00:01+08:00",
        payload={"attachments": [
            {"filename": "one.png", "content_type": "image/png", "url": "https://images.example/one"},
            {"filename": "two.jpg", "content_type": "image/jpeg", "url": "https://images.example/two"},
        ]},
        recalled_at=recalled,
    )


class FakeRequest:
    def __init__(
        self,
        payload=None,
        *,
        token="secret",
        remote="127.0.0.1",
        sticker_id="",
        query=None,
    ):
        self._payload = payload
        self.headers = {"Authorization": f"Bearer {token}"}
        self.remote = remote
        self.match_info = {"sticker_id": sticker_id}
        self.query = MultiDict(query or {})

    async def json(self):
        return self._payload


class FakeRepository:
    def __init__(self, record=None):
        self.record = record
        self.lookups = []

    async def get_by_record_id(self, group_id, record_id):
        self.lookups.append((group_id, record_id))
        if self.record and self.record.group_openid == group_id and self.record.record_id == record_id:
            return self.record
        return None


class FakeSender:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def send_proactive_image(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return BotSentGroupMessage(
            kwargs["group_id"], "sent-sticker", datetime.now(timezone.utc), True
        )


class StickerStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "stickers"
        self.store = StickerStore(self.root)
        await self.store.initialize()

    async def test_private_atomic_content_addressed_storage_and_restart(self):
        data = encoded_image()
        expected = hashlib.sha256(data).hexdigest()
        results = await asyncio.gather(*(self.store.save(data) for _ in range(4)))
        self.assertEqual({result[0].id for result in results}, {expected})
        self.assertEqual(sum(not duplicate for _, duplicate in results), 1)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        files = [path for path in self.root.iterdir() if not path.name.startswith(".sticker-")]
        self.assertEqual([path.name for path in files], [expected + ".png"])
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        restarted = StickerStore(self.root)
        await restarted.initialize()
        self.assertEqual((await restarted.list())[0].id, expected)

    async def test_formats_limits_invalid_entries_symlinks_and_manual_deletion(self):
        jpeg, _ = await self.store.save(encoded_image("JPEG"))
        self.assertEqual(jpeg.content_type, "image/jpeg")
        with self.assertRaises(StickerError):
            await self.store.save(encoded_image("GIF"))
        with self.assertRaises(StickerError):
            await self.store.save(encoded_image("PNG", (5000, 5000)))
        (self.root / "not-managed.png").write_bytes(encoded_image())
        wrong = self.root / ("0" * 64 + ".png")
        wrong.write_bytes(encoded_image())
        symlink = self.root / ("1" * 64 + ".png")
        symlink.symlink_to(self.root / jpeg.filename)
        self.assertEqual([item.id for item in await self.store.list()], [jpeg.id])
        (self.root / jpeg.filename).unlink()
        self.assertEqual(await self.store.list(), ())
        with self.assertRaises(StickerNotFound):
            await self.store.get(jpeg.id)

    async def test_png_and_jpeg_only_inspection(self):
        self.assertEqual(inspect_sticker(encoded_image()).format, "PNG")
        self.assertEqual(inspect_sticker(encoded_image("JPEG")).format, "JPEG")
        with self.assertRaises(ImageError):
            inspect_sticker(encoded_image("WEBP"))
        with self.assertRaises(ImageError):
            inspect_sticker(b"not an image")

    async def test_oversized_valid_image_is_rejected_without_residual_file(self):
        original = encoded_image()
        oversized = original + b"x" * (MAX_IMAGE_BYTES + 1 - len(original))
        with self.assertRaises(StickerError) as raised:
            await self.store.save(oversized)
        self.assertEqual(raised.exception.code, "too_large")
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_symlinked_parent_and_runtime_root_replacement_are_rejected(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        linked_parent = Path(self.temporary.name) / "linked-parent"
        linked_parent.symlink_to(outside, target_is_directory=True)
        linked_store = StickerStore(linked_parent / "stickers")
        with self.assertRaises(StickerError) as linked:
            await linked_store.initialize()
        self.assertEqual(linked.exception.code, "invalid_sticker_directory")

        moved_root = Path(self.temporary.name) / "original-stickers"
        self.root.rename(moved_root)
        self.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(StickerError) as replaced:
            await self.store.save(encoded_image())
        self.assertEqual(replaced.exception.code, "invalid_sticker_directory")
        self.assertEqual(list(outside.iterdir()), [])


class StickerSignerTests(unittest.TestCase):
    def test_signature_is_short_lived_domain_separated_and_tamper_evident(self):
        clock = [1_700_000_000]
        sticker_id = "a" * 64
        signer = StickerSigner(
            "https://example.com/fisochat", "secret" * 8, clock=lambda: clock[0]
        )
        url = signer.signed_url(sticker_id)
        self.assertTrue(url.startswith(
            f"https://example.com/fisochat/stickers/{sticker_id}?expires=1700000300&signature="
        ))
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        self.assertTrue(signer.validate(sticker_id, query["expires"], query["signature"]))
        self.assertFalse(signer.validate("b" * 64, query["expires"], query["signature"]))
        self.assertFalse(signer.validate(sticker_id, query["expires"], "A" * 43))
        clock[0] += 301
        self.assertFalse(signer.validate(sticker_id, query["expires"], query["signature"]))


class StickerHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = StickerStore(Path(self.temporary.name) / "stickers")
        await self.store.initialize()
        self.sender = FakeSender()
        self.download = AsyncMock(return_value=encoded_image())
        self.signer = StickerSigner(
            "https://example.com/fisochat", "secret" * 8, clock=lambda: 1_700_000_000
        )
        self.handler = AdminMessageHandler(
            FakeRepository(incoming_record()),
            self.sender,
            token="secret",
            sticker_store=self.store,
            sticker_signer=self.signer,
            image_downloader=self.download,
        )

    async def test_save_resolves_record_and_index_then_deduplicates(self):
        payload = {"group_openid": "group-a", "record_id": 7, "attachment_index": 2}
        first = await self.handler.save_sticker(FakeRequest(payload))
        second = await self.handler.save_sticker(FakeRequest(payload))
        self.assertEqual(first.status, 200)
        self.assertFalse(json.loads(first.text)["duplicate"])
        self.assertTrue(json.loads(second.text)["duplicate"])
        self.assertEqual(self.download.await_args_list[0].args, ("https://images.example/two",))
        self.assertEqual(len(await self.store.list()), 1)

    async def test_save_rejects_arbitrary_urls_bot_records_and_unsupported_data(self):
        payload = {
            "group_openid": "group-a", "record_id": 7, "attachment_index": 1,
            "url": "https://attacker.example/image.png",
        }
        self.assertEqual((await self.handler.save_sticker(FakeRequest(payload))).status, 400)
        self.handler._repository.record = incoming_record(bot=True)
        payload.pop("url")
        self.assertEqual((await self.handler.save_sticker(FakeRequest(payload))).status, 409)
        self.handler._repository.record = incoming_record()
        self.download.return_value = encoded_image("GIF")
        response = await self.handler.save_sticker(FakeRequest(payload))
        self.assertEqual(response.status, 422)
        self.assertEqual(await self.store.list(), ())

    async def test_save_maps_invalid_and_oversized_images_to_validation_errors(self):
        payload = {"group_openid": "group-a", "record_id": 7, "attachment_index": 1}
        for data, code in (
            (b"not an image", "invalid_image"),
            (encoded_image() + b"x" * MAX_IMAGE_BYTES, "too_large"),
        ):
            with self.subTest(code=code):
                self.download.return_value = data
                response = await self.handler.save_sticker(FakeRequest(payload))
                self.assertEqual(response.status, 422)
                self.assertEqual(json.loads(response.text)["error"]["code"], code)
        self.assertEqual(await self.store.list(), ())

    async def test_authenticated_list_preview_send_and_public_retrieval(self):
        sticker, _ = await self.store.save(encoded_image())
        self.assertEqual((await self.handler.list_stickers(FakeRequest())).status, 200)
        self.assertEqual(
            (await self.handler.preview_sticker(
                FakeRequest(sticker_id=sticker.id)
            )).headers["X-Content-Type-Options"],
            "nosniff",
        )
        sent = await self.handler.send_sticker(FakeRequest(
            {"group_openid": "group-b"}, sticker_id=sticker.id
        ))
        self.assertEqual(sent.status, 200)
        self.assertEqual(len(self.sender.calls), 1)
        call = self.sender.calls[0]
        self.assertEqual(call["group_id"], "group-b")
        self.assertEqual(call["sticker_id"], sticker.id)
        self.assertIn("expires=", call["public_url"])
        query = dict(part.split("=", 1) for part in call["public_url"].split("?", 1)[1].split("&"))
        public = await self.handler.public_sticker(FakeRequest(
            sticker_id=sticker.id, query=query
        ))
        self.assertEqual(public.body, encoded_image())
        self.assertEqual(public.headers["Cache-Control"], "no-store")
        with self.assertRaises(web.HTTPNotFound):
            await self.handler.public_sticker(FakeRequest(sticker_id=sticker.id))

    async def test_manual_deletion_and_ambiguous_send_do_not_retry(self):
        sticker, _ = await self.store.save(encoded_image())
        (self.store.root / sticker.filename).unlink()
        missing = await self.handler.send_sticker(FakeRequest(
            {"group_openid": "group-a"}, sticker_id=sticker.id
        ))
        self.assertEqual(missing.status, 404)
        self.assertEqual(self.sender.calls, [])
        sticker, _ = await self.store.save(encoded_image())
        self.sender.error = TimeoutError("unknown outcome")
        failed = await self.handler.send_sticker(FakeRequest(
            {"group_openid": "group-a"}, sticker_id=sticker.id
        ))
        self.assertEqual(failed.status, 502)
        self.assertEqual(len(self.sender.calls), 1)
        self.assertIn("不要直接重试", json.loads(failed.text)["error"]["message"])


def image_message(record_id=80):
    return dict(message(record_id), attachments=[
        {"filename": "one.png", "content_type": "image/png", "url": "https://images.example/one"}
    ])


class StickerConsoleClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.records["group-a"][-1] = image_message()
        self.library = [{
            "id": "a" * 64,
            "filename": "a" * 64 + ".png",
            "content_type": "image/png",
            "size": len(encoded_image()),
            "saved_at": "2026-09-17T12:00:00+00:00",
        }]
        self.saved = []
        self.sticker_sends = []
        self.sticker_error = None

    async def save_sticker(self, group, record_id, attachment_index):
        self.saved.append((group, record_id, attachment_index))
        return {"ok": True, "duplicate": len(self.saved) > 1, "sticker": self.library[0]}

    async def stickers(self):
        return deepcopy(self.library)

    async def sticker_image(self, sticker_id):
        if self.sticker_error:
            raise self.sticker_error
        return encoded_image()

    async def send_sticker(self, group, sticker_id):
        self.sticker_sends.append((group, sticker_id))
        if self.sticker_error:
            raise self.sticker_error
        return {"ok": True, "recorded": True, "message_id": "sticker-send"}


class StickerConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_save_and_duplicate_notice_preserve_conversation(self):
        client = StickerConsoleClient()
        app = FisoChatApp(client, image_mode="blocks")
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            composer = app.query_one(CommandInput)
            composer.value = "保留草稿"
            await app.command("/image 80")
            self.assertIsInstance(app.screen, ImageScreen)
            await pilot.press("shift+s")
            await pilot.pause()
            self.assertEqual(client.saved, [("group-a", 80, 1)])
            self.assertIn("已收藏", str(app.screen.query_one("#image-save-status", Static).render()))
            await pilot.press("s")
            await pilot.pause()
            self.assertEqual(client.saved, [
                ("group-a", 80, 1),
                ("group-a", 80, 1),
            ])
            self.assertIn("已在表情库", str(app.screen.query_one("#image-save-status", Static).render()))
            await pilot.press("escape")
            self.assertEqual(composer.value, "保留草稿")

    async def test_global_picker_previews_and_sends_to_active_group(self):
        client = StickerConsoleClient()
        app = FisoChatApp(client, image_mode="blocks")
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            await app.command("/use 2")
            await app.command("/stickers")
            self.assertIsInstance(app.screen, StickerPicker)
            await pilot.pause()
            self.assertIsNotNone(app.screen.preview)
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(client.sticker_sends, [("group-b", "a" * 64)])
            self.assertNotIsInstance(app.screen, StickerPicker)

    async def test_empty_sticker_picker_can_be_closed(self):
        client = StickerConsoleClient()
        client.library = []
        app = FisoChatApp(client, image_mode="blocks")
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            await app.command("/stickers")
            await pilot.pause()
            self.assertIsInstance(app.screen, StickerPicker)
            self.assertIn("表情库为空", str(app.screen.query_one("#empty-stickers", Static).render()))
            await pilot.press("escape")
            self.assertNotIsInstance(app.screen, StickerPicker)

    async def test_ambiguous_sticker_failure_stays_open_without_retry(self):
        client = StickerConsoleClient()
        client.sticker_error = ConsoleError(
            "发送连接中断，结果尚未确认。请检查群消息记录后再决定是否重发。"
        )
        app = FisoChatApp(client, image_mode="blocks")
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            await app.command("/stickers")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, StickerPicker)
            self.assertIn("结果尚未确认", str(app.screen.query_one("#sticker-status", Static).render()))
            self.assertEqual(len(client.sticker_sends), 1)

    async def test_deleted_sticker_refreshes_picker_without_retry(self):
        client = StickerConsoleClient()
        client.sticker_error = ConsoleError(
            "表情不存在或已被手动删除。", code="sticker_not_found"
        )
        client.library = []
        app = FisoChatApp(client, image_mode="blocks")
        async with app.run_test(size=(90, 30)) as pilot:
            await pilot.pause()
            picker = StickerPicker([
                {
                    "id": "a" * 64,
                    "filename": "a" * 64 + ".png",
                    "content_type": "image/png",
                    "size": len(encoded_image()),
                    "saved_at": "2026-09-17T12:00:00+00:00",
                }
            ], client, "group-a", mode="blocks")
            app.push_screen(picker)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertIs(app.screen, picker)
            self.assertEqual(len(picker.query_one("#stickers", ListView).children), 0)
            self.assertIn("列表已刷新", str(picker.query_one("#sticker-status", Static).render()))
            self.assertEqual(len(client.sticker_sends), 1)


if __name__ == "__main__":
    unittest.main()
