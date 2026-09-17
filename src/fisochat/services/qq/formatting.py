"""QQ text interaction tags shared by proactive and reply messages."""

import re
from html import escape


_MARKDOWN_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()#+\-.!|~])")


def markdown_literal(content: str) -> str:
    """Keep console text literal when surrounding it with QQ interaction tags."""
    return _MARKDOWN_PUNCTUATION.sub(r"\\\1", escape(content, quote=False))


def member_mention(member_openid: str) -> str:
    # QQ's current group/channel text syntax replaces the deprecated <@userid>.
    # Console mentions must travel in markdown.content (msg_type=2): QQ has
    # delivered these tags verbatim when sent through plain content (msg_type=0).
    # https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/text-chain.html
    return f'<qqbot-at-user id="{escape(member_openid, quote=True)}" />'
