"""Message contracts extracted from AiQQ."""

from collections.abc import Mapping
from typing import Any, Protocol

from .models import BotSentGroupMessage, GroupReplyContext


class BotMessageRepository(Protocol):
    async def add_bot_message(
        self,
        *,
        message_id: str,
        group_openid: str,
        username: str,
        content: str,
        message_type: int,
        sent_at: str,
        payload: dict[str, Any],
        source_message_id: str = "",
        progress: bool = False,
    ) -> bool: ...

    async def is_owned_bot_message(
        self, *, group_id: str, message_id: str
    ) -> bool: ...

    async def mark_recalled(
        self, *, group_id: str, message_id: str, recalled_at: str | None = None
    ) -> bool: ...

    async def find_console_reply_context(
        self,
        group_id: str,
        *,
        message_id: str | None = None,
    ) -> GroupReplyContext | None: ...


class GroupMessageSender(Protocol):
    async def send_proactive_image(
        self,
        *,
        group_id: str,
        public_url: str,
        sticker_id: str,
        filename: str,
        mime_type: str,
        origin: str = "console",
    ) -> BotSentGroupMessage: ...

    async def send_proactive_text(
        self,
        *,
        group_id: str,
        content: str,
        origin: str = "console",
        record_content: str | None = None,
    ) -> BotSentGroupMessage: ...

    async def send_text_reply(
        self,
        *,
        group_id: str,
        source_message_id: str,
        content: str,
        msg_seq: int,
        progress: bool = False,
        origin: str = "conversation",
        fallback_member_openid: str = "",
        record_content: str | None = None,
    ) -> BotSentGroupMessage: ...

    async def send_proactive_markdown(
        self,
        *,
        group_id: str,
        content: str,
        origin: str = "console",
        record_content: str | None = None,
    ) -> BotSentGroupMessage: ...

    async def send_markdown_reply(
        self,
        *,
        group_id: str,
        source_message_id: str,
        content: str,
        msg_seq: int,
        keyboard: Mapping[str, Any] | None = None,
        record_content: str | None = None,
        origin: str = "conversation",
        fallback_member_openid: str = "",
    ) -> BotSentGroupMessage: ...

    async def send_image_reply(
        self,
        *,
        group_id: str,
        source_message_id: str,
        public_url: str,
        mime_type: str,
        msg_seq: int,
        origin: str = "conversation",
        fallback_member_openid: str = "",
    ) -> BotSentGroupMessage: ...

    async def recall_from_group(self, target: BotSentGroupMessage) -> bool: ...
