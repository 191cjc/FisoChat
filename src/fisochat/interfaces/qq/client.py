"""QQ gateway capture and standalone HTTP service lifecycle."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

import botpy
from aiohttp import web

from fisochat.config import AppConfig
from fisochat.database import GroupMessageRepository, SQLiteConnection
from fisochat.interfaces.web.app import create_web_application
from fisochat.services.qq.sender import QQMessageSender

from .gateway import GatewayStatus, MonitoredBotWebSocket


logger = logging.getLogger(__name__)


class ChatRecorderClient(botpy.Client):
    def __init__(self, config: AppConfig) -> None:
        super().__init__(
            intents=botpy.Intents(public_messages=True),
            timeout=config.http_timeout_seconds,
            ext_handlers=False,
        )
        self.config = config
        self.repository = GroupMessageRepository(SQLiteConnection(config.database_path))
        self.sender = QQMessageSender(self.api, self.repository, bot_username="FisoChat")
        self.gateway_status = GatewayStatus()
        self.web_application = create_web_application(
            config, self.repository, self.sender, self.gateway_status
        )
        self._web_runner: web.AppRunner | None = None
        self._gateway_watchdog: asyncio.Task[None] | None = None

    async def start(self, appid: str, secret: str, ret_coro: bool = False) -> Any:
        await self.repository.initialize()
        runner = web.AppRunner(self.web_application, access_log=None)
        self._web_runner = runner
        await runner.setup()
        await web.TCPSite(runner, self.config.web_host, self.config.web_port).start()
        logger.info("event=http_server_started port=%s", self.config.web_port)
        return await super().start(appid, secret, ret_coro=ret_coro)

    async def bot_connect(self, session: Any) -> None:
        socket = MonitoredBotWebSocket(
            session,
            self._connection,
            on_connected=self._mark_gateway_connected,
            on_disconnected=self._mark_gateway_disconnected,
            on_group_message=self._handle_raw_group_message,
        )
        try:
            await socket.ws_connect()
        except Exception as exc:
            await socket.on_error(exc)

    async def on_ready(self) -> None:
        self.sender.set_bot_username(getattr(self.robot, "name", "") or "FisoChat")
        logger.info("event=fisochat_ready FisoChat 已登录，正在记录群消息。")

    async def on_group_msg_receive(self, _event: object) -> None:
        logger.info("event=qq_full_group_messages_enabled")

    async def on_group_msg_reject(self, _event: object) -> None:
        logger.info("event=qq_full_group_messages_disabled")

    async def _handle_raw_group_message(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            await self.repository.add_gateway_event(event_type, payload)
        except Exception as exc:
            logger.warning(
                "event=group_message_record_failed event_type=%s error_type=%s",
                event_type,
                type(exc).__name__,
            )

    def _mark_gateway_connected(self, resumed: bool) -> None:
        self.gateway_status.mark_connected(resumed=resumed)
        if self._gateway_watchdog is not None:
            self._gateway_watchdog.cancel()
            self._gateway_watchdog = None

    def _mark_gateway_disconnected(self, code: int | None, message: str) -> None:
        self.gateway_status.mark_disconnected(code, message)
        if self._gateway_watchdog is None or self._gateway_watchdog.done():
            self._gateway_watchdog = asyncio.create_task(self._restart_if_gateway_stuck())

    async def _restart_if_gateway_stuck(self) -> None:
        await asyncio.sleep(self.config.gateway_restart_timeout_seconds)
        if not self.gateway_status.connected:
            logger.error("event=qq_gateway_restart_timeout")
            os.kill(os.getpid(), signal.SIGTERM)

    async def close(self) -> None:
        if self.is_closed():
            return
        watchdog, self._gateway_watchdog = self._gateway_watchdog, None
        if watchdog is not None:
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)
        try:
            if self._web_runner is not None:
                await self._web_runner.cleanup()
                self._web_runner = None
        finally:
            try:
                await self.repository.close()
            finally:
                await super().close()
