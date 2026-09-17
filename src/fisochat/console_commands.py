"""Local slash-command completion for the chat composer."""

from dataclasses import dataclass
import re
from typing import Any

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Input

from .console_mentions import MentionMember, MentionSpan, edited_mentions


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    arguments: str = ""
    example: str = ""

    @property
    def usage(self) -> str:
        return f"{self.name} {self.arguments}".rstrip()


COMMANDS = (
    Command("/name", "临时展开完整昵称"),
    Command("/groups", "临时切换群聊"),
    Command("/image", "预览图片，省略参数查看最近一张", "[记录号 [图片序号]]", "/image 或 /image 31 2"),
    Command("/use", "切换到指定群", "群序号或群ID", "/use 2"),
    Command("/older", "加载更早的消息"),
    Command("/refresh", "立即同步新消息"),
    Command("/reply", "指定回复，再输入正文", "记录号", "/reply 31"),
    Command("/at", "@ 这条消息的发送人", "记录号", "/at 31"),
    Command("/cancel", "取消指定回复"),
    Command("/status", "查看连接状态"),
    Command("/help", "查看全部命令和快捷键"),
    Command("/quit", "退出终端，后台继续运行"),
)


class CommandInput(Input):
    BINDINGS = [
        Binding("up,shift+tab", "previous_command", "上一项", show=False),
        Binding("down", "next_command", "下一项", show=False),
        Binding("tab", "complete_command", "补全", show=False),
        Binding("escape", "hide_commands", "收起提示", show=False),
    ]

    class HintsChanged(Message):
        def __init__(self, input_widget: "CommandInput") -> None:
            super().__init__()
            self.input = input_widget

    def __init__(self, **kwargs: Any) -> None:
        self.matches: tuple[Command, ...] = ()
        self.command_index = 0
        self.command_hint: Text | None = None
        self._hint_value = ""
        self._dismissed_hint: str | None = None
        self.members: tuple[MentionMember, ...] = ()
        self.mention_matches: tuple[MentionMember, ...] = ()
        self.mentions: list[MentionSpan] = []
        self._mention_value = ""
        self._mention_start = 0
        super().__init__(**kwargs)

    def watch_value(self) -> None:
        self.mentions = edited_mentions(self._mention_value, self.value, self.mentions)
        self._mention_value = self.value
        self.refresh_commands()

    def watch_selection(self) -> None:
        self.refresh_commands()

    def on_focus(self) -> None:
        self.refresh_commands()

    def on_blur(self) -> None:
        self.refresh_commands()

    def on_resize(self) -> None:
        self.refresh_commands()

    def refresh_commands(self) -> None:
        if not self.is_mounted:
            return
        if self.value != self._hint_value:
            self.command_index = 0
            self._dismissed_hint = None
            self._hint_value = self.value
        self.matches = ()
        self.mention_matches = ()
        self.command_hint = None
        value = self.value.lstrip()
        if (
            self.has_focus and self.screen.is_active and not self.disabled
            and self._dismissed_hint != self.value
            and self.selection.is_empty
        ):
            if value.startswith("/") and not value.startswith("//"):
                if self.cursor_position == len(self.value):
                    name, separator, _arguments = value.partition(" ")
                    if separator:
                        command = next((command for command in COMMANDS if command.name == name), None)
                        if command is not None:
                            self.command_hint = Text(f"用法：{command.usage}", style="cyan", no_wrap=True, overflow="ellipsis")
                            self.command_hint.append("\n" + command.description, style="default")
                            if command.example:
                                self.command_hint.append(f"  ·  例如 {command.example}", style="dim")
                    else:
                        self.matches = tuple(command for command in COMMANDS if command.name.startswith(name))
                        self.command_index = min(self.command_index, max(0, len(self.matches) - 1))
                        self.command_hint = self._render_matches()
            else:
                self._refresh_mentions()
        # The composer can belong to a suspended screen, so notify the app directly.
        self.app.post_message(self.HintsChanged(self))

    def _refresh_mentions(self) -> None:
        prefix = self.value[:self.cursor_position]
        query = re.search(r"(?:^|[\s（(【\[，,。:：!?！？])@([^\s@<>]*)$", prefix)
        at_boundary = self.cursor_position == len(self.value) or self.value[self.cursor_position].isspace()
        in_mention = any(mention.start < self.cursor_position <= mention.end for mention in self.mentions)
        if query and at_boundary and not in_mention:
            self._mention_start = self.cursor_position - len(query.group(1)) - 1
            search = query.group(1).casefold()
            self.mention_matches = tuple(member for member in self.members
                                         if search in member.username.casefold() or search in member.alias.casefold())
            self.command_index = min(self.command_index, max(0, len(self.mention_matches) - 1))
            if not self.mention_matches:
                self.command_hint = Text("没有匹配的群成员 · 可用 /older 加载更早消息", style="dim")
                return
            self.command_hint = Text(
                f"@ 成员 {self.command_index + 1}/{len(self.mention_matches)} · ↑↓ 选择 · Tab / Enter 确认",
                style="dim", no_wrap=True, overflow="ellipsis",
            )
            count = min(5, max(1, self.app.size.height // 3 - 3))
            start = max(0, min(self.command_index - count + 1, len(self.mention_matches) - count))
            for index in range(start, min(start + count, len(self.mention_matches))):
                member = self.mention_matches[index]
                selected = index == self.command_index
                self.command_hint.append("\n" + ("› " if selected else "  "), style="cyan")
                self.command_hint.append(f"{member.username}〔{member.alias}〕  #{member.record_id}",
                                         style="bold cyan" if selected else "default")
            self.command_hint.append("\n从当前群已加载消息选择 · Esc 收起", style="dim")
        elif self.mentions:
            names = dict.fromkeys(f"{span.member.username}〔{span.member.alias}〕" for span in self.mentions)
            self.command_hint = Text("将 @：" + "、".join(names), style="cyan", no_wrap=True, overflow="ellipsis")
            self.command_hint.append("\n删除对应的 @ 文字可取消 · Enter 发送", style="dim")

    def set_members(self, members: tuple[MentionMember, ...]) -> None:
        selected = self.mention_matches[self.command_index].sender_key if self.mention_matches else None
        self.members = members
        self.refresh_commands()
        if selected is not None and self.mention_matches:
            self.command_index = next((index for index, member in enumerate(self.mention_matches)
                                       if member.sender_key == selected), 0)
            self.refresh_commands()

    def restore_mentions(self, mentions: list[MentionSpan]) -> None:
        self.mentions = [span for span in mentions if self.value[span.start:span.end] == span.member.label]
        self.refresh_commands()

    def insert_mention(self, member: MentionMember, *, start: int | None = None) -> None:
        start = self.cursor_position if start is None else start
        end = self.cursor_position
        expected = self.value[:start] + member.label + " " + self.value[end:]
        self.replace(member.label + " ", start, end)
        if self.value != expected:
            return
        self.mentions.append(MentionSpan(start, start + len(member.label), member))
        self.mentions.sort(key=lambda span: span.start)
        self.cursor_position = start + len(member.label) + 1
        self.refresh_commands()

    def mention_payload(self, offset: int = 0) -> list[dict[str, int]]:
        return [{"record_id": span.member.record_id, "start": span.start - offset, "end": span.end - offset}
                for span in self.mentions]

    def _render_matches(self) -> Text:
        if not self.matches:
            return Text("没有匹配的命令 · /help 查看帮助 · Esc 收起", style="dim")
        result = Text(
            f"命令 {self.command_index + 1}/{len(self.matches)} · ↑↓ 选择 · Tab 补全 · Esc 收起",
            style="dim", no_wrap=True, overflow="ellipsis",
        )
        # Keep a small, moving window of candidates above the composer.
        count = min(5, max(1, self.app.size.height // 3 - 3))
        start = max(0, min(self.command_index - count + 1, len(self.matches) - count))
        for index in range(start, min(start + count, len(self.matches))):
            command = self.matches[index]
            selected = index == self.command_index
            result.append("\n")
            result.append("› " if selected else "  ", style="bold cyan" if selected else "dim")
            result.append(f"{command.name:<10}", style="bold cyan" if selected else "default")
            detail = f"{command.arguments} · {command.description}" if command.arguments else command.description
            result.append(detail, style="default" if selected else "dim")
        result.append("\nEnter 补全未写完的命令，完整命令按 Enter 执行", style="dim")
        return result

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"previous_command", "next_command", "complete_command"}:
            return bool(self.matches or self.mention_matches)
        if action == "hide_commands":
            return self.command_hint is not None
        return super().check_action(action, parameters)

    def action_previous_command(self) -> None:
        self.command_index = (self.command_index - 1) % len(self.matches or self.mention_matches)
        self.refresh_commands()

    def action_next_command(self) -> None:
        self.command_index = (self.command_index + 1) % len(self.matches or self.mention_matches)
        self.refresh_commands()

    def action_complete_command(self) -> None:
        if self.mention_matches:
            self.insert_mention(self.mention_matches[self.command_index], start=self._mention_start)
            return
        command = self.matches[self.command_index]
        self.value = command.name + (" " if command.arguments else "")
        self.cursor_position = len(self.value)
        self.refresh_commands()

    def action_hide_commands(self) -> None:
        self._dismissed_hint = self.value
        self.refresh_commands()

    async def action_submit(self) -> None:
        if self.mention_matches:
            self.action_complete_command()
            return
        if self.matches:
            command = self.matches[self.command_index]
            requires_arguments = bool(command.arguments) and not command.arguments.startswith("[")
            if self.value.strip() != command.name or requires_arguments:
                self.action_complete_command()
                return
        await super().action_submit()


class CommandScreen(Screen):
    """Suspend composer hints while a temporary view owns the keyboard."""

    def focus_composer(self) -> None:
        if self.is_active:
            for composer in self.query(CommandInput):
                if not composer.disabled:
                    self.set_focus(composer, scroll_visible=False)

    def on_click(self, event: events.Click) -> None:
        if event.button == 1:
            self.focus_composer()

    def on_screen_suspend(self) -> None:
        for composer in self.query(CommandInput):
            composer.refresh_commands()

    def on_screen_resume(self) -> None:
        for composer in self.query(CommandInput):
            composer.refresh_commands()
