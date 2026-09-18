import asyncio
import socket
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image
from textual.widgets import Static
from textual_image.widget import HalfcellImage

from fisochat.console import FisoChatApp, GroupPicker, ImageScreen, message_text
from fisochat.console_client import ConsoleError
from fisochat.console_commands import CommandInput
from fisochat.console_images import (
    PublicImageResolver, decode_image, fetch_image, image_attachments,
)
from tests.test_console import FakeClient, message


def png(size=(80, 40)):
    data = BytesIO()
    with Image.new("RGB", size, "#7dd3c7") as image:
        image.save(data, format="PNG")
    return data.getvalue()


def image_message(record_id=80):
    return dict(message(record_id), attachments=[
        {"filename": "first.png", "content_type": "image/png", "url": "https://images.example.com/first"},
        {"filename": "file.txt", "content_type": "text/plain", "url": "https://images.example.com/file.txt"},
        {"filename": "second.PNG", "url": "https://images.example.com/second"},
    ])


class ImageDecodeTests(unittest.TestCase):
    def test_image_hints_use_mime_or_extension_and_preserve_links(self):
        record = image_message()
        self.assertEqual(len(image_attachments(record)), 2)
        self.assertIn("/image 80", message_text(record).plain)
        self.assertIn("https://images.example.com/first", message_text(record).plain)
        self.assertNotIn("/image", message_text(message(1)).plain)

    def test_decode_preserves_aspect_and_bounds_preview_size(self):
        result = decode_image(png((2400, 600)))
        self.assertEqual((result.width, result.height), (2400, 600))
        self.assertEqual(result.image.size, (1600, 400))
        self.assertEqual(result.image.mode, "RGB")
        self.assertFalse(result.animated)
        result.image.close()

    def test_camera_orientation_transparency_and_animation(self):
        data = BytesIO()
        with Image.new("RGB", (80, 40), "red") as source:
            exif = Image.Exif()
            exif[274] = 6
            source.save(data, format="JPEG", exif=exif)
        result = decode_image(data.getvalue())
        self.assertEqual((result.width, result.height), (40, 80))
        result.image.close()
        data = BytesIO()
        with Image.new("RGBA", (10, 10), (255, 255, 255, 0)) as source:
            source.save(data, format="PNG")
        result = decode_image(data.getvalue())
        self.assertEqual(result.image.getpixel((0, 0)), (22, 29, 38))
        result.image.close()
        data = BytesIO()
        with Image.new("RGB", (10, 10), "red") as first, Image.new("RGB", (10, 10), "blue") as second:
            first.save(data, format="GIF", save_all=True, append_images=[second])
        result = decode_image(data.getvalue())
        self.assertTrue(result.animated)
        self.assertEqual(result.image.getpixel((0, 0)), (255, 0, 0))
        result.image.close()

    def test_invalid_and_excessive_images_are_reported(self):
        for data in [b"not an image", b"<svg></svg>", png()[:20]]:
            with self.subTest(data=data[:10]), self.assertRaises(ConsoleError):
                decode_image(data)
        with patch("fisochat.console_images.MAX_IMAGE_PIXELS", 100), self.assertRaises(ConsoleError):
            decode_image(png())


class ImageDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.data = png()

        async def route(request):
            self.requests.append((request.path, dict(request.headers)))
            if request.path == "/redirect":
                raise web.HTTPFound("/image", headers={"Set-Cookie": "private=secret"})
            if request.path == "/private":
                raise web.HTTPFound("http://127.0.0.1/private")
            if request.path == "/loop":
                raise web.HTTPFound("/loop")
            if request.path == "/expired":
                raise web.HTTPForbidden()
            if request.path == "/broken":
                return web.Response(text="not an image")
            if request.path == "/stream":
                response = web.StreamResponse()
                await response.prepare(request)
                await response.write(self.data)
                await response.write_eof()
                return response
            return web.Response(body=self.data, content_type="image/png")

        app = web.Application()
        app.router.add_get("/{name}", route)
        self.server = TestServer(app)
        await self.server.start_server()
        self.url = f"http://images.example.com:{self.server.port}"

        async def resolve(host, port=0, family=socket.AF_INET):
            return [{"hostname": host, "host": "127.0.0.1", "port": port,
                     "family": socket.AF_INET, "proto": 0, "flags": 0}]

        self.resolver_patch = patch.object(PublicImageResolver, "resolve", side_effect=resolve)
        self.resolver_patch.start()

    async def asyncTearDown(self):
        self.resolver_patch.stop()
        await self.server.close()

    async def test_real_download_and_redirect_send_no_credentials_or_cookies(self):
        result = await fetch_image(self.url + "/redirect")
        self.assertEqual(result.image.size, (80, 40))
        result.image.close()
        self.assertEqual([path for path, _ in self.requests], ["/redirect", "/image"])
        for _, headers in self.requests:
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("Cookie", headers)

    async def test_rejects_private_urls_and_redirects_before_connecting(self):
        for url in ["file:///etc/passwd", "http://127.0.0.1/x", "http://[::1]/x",
                    "http://[::ffff:127.0.0.1]/x", "http://10.0.0.1/x", "http://169.254.169.254/x",
                    "http://user:secret@example.com/x", "https://example.com/\npath"]:
            with self.subTest(url=url), self.assertRaises(ConsoleError):
                await fetch_image(url)
        self.assertEqual(self.requests, [])
        with self.assertRaises(ConsoleError):
            await fetch_image(self.url + "/private")
        self.assertEqual(len(self.requests), 1)

    async def test_download_limits_expiry_corruption_and_redirect_loops(self):
        for path in ("/expired", "/broken", "/loop"):
            with self.subTest(path=path), self.assertRaises(ConsoleError):
                await fetch_image(self.url + path)
        with patch("fisochat.console_images.MAX_IMAGE_BYTES", 10):
            for path in ("/image", "/stream"):
                with self.subTest(path=path), self.assertRaises(ConsoleError):
                    await fetch_image(self.url + path)

    async def test_private_dns_answers_are_rejected(self):
        self.resolver_patch.stop()
        resolver = PublicImageResolver()
        try:
            for host in ("127.0.0.1", "10.0.0.1", "::1", "169.254.169.254"):
                with patch.object(resolver._resolver, "resolve", new=AsyncMock(return_value=[{"host": host}])):
                    with self.assertRaises(ConsoleError):
                        await resolver.resolve("images.example.com")
            records = [{"host": "1.1.1.1"}]
            with patch.object(resolver._resolver, "resolve", new=AsyncMock(return_value=records)):
                self.assertEqual(await resolver.resolve("images.example.com"), records)
        finally:
            await resolver.close()


class ImageScreenTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self):
        client = FakeClient()
        client.records["group-a"][-1] = image_message()
        return FisoChatApp(client, image_mode="blocks")

    async def test_preview_switch_resize_and_close_preserve_conversation(self):
        app = self.make_app()
        with patch("fisochat.console.fetch_image", side_effect=lambda url: decode_image(png())) as fetch:
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.pause()
                fetch.assert_not_called()
                app.query_one(CommandInput).value = "保留草稿"
                await app.command("/reply 80")
                await app.command("/name")
                await app.command("/image 80")
                await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, ImageScreen)
                self.assertIsInstance(screen.image_view, HalfcellImage)
                self.assertIsNotNone(screen.image_view.image)
                self.assertEqual(screen.index, 0)
                await pilot.click("#image-title")
                self.assertIsNot(app.focused, app.query_one(CommandInput))
                await pilot.press("right")
                await pilot.pause()
                self.assertEqual(screen.index, 1)
                self.assertEqual(fetch.call_args.args[0], "https://images.example.com/second")
                await pilot.press("left")
                await pilot.resize_terminal(60, 22)
                await pilot.pause()
                self.assertGreater(screen.image_view.size.width, 0)
                self.assertGreater(screen.image_view.size.height, 0)
                self.assertLessEqual(screen.image_view.size.height, screen.query_one("#image-stage").size.height)
                await app._refresh()
                await pilot.press("escape")
                self.assertNotIsInstance(app.screen, ImageScreen)
                self.assertIsNone(screen.preview)
                self.assertEqual(app.query_one(CommandInput).value, "保留草稿")
                self.assertTrue(app.query_one(CommandInput).has_focus)
                self.assertEqual(app.reply_to["record_id"], 80)
                self.assertTrue(app.show_names)
                self.assertEqual(app.selected_group, "group-a")
                self.assertEqual(app.client.sent, [])

    async def test_command_validation_and_starting_at_second_image(self):
        app = self.make_app()
        with patch("fisochat.console.fetch_image", side_effect=lambda url: decode_image(png())) as fetch:
            async with app.run_test(size=(80, 28)) as pilot:
                await pilot.pause()
                for command in ("/image bad", "/image 999", "/image 81", "/image 31",
                                "/image 80 0", "/image 80 3", "/image 80 1 extra"):
                    await app.command(command)
                    self.assertNotIsInstance(app.screen, ImageScreen)
                fetch.assert_not_called()
                app.query_one(CommandInput).value = "/image 80 2"
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.screen.index, 1)
                await pilot.press("enter")
                self.assertTrue(app.query_one(CommandInput).has_focus)
                self.assertEqual(app.client.sent, [])

    async def test_bare_image_command_opens_last_image_in_current_group(self):
        app = self.make_app()
        app.client.records["group-a"][-2] = image_message(79)
        app.client.records["group-a"].extend([message(82), dict(image_message(83), recalled=True)])
        with patch("fisochat.console.fetch_image", side_effect=lambda url: decode_image(png())) as fetch:
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.pause()
                # Loading older history changes insertion order, not which image is latest.
                app._merge_messages([image_message(10)])
                await pilot.press("/", "i", "m", "a", "g", "e", "enter")
                await pilot.pause()
                self.assertIsInstance(app.screen, ImageScreen)
                self.assertEqual(app.screen.record_id, 80)
                self.assertEqual(app.screen.index, 1)
                self.assertEqual(fetch.call_args.args[0], "https://images.example.com/second")
                await pilot.press("escape")
                await app.command("/use 2")
                fetch.reset_mock()
                await app.command("/image")
                self.assertNotIsInstance(app.screen, ImageScreen)
                self.assertIn("没有可预览的图片", str(app.query_one("#notice", Static).render()))
                fetch.assert_not_called()
                self.assertEqual(app.client.sent, [])

    async def test_failed_image_can_retry_and_group_switch_closes_preview(self):
        app = self.make_app()
        with patch("fisochat.console.fetch_image", side_effect=[ConsoleError("链接已过期"), decode_image(png())]):
            async with app.run_test(size=(80, 28)) as pilot:
                await pilot.pause()
                await app.command("/image 80")
                await pilot.pause()
                self.assertIn("链接已过期", str(app.screen.query_one("#image-status", Static).render()))
                await pilot.press("r")
                await pilot.pause()
                self.assertIsNotNone(app.screen.preview)
                screen = app.screen
                await pilot.press("ctrl+g")
                self.assertIsInstance(app.screen, GroupPicker)
                self.assertIsNone(screen.preview)
                await pilot.press("down", "enter")
                await pilot.pause()
                self.assertEqual(app.selected_group, "group-b")
                self.assertTrue(app.query_one(CommandInput).has_focus)

    async def test_escape_cancels_download_and_keeps_chat_usable(self):
        started, canceled = asyncio.Event(), asyncio.Event()

        async def slow_fetch(url):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()

        app = self.make_app()
        with patch("fisochat.console.fetch_image", side_effect=slow_fetch):
            async with app.run_test(size=(80, 28)) as pilot:
                await pilot.pause()
                await app.command("/image 80")
                await asyncio.wait_for(started.wait(), 2)
                await pilot.press("escape")
                await asyncio.wait_for(canceled.wait(), 2)
                await app.command("/groups")
                self.assertIsInstance(app.screen, GroupPicker)
                await pilot.press("escape")
                self.assertEqual(app.client.sent, [])


if __name__ == "__main__":
    unittest.main()
