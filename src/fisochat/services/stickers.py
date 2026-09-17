"""Filesystem-backed sticker storage and short-lived public URL signing."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import secrets
import stat
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .images import MAX_IMAGE_BYTES, ImageError, inspect_sticker


STICKER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
SIGNATURE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
SIGNATURE_LIFETIME_SECONDS = 300
SIGNATURE_CLOCK_TOLERANCE_SECONDS = 5


class StickerError(Exception):
    """A classified storage or signing error safe to map at an API boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StickerNotFound(StickerError):
    def __init__(self) -> None:
        super().__init__("sticker_not_found", "表情不存在或已被手动删除。")


@dataclass(frozen=True)
class Sticker:
    id: str
    filename: str
    content_type: str
    size: int
    saved_at: str

    def projection(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StoredSticker:
    sticker: Sticker
    data: bytes


class StickerStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._mutation_lock = asyncio.Lock()
        self._root_identity: tuple[int, int] | None = None

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        try:
            self._reject_symlink_components()
            self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
            self._reject_symlink_components()
            info = self.root.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise OSError
            self.root.chmod(0o700)
            info = self.root.stat(follow_symlinks=False)
            self._root_identity = (info.st_dev, info.st_ino)
        except StickerError:
            raise
        except OSError:
            raise StickerError(
                "sticker_directory_unavailable", "无法创建或访问表情目录。"
            ) from None

    async def save(self, data: bytes) -> tuple[Sticker, bool]:
        if not 0 < len(data) <= MAX_IMAGE_BYTES:
            raise StickerError("too_large", "图片超过 10 MB。")
        try:
            metadata = await asyncio.to_thread(inspect_sticker, data)
        except ImageError as exc:
            raise StickerError(exc.code, str(exc)) from None
        digest = hashlib.sha256(data).hexdigest()
        filename = digest + metadata.extension
        async with self._mutation_lock:
            return await asyncio.to_thread(self._save_sync, filename, data)

    def _save_sync(self, filename: str, data: bytes) -> tuple[Sticker, bool]:
        root_descriptor = self._open_root()
        try:
            existing = self._read_named(filename, root_descriptor=root_descriptor)
            if existing is not None:
                return existing.sticker, True
            self._publish(filename, data, root_descriptor=root_descriptor)
            saved = self._read_named(filename, root_descriptor=root_descriptor)
            if saved is None:
                raise StickerError("sticker_write_failed", "表情保存失败。")
            return saved.sticker, False
        finally:
            os.close(root_descriptor)

    async def list(self) -> tuple[Sticker, ...]:
        return await asyncio.to_thread(self._list_sync)

    def _list_sync(self) -> tuple[Sticker, ...]:
        root_descriptor = self._open_root()
        try:
            names = [entry.name for entry in os.scandir(root_descriptor)]
            stickers = []
            for name in names:
                stored = self._read_named(name, root_descriptor=root_descriptor)
                if stored is not None:
                    stickers.append(stored.sticker)
        except OSError:
            raise StickerError(
                "sticker_directory_unavailable", "无法读取表情目录。"
            ) from None
        finally:
            os.close(root_descriptor)
        stickers.sort(key=lambda item: (-_parse_timestamp(item.saved_at), item.id))
        return tuple(stickers)

    async def get(self, sticker_id: str) -> StoredSticker:
        if not STICKER_ID_RE.fullmatch(sticker_id):
            raise StickerNotFound()
        return await asyncio.to_thread(self._get_sync, sticker_id)

    def _get_sync(self, sticker_id: str) -> StoredSticker:
        root_descriptor = self._open_root()
        try:
            for extension in (".png", ".jpg"):
                stored = self._read_named(
                    sticker_id + extension, root_descriptor=root_descriptor
                )
                if stored is not None:
                    return stored
        finally:
            os.close(root_descriptor)
        raise StickerNotFound()

    def _read_named(
        self, filename: str, *, root_descriptor: int | None = None
    ) -> StoredSticker | None:
        close_root = root_descriptor is None
        if root_descriptor is None:
            root_descriptor = self._open_root()
        try:
            return self._read_named_from(filename, root_descriptor)
        finally:
            if close_root:
                os.close(root_descriptor)

    def _read_named_from(self, filename: str, root_descriptor: int) -> StoredSticker | None:
        stem, extension = os.path.splitext(filename)
        if not STICKER_ID_RE.fullmatch(stem) or extension not in {".png", ".jpg"}:
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(filename, flags, dir_fd=root_descriptor)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_IMAGE_BYTES:
                    return None
                data = bytearray()
                while len(data) <= MAX_IMAGE_BYTES:
                    chunk = os.read(
                        descriptor, min(64 * 1024, MAX_IMAGE_BYTES + 1 - len(data))
                    )
                    if not chunk:
                        break
                    data.extend(chunk)
                if len(data) != info.st_size or len(data) > MAX_IMAGE_BYTES:
                    return None
            finally:
                os.close(descriptor)
        except OSError:
            return None
        raw = bytes(data)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), stem):
            return None
        try:
            metadata = inspect_sticker(raw)
        except ImageError:
            return None
        if metadata.extension != extension:
            return None
        saved_at = datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()
        return StoredSticker(
            Sticker(stem, filename, metadata.content_type, len(raw), saved_at), raw
        )

    def _open_root(self) -> int:
        if self._root_identity is None:
            raise StickerError("sticker_directory_unavailable", "表情目录尚未初始化。")
        try:
            self._reject_symlink_components()
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(self.root, flags)
            info = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(info.st_mode)
                or (info.st_dev, info.st_ino) != self._root_identity
            ):
                os.close(descriptor)
                raise StickerError(
                    "invalid_sticker_directory", "表情目录在运行期间被替换。"
                )
            return descriptor
        except StickerError:
            raise
        except OSError:
            raise StickerError(
                "sticker_directory_unavailable", "无法创建或访问表情目录。"
            ) from None

    def _reject_symlink_components(self) -> None:
        absolute = self.root.absolute()
        for component in reversed((absolute, *absolute.parents)):
            try:
                info = component.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                raise StickerError(
                    "sticker_directory_unavailable", "无法创建或访问表情目录。"
                ) from None
            if stat.S_ISLNK(info.st_mode):
                raise StickerError(
                    "invalid_sticker_directory", "表情目录及其父目录不能是符号链接。"
                )

    def _assert_root_current(self, root_descriptor: int) -> None:
        self._reject_symlink_components()
        try:
            current = self.root.stat(follow_symlinks=False)
            opened = os.fstat(root_descriptor)
        except OSError:
            raise StickerError(
                "sticker_directory_unavailable", "无法创建或访问表情目录。"
            ) from None
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise StickerError("invalid_sticker_directory", "表情目录在运行期间被替换。")

    def _publish(self, filename: str, data: bytes, *, root_descriptor: int) -> None:
        descriptor = -1
        temporary = ".sticker-" + secrets.token_hex(16) + ".tmp"
        try:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(temporary, flags, 0o600, dir_fd=root_descriptor)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                descriptor = -1
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            self._assert_root_current(root_descriptor)
            os.replace(
                temporary,
                filename,
                src_dir_fd=root_descriptor,
                dst_dir_fd=root_descriptor,
            )
            temporary = ""
            os.fsync(root_descriptor)
        except StickerError:
            raise
        except OSError:
            raise StickerError("sticker_write_failed", "表情保存失败。") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary:
                try:
                    os.unlink(temporary, dir_fd=root_descriptor)
                except FileNotFoundError:
                    pass


class StickerSigner:
    def __init__(self, public_base_url: str, secret: str, *, clock=time.time) -> None:
        self.public_base_url = public_base_url.rstrip("/")
        self._secret = secret.encode("utf-8")
        self._clock = clock

    def signed_url(self, sticker_id: str) -> str:
        if not STICKER_ID_RE.fullmatch(sticker_id):
            raise StickerNotFound()
        expires = int(self._clock()) + SIGNATURE_LIFETIME_SECONDS
        signature = self._signature(sticker_id, expires)
        query = urlencode({"expires": str(expires), "signature": signature})
        return f"{self.public_base_url}/stickers/{sticker_id}?{query}"

    def validate(self, sticker_id: str, expires_value: str, signature: str) -> bool:
        if (
            not STICKER_ID_RE.fullmatch(sticker_id)
            or not expires_value.isascii()
            or not expires_value.isdecimal()
            or len(expires_value) > 12
            or not SIGNATURE_RE.fullmatch(signature)
        ):
            return False
        expires = int(expires_value)
        now = int(self._clock())
        if not now < expires <= now + SIGNATURE_LIFETIME_SECONDS + SIGNATURE_CLOCK_TOLERANCE_SECONDS:
            return False
        expected = self._signature(sticker_id, expires)
        return hmac.compare_digest(signature.encode("ascii"), expected.encode("ascii"))

    def _signature(self, sticker_id: str, expires: int) -> str:
        message = f"fisochat-sticker-v1\n{sticker_id}\n{expires}".encode("ascii")
        digest = hmac.new(self._secret, message, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _parse_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0
