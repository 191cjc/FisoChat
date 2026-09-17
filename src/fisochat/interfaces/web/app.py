"""Compose the standalone viewer, send API and health endpoint."""

from __future__ import annotations

from aiohttp import web

from fisochat.config import AppConfig
from fisochat.database import GroupMessageRepository
from fisochat.interfaces.qq.gateway import GatewayStatus
from fisochat.logic.ports import GroupMessageSender

from .admin_messages import AdminMessageHandler, register_admin_message_routes
from .group_messages import GroupMessageViewer, register_group_message_routes


def create_web_application(
    config: AppConfig,
    repository: GroupMessageRepository,
    sender: GroupMessageSender,
    gateway: GatewayStatus,
    *,
    web_only: bool = False,
) -> web.Application:
    application = web.Application(client_max_size=16 * 1024)
    viewer = GroupMessageViewer(
        repository,
        sender,
        username=config.view_username,
        password=config.view_password,
        read_only=web_only,
    )
    register_group_message_routes(application, viewer)
    if not web_only:
        register_admin_message_routes(
            application, AdminMessageHandler(repository, sender, token=config.admin_token)
        )

    async def index(_request: web.Request) -> web.Response:
        raise web.HTTPFound("group-messages")

    async def health(_request: web.Request) -> web.Response:
        ready = repository.is_open and (web_only or gateway.connected)
        return web.json_response(
            {
                "ok": ready,
                "mode": "web_only" if web_only else "qq_gateway",
                "database": {"open": repository.is_open},
                "qq_gateway": gateway.snapshot(),
            },
            status=200 if ready else 503,
            headers={"Cache-Control": "no-store"},
        )

    application.router.add_get("/", index)
    application.router.add_get("/health", health)
    return application
