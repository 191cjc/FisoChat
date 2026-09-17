"""Credential-free public image downloads and shared image validation."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import aiohttp
from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif"
}
PREVIEW_FORMATS = ("JPEG", "PNG", "GIF", "WEBP", "BMP", "TIFF", "AVIF")
STICKER_FORMATS = ("JPEG", "PNG")


class ImageError(Exception):
    """A classified image failure whose message is safe for an operator."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ImageMetadata:
    format: str
    content_type: str
    extension: str
    width: int
    height: int
    animated: bool


def image_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Return image attachments in the same stable order used by the terminal."""
    result = []
    attachments = message.get("attachments", [])
    if not isinstance(attachments, list):
        return result
    for attachment in attachments:
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


def inspect_image(
    data: bytes,
    *,
    allowed_formats: tuple[str, ...] = PREVIEW_FORMATS,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> ImageMetadata:
    """Validate encoded image bytes without changing the original payload."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=allowed_formats) as source:
                image_format = str(source.format or "").upper()
                if image_format not in allowed_formats:
                    raise ImageError("unsupported_format", "图片格式不受支持。")
                if source.width * source.height > max_pixels:
                    raise ImageError("too_many_pixels", "图片超过 2000 万像素。")
                metadata = ImageMetadata(
                    format=image_format,
                    content_type="image/jpeg" if image_format == "JPEG" else f"image/{image_format.lower()}",
                    extension=".jpg" if image_format == "JPEG" else f".{image_format.lower()}",
                    width=source.width,
                    height=source.height,
                    animated=bool(getattr(source, "is_animated", False)),
                )
                source.verify()
                return metadata
    except ImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageError(
            "invalid_image", "无法读取图片，文件可能已损坏或格式不受支持。"
        ) from None


def inspect_sticker(data: bytes) -> ImageMetadata:
    metadata = inspect_image(data)
    if metadata.format not in STICKER_FORMATS:
        raise ImageError("unsupported_sticker_format", "表情仅支持 PNG 或 JPEG 图片。")
    return metadata


def _public_address(host: str) -> bool:
    address = ipaddress.ip_address(host)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def validate_public_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)
            or any(ord(char) < 33 or ord(char) == 127 for char in url)
        ):
            raise ValueError
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            if not _public_address(parsed.hostname):
                raise ValueError
    except ValueError:
        raise ImageError("invalid_url", "图片链接无效，仅支持公网 HTTP/HTTPS 地址。") from None


class PublicImageResolver(aiohttp.abc.AbstractResolver):
    """Pass checked DNS results directly to aiohttp to prevent DNS rebinding."""

    def __init__(self) -> None:
        self._resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list:
        records = await self._resolver.resolve(host, port, family)
        if not records or any(not _public_address(record["host"]) for record in records):
            raise ImageError("private_address", "图片地址指向内网或本机。")
        return records

    async def close(self) -> None:
        await self._resolver.close()


async def download_public_image(
    url: str,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    resolver_factory: Callable[[], PublicImageResolver] = PublicImageResolver,
) -> bytes:
    """Download bytes without credentials, proxy settings, cookies, or implicit redirects."""
    resolver = resolver_factory()
    try:
        async with asyncio.timeout(20):
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(resolver=resolver),
                cookie_jar=aiohttp.DummyCookieJar(),
                trust_env=False,
                auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as session:
                for redirect in range(4):
                    validate_public_url(url)
                    async with session.get(url, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location or redirect == 3:
                                raise ImageError("redirect", "图片链接重定向异常。")
                            try:
                                url = urljoin(str(response.url), location)
                            except ValueError:
                                raise ImageError("redirect", "图片链接重定向无效。") from None
                            continue
                        if response.status != 200:
                            raise ImageError(
                                "download_status", f"图片下载失败（HTTP {response.status}），链接可能已过期。"
                            )
                        if response.content_length is not None and response.content_length > max_bytes:
                            raise ImageError("too_large", "图片超过 10 MB。")
                        data = bytearray()
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            data.extend(chunk)
                            if len(data) > max_bytes:
                                raise ImageError("too_large", "图片超过 10 MB。")
                        return bytes(data)
    except ImageError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        raise ImageError("download_failed", "图片下载失败或超时，原链接可能已过期。") from None
    finally:
        await resolver.close()
