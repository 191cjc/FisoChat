"""Asynchronous, loopback-only transport for the terminal client."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .services.images import MAX_IMAGE_BYTES


class ConsoleError(Exception):
    """An actionable message safe to display in the terminal."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class ConsoleClient:
    def __init__(self, endpoint: str, token: str) -> None:
        try:
            url = urlsplit(endpoint)
            valid = (
                url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"}
                and url.username is None and url.password is None
                and not url.query and not url.fragment and url.path in {"", "/"}
                and (url.port is None or 1 <= url.port <= 65535)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("终端接口必须是本机 HTTP 地址，例如 http://127.0.0.1:8789。")
        if not token:
            raise ValueError("请配置 FISOCHAT_ADMIN_TOKEN 或 FISOCHAT_ADMIN_TOKEN_FILE。")
        self.endpoint = endpoint.rstrip("/")
        self._token = token
        self._session: aiohttp.ClientSession | None = None

    async def open(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self._token}"}, trust_env=False
        )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        uncertain_send: bool = False,
        timeout: int = 5,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._session is None:
            raise ConsoleError("终端连接尚未初始化。")
        try:
            async with self._session.request(
                method, self.endpoint + path, allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout), **kwargs,
            ) as response:
                if response.status == 401:
                    raise ConsoleError("管理 Token 不正确，请检查终端与后台服务的配置。")
                try:
                    data = await response.json()
                except (ValueError, aiohttp.ContentTypeError):
                    if response.status == 404:
                        raise ConsoleError("后台尚未提供终端接口，请更新并重启 fisochat 服务。") from None
                    raise ConsoleError(f"后台返回无效响应（HTTP {response.status}）。") from None
                if not isinstance(data, dict):
                    raise ConsoleError("后台返回无效数据。")
                if response.status >= 400 and not (path == "/health" and response.status == 503):
                    error = data.get("error")
                    details = error if isinstance(error, dict) else {}
                    message = details.get("message", "后台暂时不可用。")
                    code = details.get("code", "")
                    raise ConsoleError(
                        str(message), code=code if isinstance(code, str) else ""
                    )
                if 300 <= response.status < 400:
                    raise ConsoleError("后台地址发生重定向，请检查本机接口配置。")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            if uncertain_send:
                raise ConsoleError("发送连接中断，结果尚未确认。请检查群消息记录后再决定是否重发。") from None
            raise ConsoleError("无法连接后台。请确认 fisochat 服务正在运行，终端会自动重连。") from None

    async def _image(self, path: str) -> bytes:
        if self._session is None:
            raise ConsoleError("终端连接尚未初始化。")
        try:
            async with self._session.get(
                self.endpoint + path,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 401:
                    raise ConsoleError("管理 Token 不正确，请检查终端与后台服务的配置。")
                if response.status == 404:
                    raise ConsoleError("表情不存在或已被手动删除。")
                if response.status != 200:
                    raise ConsoleError(f"表情预览失败（HTTP {response.status}）。")
                if response.content_length is not None and response.content_length > MAX_IMAGE_BYTES:
                    raise ConsoleError("表情文件超过 10 MB。")
                data = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ConsoleError("表情文件超过 10 MB。")
                return bytes(data)
        except ConsoleError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            raise ConsoleError("无法从后台加载表情预览。") from None

    async def groups(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/internal/groups"))["groups"]

    async def messages(
        self, group: str, *, before: int | None = None, after: int | None = None,
    ) -> list[dict[str, Any]]:
        params = {"group": group, "limit": "100" if after is not None else "50"}
        if before is not None:
            params["before"] = str(before)
        if after is not None:
            params["after"] = str(after)
        return (await self._request("GET", "/internal/group-messages", params=params))["messages"]

    async def members(self, group: str) -> list[dict[str, Any]]:
        return (
            await self._request(
                "GET", "/internal/group-members", params={"group": group}
            )
        )["members"]

    async def mention_alerts(
        self, after: int, *, limit: int = 100
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/internal/group-mention-alerts",
            params={"after": str(after), "limit": str(limit)},
        )

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def send(
        self, group: str, content: str, *, reply_to: str | None = None,
        mentions: list[dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"group_openid": group, "content": content}
        if reply_to is not None:
            payload["reply_to_message_id"] = reply_to
        if mentions:
            payload["mentions"] = mentions
        return await self._request(
            "POST", "/internal/group-messages", json=payload,
            uncertain_send=True, timeout=130,
        )

    async def save_sticker(
        self, group: str, record_id: int, attachment_index: int
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/internal/stickers",
            json={
                "group_openid": group,
                "record_id": record_id,
                "attachment_index": attachment_index,
            },
            timeout=30,
        )

    async def stickers(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/internal/stickers"))["stickers"]

    async def sticker_image(self, sticker_id: str) -> bytes:
        return await self._image(f"/internal/stickers/{sticker_id}")

    async def send_sticker(self, group: str, sticker_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/stickers/{sticker_id}/send",
            json={"group_openid": group},
            uncertain_send=True,
            timeout=130,
        )
