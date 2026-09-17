"""Bounded, credential-free downloads and decoding for terminal image previews."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp
from PIL import Image, ImageOps, UnidentifiedImageError

from .console_client import ConsoleError


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
IMAGE_FORMATS = ("JPEG", "PNG", "GIF", "WEBP", "BMP", "TIFF", "AVIF")


def image_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Use MIME type first, and recognize common filenames when QQ omits it."""
    result = []
    for attachment in message.get("attachments", []):
        if not isinstance(attachment, dict) or not isinstance(attachment.get("url"), str):
            continue
        mime = str(attachment.get("content_type") or "").lower().split(";", 1)[0].strip()
        try:
            paths = (str(attachment.get("filename") or ""), urlsplit(attachment["url"]).path)
        except ValueError:
            continue
        if mime.startswith("image/") or (
            mime in {"", "application/octet-stream"}
            and any(PurePosixPath(path).suffix.lower() in IMAGE_EXTENSIONS for path in paths)
        ):
            result.append(attachment)
    return result


def _public_address(host: str) -> bool:
    address = ipaddress.ip_address(host)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def _validate_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)
            or any(ord(char) < 33 or ord(char) == 127 for char in url)
        ):
            raise ValueError
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass  # Hostnames are checked by the resolver at connection time.
        else:
            if not _public_address(parsed.hostname):
                raise ValueError
    except ValueError:
        raise ConsoleError("图片链接无效，预览仅支持公网 HTTP/HTTPS 地址。") from None


class PublicImageResolver(aiohttp.abc.AbstractResolver):
    """Pass the checked DNS results directly to the connector, without re-resolving."""

    def __init__(self) -> None:
        self._resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list:
        records = await self._resolver.resolve(host, port, family)
        if not records or any(not _public_address(record["host"]) for record in records):
            raise ConsoleError("图片地址指向内网或本机，无法预览。")
        return records

    async def close(self) -> None:
        await self._resolver.close()


@dataclass
class PreviewImage:
    image: Image.Image
    width: int
    height: int
    animated: bool


def decode_image(data: bytes) -> PreviewImage:
    try:
        with Image.open(BytesIO(data), formats=IMAGE_FORMATS) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ConsoleError("图片超过 2000 万像素，请通过消息中的链接查看。")
            animated = bool(getattr(source, "is_animated", False))
            # Only the first frame is decoded. Respect phone-camera orientation.
            with ImageOps.exif_transpose(source) as oriented:
                width, height = oriented.size
                oriented.thumbnail((1600, 1200))
                with oriented.convert("RGBA") as rgba:
                    background = Image.new("RGBA", rgba.size, "#161d26")
                    try:
                        background.alpha_composite(rgba)
                        image = background.convert("RGB")
                    finally:
                        background.close()
        return PreviewImage(image, width, height, animated)
    except ConsoleError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ConsoleError("无法读取图片，文件可能已损坏或格式不受支持。") from None


async def fetch_image(url: str) -> PreviewImage:
    """Never reuse the admin API session or send its Bearer token to an attachment host."""
    resolver = PublicImageResolver()
    try:
        async with asyncio.timeout(20):
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(resolver=resolver),
                cookie_jar=aiohttp.DummyCookieJar(), trust_env=False,
                auto_decompress=False, timeout=aiohttp.ClientTimeout(total=15),
            ) as session:
                for redirect in range(4):
                    _validate_url(url)
                    async with session.get(url, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location or redirect == 3:
                                raise ConsoleError("图片链接重定向异常，请通过消息中的链接查看。")
                            try:
                                url = urljoin(str(response.url), location)
                            except ValueError:
                                raise ConsoleError("图片链接重定向无效。") from None
                            continue
                        if response.status != 200:
                            raise ConsoleError(f"图片下载失败（HTTP {response.status}），链接可能已过期。")
                        if response.content_length is not None and response.content_length > MAX_IMAGE_BYTES:
                            raise ConsoleError("图片超过 10 MB，请通过消息中的链接查看。")
                        data = bytearray()
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            data.extend(chunk)
                            if len(data) > MAX_IMAGE_BYTES:
                                raise ConsoleError("图片超过 10 MB，请通过消息中的链接查看。")
                        return await asyncio.to_thread(decode_image, bytes(data))
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        raise ConsoleError("图片下载失败或超时，请稍后重试；原链接也可能已过期。") from None
    finally:
        await resolver.close()
