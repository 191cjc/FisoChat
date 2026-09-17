"""Compose the terminal API, signed sticker retrieval and health endpoint."""

from __future__ import annotations

from aiohttp import web

from fisochat.config import AppConfig
from fisochat.database import GroupMessageRepository
from fisochat.interfaces.qq.gateway import GatewayStatus
from fisochat.logic.ports import GroupMessageSender
from fisochat.services.stickers import StickerSigner, StickerStore

from .admin_messages import (
    AdminMessageHandler,
    register_admin_message_routes,
    register_public_sticker_route,
)


def create_web_application(
    config: AppConfig,
    repository: GroupMessageRepository,
    sender: GroupMessageSender,
    gateway: GatewayStatus,
) -> web.Application:
    application = web.Application(client_max_size=16 * 1024)
    sticker_store = StickerStore(config.sticker_directory)
    handler = AdminMessageHandler(
        repository,
        sender,
        token=config.admin_token,
        sticker_store=sticker_store,
        sticker_signer=StickerSigner(
            config.sticker_public_base_url, config.sticker_signing_secret
        ),
    )
    register_admin_message_routes(application, handler)
    register_public_sticker_route(application, handler)

    async def sticker_lifecycle(_application: web.Application):
        await sticker_store.initialize()
        yield

    application.cleanup_ctx.append(sticker_lifecycle)

    async def health(_request: web.Request) -> web.Response:
        ready = repository.is_open and gateway.connected
        return web.json_response(
            {
                "ok": ready,
                "mode": "qq_gateway",
                "database": {"open": repository.is_open},
                "qq_gateway": gateway.snapshot(),
            },
            status=200 if ready else 503,
            headers={"Cache-Control": "no-store"},
        )

    application.router.add_get("/health", health)
    return application
