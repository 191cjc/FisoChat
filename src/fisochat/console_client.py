"""Asynchronous, loopback-only transport for the terminal client."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

import aiohttp


class ConsoleError(Exception):
    """An actionable message safe to display in the terminal."""


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

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if self._session is None:
            raise ConsoleError("终端连接尚未初始化。")
        sending = method == "POST"
        try:
            async with self._session.request(
                method, self.endpoint + path, allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=130 if sending else 5), **kwargs,
            ) as response:
                if response.status == 401:
                    raise ConsoleError("管理 Token 不正确，请检查终端与后台服务的配置。")
                if response.status == 404:
                    raise ConsoleError("后台尚未提供终端接口，请更新并重启 fisochat 服务。")
                try:
                    data = await response.json()
                except (ValueError, aiohttp.ContentTypeError):
                    raise ConsoleError(f"后台返回无效响应（HTTP {response.status}）。") from None
                if not isinstance(data, dict):
                    raise ConsoleError("后台返回无效数据。")
                if response.status >= 400 and not (path == "/health" and response.status == 503):
                    message = data.get("error", {}).get("message", "后台暂时不可用。")
                    raise ConsoleError(str(message))
                if 300 <= response.status < 400:
                    raise ConsoleError("后台地址发生重定向，请检查本机接口配置。")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            if sending:
                raise ConsoleError("发送连接中断，结果尚未确认。请检查群消息记录后再决定是否重发。") from None
            raise ConsoleError("无法连接后台。请确认 fisochat 服务正在运行，终端会自动重连。") from None

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
        return await self._request("POST", "/internal/group-messages", json=payload)
