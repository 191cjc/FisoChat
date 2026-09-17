"""Message contracts extracted from AiQQ."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class GroupHistoryMessage:
    record_id: int
    role: Literal["user", "assistant"]
    sender_name: str
    sent_at: str
    content: str
    message_type: int | None = None
    reply_summary: str = ""
    has_image: bool = False

    def __post_init__(self) -> None:
        if self.record_id < 1:
            raise ValueError("history record ID must be positive")
        if not self.sent_at:
            raise ValueError("history timestamp must not be empty")


@dataclass(frozen=True)
class BotSentGroupMessage:
    group_id: str
    message_id: str
    sent_at: datetime
    recorded: bool

    def __post_init__(self) -> None:
        if not self.group_id or not self.message_id:
            raise ValueError("sent group message requires group and message IDs")


@dataclass(frozen=True)
class GroupReplyContext:
    group_id: str
    message_id: str
    next_sequence: int
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.group_id or not self.message_id:
            raise ValueError("reply context requires group and message IDs")
        if not 1 <= self.next_sequence <= 5:
            raise ValueError("reply sequence must be between 1 and 5")
        if self.expires_at.tzinfo is None:
            raise ValueError("reply context expiration must be timezone-aware")
