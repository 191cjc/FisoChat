"""Chat storage, compatible with AiQQ group_messages databases."""

from .connection import SQLiteConnection
from .group_messages import GroupMessageRepository

__all__ = ["SQLiteConnection", "GroupMessageRepository"]
