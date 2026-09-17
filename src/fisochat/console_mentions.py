"""Selected mentions retain their identity while the surrounding draft is edited."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class MentionMember:
    record_id: int
    sender_key: str
    username: str
    alias: str

    @property
    def label(self) -> str:
        return "@" + self.alias


@dataclass(frozen=True)
class MentionSpan:
    start: int
    end: int
    member: MentionMember


def edited_mentions(old: str, new: str, mentions: list[MentionSpan]) -> list[MentionSpan]:
    if old == new:
        return list(mentions)
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(old), len(new)) - prefix and old[-suffix - 1] == new[-suffix - 1]:
        suffix += 1
    old_end = len(old) - suffix
    result = []
    for mention in mentions:
        if mention.end <= prefix:
            updated = mention
        elif mention.start >= old_end:
            delta = len(new) - len(old)
            updated = replace(mention, start=mention.start + delta, end=mention.end + delta)
        else:
            continue  # Editing the selected name removes its mention identity.
        if new[updated.start:updated.end] == updated.member.label:
            result.append(updated)
    return result
