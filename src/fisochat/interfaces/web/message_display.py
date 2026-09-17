"""Readable QQ mentions derived from event metadata without changing history."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


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


def readable_mentions(content: str, names: Mapping[str, str]) -> str:
    """Convert only markers backed by names from this message's metadata.

    Unknown tags and escaped examples remain literal; replacement text is not
    parsed again. Callers still apply their usual HTML/terminal escaping.
    """
    def replace(match: re.Match[str]) -> str:
        name = names.get(match.group("legacy") or match.group("modern"))
        return "@" + name if name else match.group(0)

    return _MENTION.sub(replace, content)
