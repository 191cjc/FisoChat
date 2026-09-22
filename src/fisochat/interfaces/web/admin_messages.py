"""Loopback-only endpoint used by the console group-message script."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from aiohttp import web

from fisochat.logic.ports import BotMessageRepository, GroupMessageSender
from fisochat.database.group_messages import GATEWAY_GROUP_EVENT_TYPES
from fisochat.database.models import GroupMessageSummary, StoredGroupMessage
from fisochat.services.qq.formatting import markdown_literal, member_mention
from fisochat.services.images import ImageError, download_public_image, image_attachments
from fisochat.services.stickers import (
    STICKER_ID_RE,
    StickerError,
    StickerNotFound,
    StickerSigner,
    StickerStore,
)

from .message_display import (
    element_texts,
    mention_names,
    mentions_current_bot,
    readable_mentions,
    safe_http_url,
)


GROUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
MEMBER_OPENID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
MAX_REPLY_MESSAGE_ID_CHARS = 256
MAX_CONSOLE_MESSAGE_CHARS = 2000
MAX_MENTION_ALERT_CONTENT_CHARS = 500


class AdminMessageRepository(BotMessageRepository, Protocol):
    async def groups(self, *, limit: int = 200) -> Sequence[GroupMessageSummary]: ...

    async def recent(
        self, group_id: str, *, limit: int = 20,
        before_record_id: int | None = None, after_record_id: int | None = None,
    ) -> Sequence[StoredGroupMessage]: ...

    async def mentionable_members(
        self, group_id: str
    ) -> Sequence[StoredGroupMessage]: ...

    async def scan_after(
        self, after_record_id: int, *, limit: int = 100
    ) -> Sequence[StoredGroupMessage]: ...

    async def get_by_record_id(self, group_id: str, record_id: int) -> StoredGroupMessage | None: ...


class AdminMessageHandler:
    def __init__(
        self,
        repository: AdminMessageRepository,
        sender: GroupMessageSender,
        *,
        token: str,
        sticker_store: StickerStore,
        sticker_signer: StickerSigner,
        image_downloader: Callable[[str], Awaitable[bytes]] = download_public_image,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._token = token
        self._sticker_store = sticker_store
        self._sticker_signer = sticker_signer
        self._image_downloader = image_downloader
        self._send_lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    async def send_group_message(self, request: web.Request) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        return await self._send_group_message(request)

    def _access_error(self, request: web.Request) -> web.Response | None:
        if request.remote not in {"127.0.0.1", "::1"}:
            return _error("loopback_only", "该接口只允许本机访问。", 403)
        if not self.is_configured:
            return _error("not_configured", "管理消息接口尚未配置。", 503)
        if not self._authorized(request.headers.get("Authorization", "")):
            return _error("unauthorized", "管理 Token 无效。", 401)
        return None

    async def list_groups(self, request: web.Request) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        groups = await self._repository.groups(limit=500)
        return web.json_response({"groups": [
            {"group_openid": group.group_openid, "message_count": group.message_count,
             "latest_username": group.latest_username,
             "latest_content": readable_mentions(group.latest_content, mention_names(group.latest_payload)),
             "latest_record_id": group.latest_record_id}
            for group in groups
        ]}, headers={"Cache-Control": "no-store"})

    async def list_messages(self, request: web.Request) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        group_id = request.query.get("group", "")
        if not GROUP_ID_RE.fullmatch(group_id):
            return _error("invalid_group", "请选择有效的群组。", 400)
        try:
            limit = _cursor(request.query.get("limit", "50"))
            before = _cursor(request.query.get("before"))
            after = _cursor(request.query.get("after"))
            if not 1 <= limit <= 100 or (before is not None and after is not None):
                raise ValueError
        except ValueError:
            return _error("invalid_cursor", "分页参数无效。", 400)
        messages = await self._repository.recent(
            group_id, limit=limit, before_record_id=before, after_record_id=after
        )
        ordered = messages if after is not None else reversed(messages)
        return web.json_response({"messages": [_message_view(message) for message in ordered]},
                                 headers={"Cache-Control": "no-store"})

    async def list_members(self, request: web.Request) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        group_values = request.query.getall("group", [])
        if len(group_values) != 1 or not GROUP_ID_RE.fullmatch(group_values[0]):
            return _error("invalid_group", "请选择有效的群组。", 400)
        members = await self._repository.mentionable_members(group_values[0])
        return web.json_response(
            {
                "members": [
                    _member_view(member) for member in members if _can_mention(member)
                ]
            },
            headers={"Cache-Control": "no-store"},
        )

    async def list_group_mention_alerts(
        self, request: web.Request
    ) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        try:
            after = _zero_cursor(request.query.get("after"))
            limit = _cursor(request.query.get("limit", "100"))
            if limit is None or not 1 <= limit <= 100:
                raise ValueError
        except ValueError:
            return _error("invalid_cursor", "分页参数无效。", 400)
        records = await self._repository.scan_after(after, limit=limit)
        mentions = [
            _mention_alert_view(record)
            for record in records
            if not record.is_bot
            and not record.recalled_at
            and mentions_current_bot(record.event_type, record.payload)
        ]
        return web.json_response(
            {
                "mentions": mentions,
                "next_after": records[-1].record_id if records else after,
                "has_more": len(records) == limit,
            },
            headers={"Cache-Control": "no-store"},
        )

    async def save_sticker(self, request: web.Request) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        payload = await _json_object(request)
        if isinstance(payload, web.Response):
            return payload
        if set(payload) != {"group_openid", "record_id", "attachment_index"}:
            return _error("invalid_request", "收藏请求字段无效。", 400)
        group_id = payload.get("group_openid")
        record_id = payload.get("record_id")
        attachment_index = payload.get("attachment_index")
        if not isinstance(group_id, str) or not GROUP_ID_RE.fullmatch(group_id):
            return _error("invalid_group", "群 OpenID 格式无效。", 400)
        if type(record_id) is not int or not 1 <= record_id < 2**63:
            return _error("invalid_record", "消息记录号无效。", 400)
        if type(attachment_index) is not int or not 1 <= attachment_index <= 20:
            return _error("invalid_attachment", "图片序号无效。", 400)
        record = await self._repository.get_by_record_id(group_id, record_id)
        if (
            record is None
            or record.is_bot
            or record.event_type not in GATEWAY_GROUP_EVENT_TYPES
            or record.recalled_at
        ):
            return _error("invalid_sticker_source", "只能收藏当前群中未撤回的接收图片。", 409)
        attachments = image_attachments(record.payload)
        if attachment_index > len(attachments):
            return _error("invalid_attachment", "该消息中没有这张图片。", 400)
        try:
            data = await self._image_downloader(attachments[attachment_index - 1]["url"])
            sticker, duplicate = await self._sticker_store.save(data)
        except ImageError as exc:
            status = 422 if exc.code in {
                "invalid_image", "unsupported_sticker_format", "too_large", "too_many_pixels"
            } else 502
            return _error(exc.code, str(exc), status)
        except StickerError as exc:
            status = 422 if exc.code in {
                "invalid_image", "unsupported_sticker_format", "too_large", "too_many_pixels"
            } else 500
            return _error(exc.code, str(exc), status)
        except Exception as exc:
            return _error(
                "sticker_save_failed",
                f"图片下载或保存失败（{type(exc).__name__}）。",
                502,
            )
        return web.json_response(
            {"ok": True, "duplicate": duplicate, "sticker": sticker.projection()},
            headers={"Cache-Control": "no-store"},
        )

    async def list_stickers(self, request: web.Request) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        try:
            stickers = await self._sticker_store.list()
        except StickerError as exc:
            return _error(exc.code, str(exc), 500)
        return web.json_response(
            {"stickers": [sticker.projection() for sticker in stickers]},
            headers={"Cache-Control": "no-store"},
        )

    async def preview_sticker(self, request: web.Request) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        try:
            stored = await self._sticker_store.get(request.match_info.get("sticker_id", ""))
        except StickerNotFound as exc:
            return _error(exc.code, str(exc), 404)
        except StickerError as exc:
            return _error(exc.code, str(exc), 500)
        return _sticker_response(stored.data, stored.sticker.content_type)

    async def send_sticker(self, request: web.Request) -> web.Response:
        denied = self._access_error(request)
        if denied is not None:
            return denied
        sticker_id = request.match_info.get("sticker_id", "")
        if not STICKER_ID_RE.fullmatch(sticker_id):
            return _error("sticker_not_found", "表情不存在或已被手动删除。", 404)
        payload = await _json_object(request)
        if isinstance(payload, web.Response):
            return payload
        if set(payload) != {"group_openid"}:
            return _error("invalid_request", "发送请求字段无效。", 400)
        group_id = payload.get("group_openid")
        if not isinstance(group_id, str) or not GROUP_ID_RE.fullmatch(group_id):
            return _error("invalid_group", "群 OpenID 格式无效。", 400)
        async with self._send_lock:
            try:
                stored = await self._sticker_store.get(sticker_id)
                public_url = self._sticker_signer.signed_url(sticker_id)
                sent = await self._sender.send_proactive_image(
                    group_id=group_id,
                    public_url=public_url,
                    sticker_id=stored.sticker.id,
                    filename=stored.sticker.filename,
                    mime_type=stored.sticker.content_type,
                    origin="console",
                )
            except StickerNotFound as exc:
                return _error(exc.code, str(exc), 404)
            except StickerError as exc:
                return _error(exc.code, str(exc), 500)
            except Exception as exc:
                return _error(
                    "qq_send_failed",
                    f"QQ 拒绝或未完成发送（{type(exc).__name__}）。请先检查群消息记录，不要直接重试。",
                    502,
                )
        return web.json_response({
            "ok": True,
            "message_id": sent.message_id,
            "sent_at": sent.sent_at.isoformat(),
            "recorded": sent.recorded,
        })

    async def public_sticker(self, request: web.Request) -> web.Response:
        sticker_id = request.match_info.get("sticker_id", "")
        if set(request.query) != {"expires", "signature"}:
            raise web.HTTPNotFound()
        if any(len(request.query.getall(key, [])) != 1 for key in ("expires", "signature")):
            raise web.HTTPNotFound()
        if not self._sticker_signer.validate(
            sticker_id, request.query["expires"], request.query["signature"]
        ):
            raise web.HTTPNotFound()
        try:
            stored = await self._sticker_store.get(sticker_id)
        except StickerError:
            raise web.HTTPNotFound() from None
        return _sticker_response(stored.data, stored.sticker.content_type)

    async def _send_group_message(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            return _error("invalid_json", "请求体必须是 JSON 对象。", 400)
        if not isinstance(payload, dict):
            return _error("invalid_json", "请求体必须是 JSON 对象。", 400)
        allowed_fields = {"group_openid", "content", "reply_to_message_id", "mentions"}
        if set(payload) - allowed_fields:
            return _error("invalid_request", "请求包含未知字段。", 400)
        group_id = payload.get("group_openid")
        content = payload.get("content")
        has_reply_to = "reply_to_message_id" in payload
        reply_to = payload.get("reply_to_message_id")
        if not isinstance(group_id, str) or not GROUP_ID_RE.fullmatch(group_id):
            return _error("invalid_group", "群 OpenID 格式无效。", 400)
        if (
            not isinstance(content, str)
            or not content.strip()
            or len(content) > MAX_CONSOLE_MESSAGE_CHARS
        ):
            return _error(
                "invalid_content",
                f"正文必须包含 1 至 {MAX_CONSOLE_MESSAGE_CHARS} 个字符。",
                400,
            )
        if has_reply_to and not _valid_reply_message_id(reply_to):
            return _error("invalid_reply_context", "回复消息 ID 格式无效。", 400)

        mentions = payload.get("mentions", [])
        if not isinstance(mentions, list) or len(mentions) > 20:
            return _error("invalid_mentions", "单条消息最多包含 20 处 @。", 400)
        for mention in mentions:
            if (
                not isinstance(mention, dict) or set(mention) != {"record_id", "start", "end"}
                or any(type(mention[key]) is not int for key in ("record_id", "start", "end"))
                or not 1 <= mention["record_id"] < 2**63
                or not 0 <= mention["start"] < mention["end"] <= len(content)
                or not content[mention["start"]:mention["end"]].startswith("@")
            ):
                return _error("invalid_mentions", "@ 成员参数无效，请重新选择成员。", 400)
        mentions.sort(key=lambda mention: mention["start"])
        if any(first["end"] > second["start"] for first, second in zip(mentions, mentions[1:])):
            return _error("invalid_mentions", "@ 成员范围重叠，请重新选择成员。", 400)

        async with self._send_lock:
            wire_parts, display_parts = [], []
            cursor = 0
            for mention in mentions:
                member = await self._repository.get_by_record_id(group_id, mention["record_id"])
                if member is None or not _can_mention(member):
                    return _error("invalid_mention_target", "无法 @ 该成员，请从当前群消息中重新选择。", 400)
                before = content[cursor:mention["start"]]
                wire_parts.extend((markdown_literal(before), member_mention(member.member_openid)))
                display_parts.extend((before, "@" + (" ".join(member.username.split()) or "群成员")))
                cursor = mention["end"]
            tail = markdown_literal(content[cursor:]) if mentions else content[cursor:]
            wire_content = "".join([*wire_parts, tail]).strip()
            display_content = "".join([*display_parts, content[cursor:]]).strip()
            if len(wire_content) > MAX_CONSOLE_MESSAGE_CHARS:
                return _error("invalid_content", "加入 @ 成员标记后消息过长，请缩短正文。", 400)
            display_options = {"record_content": display_content} if mentions else {}
            try:
                if not has_reply_to:
                    send = (self._sender.send_proactive_markdown if mentions
                            else self._sender.send_proactive_text)
                    sent = await send(
                        group_id=group_id,
                        content=wire_content,
                        origin="console",
                        **display_options,
                    )
                else:
                    context = await self._repository.find_console_reply_context(
                        group_id, message_id=reply_to
                    )
                    if context is None:
                        return _error(
                            "no_reply_context",
                            "指定消息不是 5 分钟内可用的消息上下文。",
                            409,
                        )
                    send = (self._sender.send_markdown_reply if mentions
                            else self._sender.send_text_reply)
                    sent = await send(
                        group_id=group_id,
                        source_message_id=context.message_id,
                        content=wire_content,
                        msg_seq=context.next_sequence,
                        origin="console",
                        **display_options,
                    )
            except Exception as exc:
                return _error(
                    "qq_send_failed",
                    f"QQ 拒绝或未完成发送（{type(exc).__name__}）。",
                    502,
                )
        return web.json_response(
            {
                "ok": True,
                "message_id": sent.message_id,
                "sent_at": sent.sent_at.isoformat(),
                "recorded": sent.recorded,
            }
        )

    def _authorized(self, authorization: str) -> bool:
        scheme, separator, supplied = authorization.partition(" ")
        return (
            separator == " "
            and scheme.lower() == "bearer"
            and bool(supplied)
            and hmac.compare_digest(supplied.encode("utf-8"), self._token.encode("utf-8"))
        )


def register_admin_message_routes(
    application: web.Application, handler: AdminMessageHandler
) -> None:
    application.router.add_post(
        "/internal/group-messages", handler.send_group_message
    )
    application.router.add_get("/internal/groups", handler.list_groups)
    application.router.add_get("/internal/group-messages", handler.list_messages)
    application.router.add_get("/internal/group-members", handler.list_members)
    application.router.add_get(
        "/internal/group-mention-alerts", handler.list_group_mention_alerts
    )
    application.router.add_post("/internal/stickers", handler.save_sticker)
    application.router.add_get("/internal/stickers", handler.list_stickers)
    application.router.add_get(
        "/internal/stickers/{sticker_id}", handler.preview_sticker
    )
    application.router.add_post(
        "/internal/stickers/{sticker_id}/send", handler.send_sticker
    )


def register_public_sticker_route(
    application: web.Application, handler: AdminMessageHandler
) -> None:
    application.router.add_get("/stickers/{sticker_id}", handler.public_sticker)


async def _json_object(request: web.Request) -> dict[str, Any] | web.Response:
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        return _error("invalid_json", "请求体必须是 JSON 对象。", 400)
    if not isinstance(payload, dict):
        return _error("invalid_json", "请求体必须是 JSON 对象。", 400)
    return payload


def _sticker_response(data: bytes, content_type: str) -> web.Response:
    return web.Response(
        body=data,
        content_type=content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _cursor(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise ValueError
    number = int(value)
    if not 1 <= number < 2**63:
        raise ValueError
    return number


def _zero_cursor(value: str | None) -> int:
    if value is None or not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise ValueError
    number = int(value)
    if not 0 <= number < 2**63:
        raise ValueError
    return number


def _mention_alert_view(message: StoredGroupMessage) -> dict[str, Any]:
    content = readable_mentions(message.content, mention_names(message.payload))
    return {
        "record_id": message.record_id,
        "group_openid": message.group_openid,
        "username": message.username or "群成员",
        "content": content[:MAX_MENTION_ALERT_CONTENT_CHARS],
        "sent_at": message.sent_at or message.received_at,
    }


def _message_view(message: StoredGroupMessage) -> dict[str, Any]:
    attachments = message.payload.get("attachments", [])
    names = mention_names(message.payload)
    return {
        "record_id": message.record_id, "message_id": message.message_id,
        "sender_key": _sender_key(message),
        "username": message.username or ("FisoChat" if message.is_bot else "群成员"),
        "is_bot": message.is_bot, "content": readable_mentions(message.content, names),
        "can_mention": _can_mention(message),
        "sent_at": message.sent_at or message.received_at,
        "recalled": bool(message.recalled_at),
        "quotes": list(element_texts(message.payload.get("msg_elements"), names=names))[:20],
        "attachments": [
            {"filename": item.get("filename", "附件"), "url": item["url"],
             "content_type": item.get("content_type", "")}
            for item in (attachments[:20] if isinstance(attachments, list) else [])
            if isinstance(item, dict) and safe_http_url(item.get("url"))
        ],
    }


def _member_view(message: StoredGroupMessage) -> dict[str, Any]:
    return {
        "record_id": message.record_id,
        "sender_key": _sender_key(message),
        "username": message.username or "群成员",
    }


def _sender_key(message: StoredGroupMessage) -> str:
    sender = message.member_openid or (
        "bot" if message.is_bot else f"name:{message.username}"
    )
    return hashlib.sha256(
        f"{message.group_openid}\0{sender}".encode()
    ).hexdigest()[:24]


def _can_mention(message: StoredGroupMessage) -> bool:
    # Incoming bots have member OpenIDs just like people. Our own outbound
    # records use BOT_* events and must not become mention targets.
    return bool(message.event_type in GATEWAY_GROUP_EVENT_TYPES and not message.recalled_at
                and MEMBER_OPENID_RE.fullmatch(message.member_openid))


def _valid_reply_message_id(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and 1 <= len(value) <= MAX_REPLY_MESSAGE_ID_CHARS
        and all(character.isprintable() and not character.isspace() for character in value)
    )


def _error(code: str, message: str, status: int) -> web.Response:
    return web.json_response(
        {"ok": False, "error": {"code": code, "message": message}},
        status=status,
    )
