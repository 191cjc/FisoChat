"""Bounded, credential-free downloads and decoding for terminal image previews."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError

from .console_client import ConsoleError
from .services.images import (
    IMAGE_EXTENSIONS,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    PREVIEW_FORMATS as IMAGE_FORMATS,
    ImageError,
    PublicImageResolver as _PublicImageResolver,
    download_public_image,
    image_attachments,
)


class PublicImageResolver(_PublicImageResolver):
    async def resolve(self, host: str, port: int = 0, family: int = 0) -> list:
        try:
            return await super().resolve(host, port, family)
        except ImageError as exc:
            raise ConsoleError(str(exc) + "，无法预览。") from None


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
    try:
        data = await download_public_image(
            url, max_bytes=MAX_IMAGE_BYTES, resolver_factory=PublicImageResolver
        )
        return await asyncio.to_thread(decode_image, data)
    except ImageError as exc:
        suffix = "请通过消息中的链接查看。" if exc.code in {"too_large", "redirect"} else "请稍后重试。"
        raise ConsoleError(f"{exc} {suffix}") from None
