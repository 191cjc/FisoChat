"""Readable QQ mentions derived from event metadata without changing history."""

from __future__ import annotations

import re
from collections.abc import Mapping
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit


MAX_ELEMENT_DEPTH = 5


_MENTION = re.compile(
    r'<@!?(?P<legacy>[A-Za-z0-9_-]{1,256})>'
    r'|<qqbot-at-user\s+id=(?P<quote>["\'])'
    r'(?P<modern>[A-Za-z0-9_-]{1,256})(?P=quote)\s*/>'
)


def mention_names(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("mentions"), list):
        return {}
    names: dict[str, str] = {}
    for member in payload["mentions"]:
        if not isinstance(member, dict):
            continue
        name = member.get("username")
        if not isinstance(name, str) or not name.strip():
            continue
        name = " ".join(name.split())
        for key in ("id", "member_openid", "user_openid"):
            identity = member.get(key)
            if isinstance(identity, str) and identity:
                names[identity] = name
    return names


def mentions_current_bot(event_type: str, payload: Any) -> bool:
    """Return whether a stored gateway message explicitly mentions this bot."""
    if event_type == "GROUP_AT_MESSAGE_CREATE":
        return True
    if not isinstance(payload, dict):
        return False
    mentions = payload.get("mentions")
    return bool(
        isinstance(mentions, list)
        and any(
            isinstance(member, dict) and member.get("is_you") is True
            for member in mentions
        )
    )


def readable_mentions(content: str, names: Mapping[str, str]) -> str:
    """Convert only markers backed by names from this message's metadata.

    Unknown tags and escaped examples remain literal; replacement text is not
    parsed again. Callers still apply their usual HTML/terminal escaping.
    """
    def replace(match: re.Match[str]) -> str:
        name = names.get(match.group("legacy") or match.group("modern"))
        return "@" + name if name else match.group(0)

    return _MENTION.sub(replace, content)


def element_texts(
    value: Any, depth: int = 0, *, names: dict[str, str] | None = None,
) -> Iterable[str]:
    if depth >= MAX_ELEMENT_DEPTH or not isinstance(value, list):
        return
    for element in value:
        if not isinstance(element, dict):
            continue
        element_names = {**(names or {}), **mention_names(element)}
        content = element.get("content")
        if isinstance(content, str) and content.strip():
            yield readable_mentions(content, element_names).strip()
        yield from element_texts(element.get("msg_elements"), depth + 1, names=element_names)


def safe_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )
