"""Interactive terminal for the existing FisoChat background service."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import unicodedata
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

from dotenv import load_dotenv
from rich.cells import get_character_cell_size
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.selection import Selection
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widgets import Input, Label, ListItem, ListView, RichLog, Static
from textual_image import renderable as image_renderables
from textual_image.widget import HalfcellImage, Image as AutoImage

from .config import integer, load_admin_token
from .console_client import ConsoleClient, ConsoleError
from .console_commands import CommandInput, CommandScreen
from .console_images import PreviewImage, decode_image, fetch_image, image_attachments
from .console_mentions import MentionMember, MentionSpan


HELP = """FisoChat · 终端聊天

输入消息后按 Enter，发送到当前选中的 QQ 群。
以 / 开头的是终端命令；发送斜杠正文时，使用 // 开头。
输入 / 自动提示命令，↑↓ 选择、Tab 补全、Esc 收起。
未写完的命令按 Enter 补全，完整命令按 Enter 执行。
输入 @ 筛选群成员，↑↓ 选择、Tab / Enter 确认后输入正文。

/name                临时展开完整昵称（Esc 恢复缩写）
/groups              临时选择群组（或 Ctrl+G）
/image [记录号 [序号]] 预览图片，省略参数查看最近一张
/stickers             浏览并发送已收藏表情
/use 序号或群ID      切换到指定群
/older               加载更早的 50 条记录（或 Ctrl+L）
/refresh             立即同步新消息（或 Ctrl+R）
/reply 记录号        回复指定消息，随后输入正文
/at 记录号           @ 这条消息的发送人，随后输入正文
/cancel              取消指定回复
/status              查看连接状态
/help                打开帮助（或 F1）
/quit                退出终端，后台继续运行

PageUp / PageDown 滚动记录 · Escape 关闭临时视图
鼠标拖选记录后 Ctrl+C 复制 · Ctrl+Q 退出终端
不保存本地输入历史

按 Escape 或 Enter 返回"""


def safe_text(value: object) -> str:
    """Keep chat text from becoming terminal control sequences or bidi overrides."""
    return "".join(
        char for char in str(value)
        if (char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cs"})
        and char not in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
    )


def single_line(value: object) -> str:
    return " ".join(safe_text(value).replace("\n", " ↵ ").split())


def short_name(name: str) -> str:
    name = single_line(name) or "群成员"
    return name if len(name) <= 2 else name[:2] + "…"


def message_text(
    message: dict[str, Any], *, alias: str | None = None, show_names: bool = False,
) -> Text:
    author = single_line(message["username"]) or "群成员"
    alias = alias or short_name(author)
    timestamp = safe_text(message["sent_at"]).replace("T", " ")[11:16]
    result = Text(f"{timestamp}  #{message['record_id']}  ", style="dim")
    name = f"{author}〔{alias}〕" if show_names else alias
    if show_names and message["is_bot"]:
        name += "（机器人）"
    result.append(name, style="bold cyan" if message["is_bot"] else "bold white")
    result.append(" › ", style="dim")
    if message.get("recalled"):
        result.append("[已撤回] ", style="dim")
    result.append(single_line(message["content"]) or "[非文本消息]", style="default")
    for quote in message.get("quotes", []):
        result.append("  ↪ " + single_line(quote), style="dim")
    for attachment in message.get("attachments", []):
        result.append("  [附件] " + single_line(attachment.get("filename") or "附件"), style="yellow")
        result.append(" " + single_line(attachment["url"]), style="dim")
    if image_attachments(message):
        result.append(f"  /image {message['record_id']} 预览", style="cyan")
    return result


class SelectableRichLog(RichLog):
    """RichLog with Textual's missing line selection support."""

    @staticmethod
    def _character_offset_at_cell(strip: Strip, cell_offset: int) -> int:
        cell_position = 0
        character_offset = 0
        for character in strip.text:
            if cell_position >= cell_offset:
                break
            cell_position += get_character_cell_size(character)
            character_offset += 1
        return character_offset

    @staticmethod
    def _stylize_range(strip: Strip, start: int, end: int, style: Style) -> Strip:
        position = 0
        styled_segments: list[Segment] = []
        for segment in strip:
            text, segment_style, control = segment
            segment_end = position + len(text)
            selection_start = max(start, position)
            selection_end = min(end, segment_end)
            if control or selection_start >= selection_end:
                styled_segments.append(segment)
            else:
                local_start = selection_start - position
                local_end = selection_end - position
                if local_start:
                    styled_segments.append(Segment(text[:local_start], segment_style))
                selected_style = style if segment_style is None else segment_style + style
                styled_segments.append(Segment(text[local_start:local_end], selected_style))
                if local_end < len(text):
                    styled_segments.append(Segment(text[local_end:], segment_style))
            position = segment_end
        return Strip(styled_segments, strip.cell_length)

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        selection = self.text_selection
        if y >= len(self.lines):
            line = Strip.blank(width, self.rich_style)
            character_scroll_x = 0
        else:
            source_line = self.lines[y]
            character_scroll_x = self._character_offset_at_cell(source_line, scroll_x)
            if selection is None:
                line = super()._render_line(y, scroll_x, width)
            else:
                line = source_line
            if selection is not None and (span := selection.get_span(y)) is not None:
                start, end = span
                if end == -1:
                    end = len(line.text)
                line = self._stylize_range(
                    line, start, end,
                    self.screen.get_component_rich_style("screen--selection"),
                )
            if selection is not None:
                line = line.crop_extend(scroll_x, scroll_x + width, self.rich_style)
        return line.apply_offsets(character_scroll_x, y)

    def get_selection(self, selection: Selection) -> tuple[str, str]:
        lines = [line.text for line in self.lines]
        if not lines:
            return "", "\n"

        start, end = selection
        start_line = 0 if start is None else max(0, start.y)
        if start_line >= len(lines):
            return "", "\n"
        start_offset = (
            0 if start is None else min(max(0, start.x), len(lines[start_line]))
        )

        if end is None or end.y >= len(lines):
            end_line = len(lines) - 1
            end_offset = len(lines[end_line])
        else:
            end_line = max(0, end.y)
            end_offset = min(max(0, end.x), len(lines[end_line]))

        if start_line == end_line:
            text = lines[start_line][start_offset:end_offset]
        else:
            selected_lines = [lines[start_line][start_offset:]]
            selected_lines.extend(lines[start_line + 1:end_line])
            selected_lines.append(lines[end_line][:end_offset])
            text = "\n".join(selected_lines)
        return text, "\n"


class ImageScreen(ModalScreen):
    """A disposable preview: no disk cache, no changes to the current conversation."""

    BINDINGS = [
        Binding("escape,enter,q", "close", "返回", show=False, priority=True),
        Binding("left", "previous", "上一张", show=False, priority=True),
        Binding("right", "next", "下一张", show=False, priority=True),
        Binding("r", "reload", "重试", show=False, priority=True),
        Binding("s", "save", "收藏", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ImageScreen { align: center middle; background: #000000 70%; }
    #image-dialog { width: 94%; height: 92%; padding: 1 2;
                    border: round #7dd3c7; background: #161d26; }
    #image-title { height: 1; color: #7dd3c7; text-style: bold; }
    #image-status { height: auto; max-height: 3; margin-top: 1; color: #a1adb9; }
    #image-stage { height: 1fr; align: center middle; overflow: hidden; }
    #preview-image { width: auto; height: auto; max-width: 100%; max-height: 100%; }
    #image-hint { height: auto; color: #8b949e; }
    """

    def __init__(
        self, record: dict[str, Any], attachments: list[dict[str, Any]],
        *,
        index: int = 0,
        mode: str = "auto",
        save_callback: Callable[[int], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        super().__init__()
        self.record_id = record["record_id"]
        self.attachments = attachments
        self.index = index
        self.preview: PreviewImage | None = None
        self._load_worker = None
        self._save_worker = None
        self._saving = False
        self._save_callback = save_callback
        self._preview_closed = False
        protocols = {image_renderables.TGPImage: "Kitty", image_renderables.SixelImage: "Sixel"}
        self.renderer_name = protocols.get(image_renderables.Image, "彩色色块") if mode == "auto" else "彩色色块"
        self.image_widget = HalfcellImage if self.renderer_name == "彩色色块" else AutoImage
        self.image_view = self.image_widget(id="preview-image")

    def compose(self) -> ComposeResult:
        with Vertical(id="image-dialog"):
            yield Static(id="image-title")
            yield Static(id="image-status")
            yield Static(id="image-save-status")
            with Vertical(id="image-stage"):
                yield self.image_view
            hint = "← → 切换图片  ·  R 重试"
            if self._save_callback is not None:
                hint += "  ·  S 收藏"
            yield Static(hint + "  ·  Esc / Enter 返回", id="image-hint")

    def on_mount(self) -> None:
        self.action_reload()

    def _clear_image(self) -> None:
        if self.image_view.is_mounted:
            self.image_view.image = None
        if self.preview is not None:
            self.preview.image.close()
            self.preview = None

    def action_reload(self) -> None:
        if self._saving:
            return
        attachment = self.attachments[self.index]
        self._clear_image()
        self.query_one("#image-title", Static).update(Text(
            f"#{self.record_id}  ·  图片 {self.index + 1}/{len(self.attachments)}  ·  "
            + single_line(attachment.get("filename") or "图片")
        ))
        self.query_one("#image-status", Static).update("正在加载图片…")
        self.query_one("#image-save-status", Static).update("")
        self._load_worker = self.run_worker(
            self._load(attachment["url"]), group="image-preview", exclusive=True,
        )

    async def _load(self, url: str) -> None:
        try:
            preview = await fetch_image(url)
            if self._preview_closed:
                preview.image.close()
                return
            self.preview = preview
            self.image_view.image = preview.image
            detail = f"{preview.width} × {preview.height}  ·  {self.renderer_name}"
            if self.renderer_name == "彩色色块":
                detail += "（粗略预览，原图可通过消息链接查看）"
            if preview.animated:
                detail += "  ·  动图仅显示首帧"
            self.query_one("#image-status", Static).update(Text(detail))
        except ConsoleError as exc:
            if not self._preview_closed:
                self.query_one("#image-status", Static).update(Text(safe_text(exc), style="red"))

    def action_previous(self) -> None:
        if not self._saving and self.index > 0:
            self.index -= 1
            self.action_reload()

    def action_next(self) -> None:
        if not self._saving and self.index + 1 < len(self.attachments):
            self.index += 1
            self.action_reload()

    def action_save(self) -> None:
        if self._save_callback is None or self._saving:
            return
        self._saving = True
        self.query_one("#image-save-status", Static).update("正在收藏…")
        self._save_worker = self.run_worker(
            self._saved(self._save_callback(self.index + 1)),
            group="image-save",
            exclusive=True,
        )

    async def _saved(self, operation: Awaitable[dict[str, Any]]) -> None:
        try:
            result = await operation
            message = "该图片已在表情库中。" if result.get("duplicate") else "已收藏到全局表情库。"
            if not self._preview_closed:
                self.query_one("#image-save-status", Static).update(Text(message, style="green"))
        except ConsoleError as exc:
            if not self._preview_closed:
                self.query_one("#image-save-status", Static).update(Text(safe_text(exc), style="red"))
        finally:
            self._saving = False

    def _stop(self) -> None:
        self._preview_closed = True
        if self._load_worker is not None:
            self._load_worker.cancel()
        if self._save_worker is not None:
            self._save_worker.cancel()
        self._clear_image()

    def action_close(self) -> None:
        self._stop()
        self.dismiss()

    def on_unmount(self) -> None:
        self._stop()


class StickerItem(ListItem):
    def __init__(self, sticker: dict[str, Any], index: int) -> None:
        self.sticker = sticker
        saved = single_line(sticker.get("saved_at", "")).replace("T", " ")[:16]
        size = max(0, int(sticker.get("size", 0)))
        label = Text(f"{index}. {sticker['id'][:10]}", style="bold")
        label.append(f"  ·  {saved or '时间未知'}  ·  {size // 1024 or 1} KB", style="dim")
        super().__init__(Label(label))


class StickerPicker(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [Binding("escape", "cancel", "返回", show=False, priority=True)]
    DEFAULT_CSS = """
    StickerPicker { align: center middle; background: #000000 70%; }
    #sticker-dialog { width: 90%; max-width: 100; height: 88%; padding: 1 2;
                      border: round #7dd3c7; background: #161d26; }
    #sticker-title { height: 1; color: #7dd3c7; text-style: bold; }
    #stickers { height: 9; margin-top: 1; background: transparent; }
    StickerItem { height: 1; padding: 0 1; }
    StickerItem Label { height: 1; }
    #sticker-stage { height: 1fr; align: center middle; overflow: hidden; }
    #sticker-preview { width: auto; height: auto; max-width: 100%; max-height: 100%; }
    #sticker-status { height: auto; max-height: 3; color: #a1adb9; }
    #sticker-hint { height: 1; color: #8b949e; }
    """

    def __init__(
        self,
        stickers: list[dict[str, Any]],
        client: ConsoleClient,
        group_id: str,
        *,
        mode: str = "auto",
    ) -> None:
        super().__init__()
        self.stickers = stickers
        self.client = client
        self.group_id = group_id
        self.preview: PreviewImage | None = None
        self._load_worker = None
        self._send_worker = None
        self._closed = False
        self._sending = False
        protocols = {image_renderables.TGPImage: "Kitty", image_renderables.SixelImage: "Sixel"}
        self.renderer_name = protocols.get(image_renderables.Image, "彩色色块") if mode == "auto" else "彩色色块"
        widget = HalfcellImage if self.renderer_name == "彩色色块" else AutoImage
        self.image_view = widget(id="sticker-preview") if stickers else None

    def compose(self) -> ComposeResult:
        with Vertical(id="sticker-dialog"):
            yield Static("全局表情库", id="sticker-title")
            if self.stickers:
                yield ListView(*(
                    StickerItem(sticker, index)
                    for index, sticker in enumerate(self.stickers, 1)
                ), id="stickers")
                with Vertical(id="sticker-stage"):
                    assert self.image_view is not None
                    yield self.image_view
                yield Static(id="sticker-status")
            else:
                yield Static("表情库为空，可在收到的 PNG/JPEG 图片预览中按 S 收藏。", id="empty-stickers")
            yield Static("↑↓ 选择  ·  Enter 发送  ·  Esc 返回", id="sticker-hint")

    def on_mount(self) -> None:
        if self.stickers:
            listing = self.query_one("#stickers", ListView)
            listing.index = 0
            listing.focus()
            self._preview(self.stickers[0])

    def _clear_image(self) -> None:
        if self.image_view is not None and self.image_view.is_mounted:
            self.image_view.image = None
        if self.preview is not None:
            self.preview.image.close()
            self.preview = None

    def _preview(self, sticker: dict[str, Any]) -> None:
        if self._sending:
            return
        self._clear_image()
        self.query_one("#sticker-status", Static).update("正在加载预览…")
        self._load_worker = self.run_worker(
            self._load(sticker["id"]), group="sticker-preview", exclusive=True
        )

    async def _load(self, sticker_id: str) -> None:
        try:
            preview = decode_image(await self.client.sticker_image(sticker_id))
            if self._closed:
                preview.image.close()
                return
            self.preview = preview
            assert self.image_view is not None
            self.image_view.image = preview.image
            self.query_one("#sticker-status", Static).update(
                f"{preview.width} × {preview.height}  ·  {self.renderer_name}"
            )
        except ConsoleError as exc:
            if not self._closed:
                self.query_one("#sticker-status", Static).update(Text(safe_text(exc), style="red"))

    @on(ListView.Highlighted, "#stickers")
    def highlighted(self, event: ListView.Highlighted) -> None:
        event.stop()
        if isinstance(event.item, StickerItem):
            self._preview(event.item.sticker)

    @on(ListView.Selected, "#stickers")
    def selected(self, event: ListView.Selected) -> None:
        event.stop()
        if not self._sending and isinstance(event.item, StickerItem):
            self._sending = True
            self.query_one("#stickers", ListView).disabled = True
            self.query_one("#sticker-status", Static).update("正在发送表情…")
            self._send_worker = self.run_worker(self._send(event.item.sticker["id"]), group="sticker-send")

    async def _send(self, sticker_id: str) -> None:
        try:
            result = await self.client.send_sticker(self.group_id, sticker_id)
            if not self._closed:
                self.dismiss(result)
        except ConsoleError as exc:
            if not self._closed:
                if exc.code == "sticker_not_found":
                    await self._refresh_after_deletion(exc)
                else:
                    self.query_one("#sticker-status", Static).update(
                        Text(safe_text(exc), style="red")
                    )
                listing = self.query_one("#stickers", ListView)
                listing.disabled = False
                listing.focus()
        finally:
            self._sending = False

    async def _refresh_after_deletion(self, error: ConsoleError) -> None:
        status = self.query_one("#sticker-status", Static)
        try:
            stickers = await self.client.stickers()
        except ConsoleError:
            status.update(Text(f"{safe_text(error)} 列表刷新失败，请重新打开表情库。", style="red"))
            return
        self.stickers = stickers
        listing = self.query_one("#stickers", ListView)
        await listing.clear()
        if stickers:
            await listing.extend(
                StickerItem(sticker, index)
                for index, sticker in enumerate(stickers, 1)
            )
            listing.index = 0
        self._clear_image()
        status.update(Text(f"{safe_text(error)} 列表已刷新。", style="red"))

    def action_cancel(self) -> None:
        if self._sending:
            return
        self.dismiss(None)

    def _stop(self) -> None:
        self._closed = True
        if self._load_worker is not None:
            self._load_worker.cancel()
        if self._send_worker is not None:
            self._send_worker.cancel()
        self._clear_image()

    def on_unmount(self) -> None:
        self._stop()


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,enter,f1", "dismiss", "返回", show=False)]

    def compose(self) -> ComposeResult:
        yield Static(Text(HELP), id="help-dialog")

    def action_dismiss(self) -> None:
        self.dismiss()


class GroupItem(ListItem):
    def __init__(self, group: dict[str, Any], index: int, *, current: bool) -> None:
        self.group_id = group["group_openid"]
        label = Text(f"{index}. {single_line(self.group_id)}", style="bold")
        label.append(f"  ·  {group['message_count']} 条", style="dim")
        if current:
            label.append("  当前", style="cyan")
        super().__init__(Label(label))


class GroupPicker(ModalScreen[str | None]):
    """A temporary group menu; nothing remains mounted after selection or cancel."""

    BINDINGS = [Binding("escape,ctrl+g", "cancel", "返回", show=False, priority=True)]

    def __init__(self, groups: list[dict[str, Any]], selected_group: str | None) -> None:
        super().__init__()
        self.groups = list(groups)
        self.selected_group = selected_group

    def compose(self) -> ComposeResult:
        with Vertical(id="group-picker"):
            yield Static("切换群聊", id="picker-title")
            if self.groups:
                yield ListView(*(
                    GroupItem(group, index, current=group["group_openid"] == self.selected_group)
                    for index, group in enumerate(self.groups, 1)
                ), id="groups")
            else:
                yield Static("尚未收到群消息，收到后可在这里选择群聊。", id="empty-groups")
            yield Static("↑↓ 选择  ·  Enter 确认  ·  Esc 返回", id="picker-hint")

    def on_mount(self) -> None:
        if self.groups:
            listing = self.query_one(ListView)
            listing.index = next((index for index, group in enumerate(self.groups)
                                  if group["group_openid"] == self.selected_group), 0)
            listing.focus()

    @on(ListView.Selected, "#groups")
    def selected(self, event: ListView.Selected) -> None:
        event.stop()
        if isinstance(event.item, GroupItem):
            self.dismiss(event.item.group_id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class FisoChatApp(App):
    TITLE = "FisoChat"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: #0d1117; color: #d8dee9; }
    #top { height: 1; margin: 1 2 0 2; }
    #brand { width: 14; color: #7dd3c7; text-style: bold; }
    #connection { width: 1fr; text-align: right; color: #8b949e; }
    #group-title { height: 1; margin: 0 2; color: #8b949e; }
    #messages { height: 1fr; margin: 1 2; background: transparent; }
    #notice { height: 1; margin: 0 2; color: #a1adb9; }
    #command-hints { display: none; height: auto; max-height: 40%; margin: 0 2;
                     padding: 0 1; border-top: solid #405b59; background: #161d26; }
    #composer { height: 3; margin: 0 2; border-top: solid #405b59; padding: 0 1; }
    #prompt { width: 3; content-align: center middle; color: #7dd3c7; }
    #input { width: 1fr; height: 1; border: none; background: transparent; padding: 0; }
    #input:focus { border: none; }
    HelpScreen { align: center middle; background: #000000 60%; }
    #help-dialog { width: 76; max-width: 95%; height: auto; max-height: 95%;
                   padding: 1 3; border: round #7dd3c7; background: #161d26; overflow-y: auto; }
    GroupPicker { align: center bottom; background: transparent; }
    #group-picker { width: 100%; height: auto; max-height: 70%; margin: 0 2 3 2;
                    padding: 1 2; border: round #405b59; background: #161d26; }
    #picker-title { height: 1; margin-bottom: 1; color: #7dd3c7; text-style: bold; }
    #groups { height: auto; max-height: 12; background: transparent; }
    GroupItem { height: 1; padding: 0 1; }
    GroupItem Label { height: 1; }
    ListView > ListItem.--highlight { background: #203d39; }
    #picker-hint { height: 1; margin-top: 1; color: #8b949e; }
    #empty-groups { height: auto; }
    """
    BINDINGS = [
        Binding("ctrl+c", "copy_selection", "复制", priority=True),
        Binding("ctrl+q", "quit", "退出", priority=True),
        Binding("ctrl+g", "groups", "群组", priority=True),
        Binding("ctrl+n", "names", "完整昵称", priority=True),
        Binding("ctrl+r", "refresh", "刷新", priority=True),
        Binding("ctrl+l", "older", "更早记录", priority=True),
        Binding("f1", "help", "帮助"),
        Binding("escape", "compose", "输入", show=False),
        Binding("pageup", "page_up", "上翻", show=False, priority=True),
        Binding("pagedown", "page_down", "下翻", show=False, priority=True),
    ]

    def __init__(self, client: ConsoleClient, *, group: str | None = None, image_mode: str = "auto") -> None:
        super().__init__()
        self.client = client
        self.requested_group = group
        self.image_mode = image_mode
        self.groups: list[dict[str, Any]] = []
        self.selected_group: str | None = None
        self.messages: dict[int, dict[str, Any]] = {}
        self.latest_record_id: int | None = None
        self.reply_to: dict[str, Any] | None = None
        self.drafts: dict[str, str] = {}
        self.draft_mentions: dict[str, list[MentionSpan]] = {}
        self.show_names = False
        self._aliases: dict[str, dict[str, str]] = {}
        self._data_lock = asyncio.Lock()
        self._refreshing = False
        self._sending = False
        self._last_error = ""
        self._command_hints = Static(id="command-hints", markup=False)

    def get_default_screen(self) -> CommandScreen:
        return CommandScreen()

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("❯ FisoChat", id="brand")
            yield Static("正在连接…", id="connection")
        yield Static("/groups 选择群聊", id="group-title")
        messages = SelectableRichLog(
            id="messages", wrap=True, highlight=False, markup=False, max_lines=20000,
        )
        messages.can_focus = False
        yield messages
        yield Static("Enter 发送 · /name 完整昵称 · /groups 切群 · /help 帮助", id="notice")
        yield self._command_hints
        with Horizontal(id="composer"):
            yield Static("❯", id="prompt")
            yield CommandInput(placeholder="输入消息，/ 查看命令，@ 选择成员…", id="input",
                               max_length=2000, select_on_focus=False)

    async def on_mount(self) -> None:
        self.theme = "textual-dark"
        await self.client.open()
        self.query_one("#input", Input).focus()
        self.action_refresh()
        self.set_interval(2, self.action_refresh)

    async def on_unmount(self) -> None:
        await self.client.close()

    def on_app_focus(self) -> None:
        self.call_after_refresh(self._restore_composer_focus)

    def _restore_composer_focus(self) -> None:
        if isinstance(self.screen, CommandScreen):
            self.screen.focus_composer()

    def notice(self, message: str, *, error: bool = False) -> None:
        self.query_one("#notice", Static).update(Text(safe_text(message), style="red" if error else "#a1adb9"))

    @on(CommandInput.HintsChanged)
    def command_hints_changed(self, event: CommandInput.HintsChanged) -> None:
        panel = self._command_hints
        if not panel.is_mounted:
            return
        panel.display = event.input.command_hint is not None
        if event.input.command_hint is not None:
            panel.update(event.input.command_hint)

    def action_refresh(self) -> None:
        if not self._refreshing:
            self._refreshing = True
            self.run_worker(self._refresh(), group="refresh")

    def action_copy_selection(self) -> None:
        selection = self.screen.get_selected_text()
        if selection:
            self.copy_to_clipboard(selection)
            return
        focused = self.focused
        if isinstance(focused, Input) and focused.selected_text:
            self.copy_to_clipboard(focused.selected_text)

    async def _refresh(self) -> None:
        try:
            async with self._data_lock:
                groups = await self.client.groups()
                health = await self.client.health()
                online = health.get("qq_gateway", {}).get("connected", False)
                self.query_one("#connection", Static).update(Text(
                    "● QQ 在线  ·  每 2 秒同步" if online else "○ QQ 离线  ·  可查看已有记录",
                    style="green" if online else "yellow",
                ))
                if self._last_error:
                    self.notice("已重新连接后台。")
                    self._last_error = ""
                # Stable positions keep numeric /use commands predictable while new messages arrive.
                order = {group["group_openid"]: index for index, group in enumerate(self.groups)}
                groups.sort(key=lambda group: order.get(group["group_openid"], len(order)))
                self.groups = groups
                if groups and self.selected_group is None:
                    target = next((g["group_openid"] for g in groups if g["group_openid"] == self.requested_group), groups[0]["group_openid"])
                    await self._select_group(target)
                elif self.selected_group:
                    if self.latest_record_id is None:
                        batch = await self.client.messages(self.selected_group)
                        self._merge_messages(batch)
                    else:
                        for _ in range(5):
                            batch = await self.client.messages(self.selected_group, after=self.latest_record_id)
                            self._merge_messages(batch)
                            if len(batch) < 100:
                                break
                elif not groups:
                    self.query_one("#messages", RichLog).clear().write(Text(
                        "还没有群消息。将机器人加入 QQ 群并开启「接收所有消息」，之后可用 /groups 切换群聊。", style="dim"
                    ))
        except ConsoleError as exc:
            self.query_one("#connection", Static).update(Text("○ 后台未连接", style="red"))
            self._last_error = str(exc)
            self.notice(str(exc), error=True)
        finally:
            self._refreshing = False

    async def select_group(self, group_id: str) -> None:
        if self._sending:
            return
        try:
            async with self._data_lock:
                if self._sending:
                    return
                await self._select_group(group_id)
        except ConsoleError as exc:
            self.notice(str(exc), error=True)

    async def _select_group(self, group_id: str) -> None:
        batch = await self.client.messages(group_id)
        input_widget = self.query_one("#input", CommandInput)
        if self.selected_group:
            self.drafts[self.selected_group] = input_widget.value
            self.draft_mentions[self.selected_group] = list(input_widget.mentions)
        self.selected_group = group_id
        self.messages = {}
        self.latest_record_id = None
        self.reply_to = None
        self.show_names = False
        input_widget.value = self.drafts.get(group_id, "")
        input_widget.cursor_position = len(input_widget.value)
        input_widget.restore_mentions(self.draft_mentions.get(group_id, []))
        input_widget.set_members(())
        group_label = single_line(group_id)
        if len(group_label) > 24:
            group_label = group_label[:10] + "…" + group_label[-8:]
        self.query_one("#group-title", Static).update(Text(f"群聊 {group_label}  ·  /groups 切换"))
        self.query_one("#messages", RichLog).clear()
        self._merge_messages(batch)
        self.notice("Enter 发送 · /name 完整昵称 · /groups 切群 · /help 帮助")

    def author_alias(self, message: dict[str, Any]) -> str:
        aliases = self._aliases.setdefault(self.selected_group or "", {})
        key = message.get("sender_key") or f"{message['is_bot']}:{message['username']}"
        if key not in aliases:
            base = short_name(message["username"])
            alias = base
            number = 2
            while alias in aliases.values():
                alias = f"{base}·{number}"
                number += 1
            aliases[key] = alias
        return aliases[key]

    def render_message(self, message: dict[str, Any]) -> Text:
        return message_text(message, alias=self.author_alias(message), show_names=self.show_names)

    def mention_member(self, record: dict[str, Any]) -> MentionMember | None:
        if not record.get("can_mention") or record.get("recalled"):
            return None
        return MentionMember(record["record_id"], record.get("sender_key") or record["username"],
                             single_line(record["username"]) or "群成员", self.author_alias(record))

    def _refresh_members(self) -> None:
        members = {}
        for _, record in sorted(self.messages.items(), reverse=True):
            member = self.mention_member(record)
            if member is not None:
                members.setdefault(member.sender_key, member)
        self.query_one(CommandInput).set_members(tuple(members.values()))

    def _redraw_messages(self) -> None:
        log = self.query_one("#messages", RichLog)
        follow = log.is_vertical_scroll_end
        position = log.scroll_y
        log.clear()
        for _, message in sorted(self.messages.items()):
            log.write(self.render_message(message), scroll_end=False)
        if follow:
            self.call_after_refresh(log.scroll_end, animate=False)
        else:
            self.call_after_refresh(log.scroll_to, y=position, animate=False)

    def _hide_names(self) -> None:
        if self.show_names:
            self.show_names = False
            self._redraw_messages()

    def _merge_messages(self, batch: list[dict[str, Any]], *, older: bool = False) -> None:
        fresh = [message for message in batch if message["record_id"] not in self.messages]
        if not fresh:
            return
        for message in fresh:
            self.messages[message["record_id"]] = message
            self.author_alias(message)
        self.latest_record_id = max(self.messages)
        if len(self.messages) > 2000:
            self.messages = dict(sorted(self.messages.items())[-2000:])
        self._refresh_members()
        log = self.query_one("#messages", RichLog)
        if older:
            log.clear()
            for _, message in sorted(self.messages.items()):
                log.write(self.render_message(message), scroll_end=False)
            log.scroll_home(animate=False)
        else:
            follow = log.is_vertical_scroll_end
            for message in fresh:
                log.write(self.render_message(message), scroll_end=follow)

    @on(Input.Submitted, "#input")
    async def submitted(self, event: Input.Submitted) -> None:
        content = event.value.strip()
        mention_offset = len(event.value) - len(event.value.lstrip())
        if not content or self._sending:
            return
        if content.startswith("/") and not content.startswith("//"):
            event.input.value = ""
            await self.command(content)
            return
        if content.startswith("//"):
            content = content[1:]
            mention_offset += 1
        if not self.selected_group:
            self.notice("请先选择一个已接收过消息的群。", error=True)
            return
        if len(content) > 2000:
            self.notice("正文不能超过 2000 个字符。", error=True)
            return
        self._sending = True
        self._hide_names()
        event.input.disabled = True
        self.notice("正在发送…")
        mentions = self.query_one(CommandInput).mention_payload(mention_offset)
        self.run_worker(self._send(content, event.value, mentions=mentions), group="send")

    async def _send(self, content: str, draft: str, *, mentions: list[dict[str, int]] | None = None) -> None:
        try:
            result = await self.client.send(
                self.selected_group, content,
                reply_to=self.reply_to["message_id"] if self.reply_to else None,
                **({"mentions": mentions} if mentions else {}),
            )
            self.query_one("#input", Input).value = ""
            self.drafts.pop(self.selected_group, None)
            self.draft_mentions.pop(self.selected_group, None)
            self.reply_to = None
            self.notice("消息已发送。" if result.get("recorded") else "QQ 已确认发送，但记录未保存，请勿重复发送。")
            self.action_refresh()
        except ConsoleError as exc:
            self.query_one("#input", Input).value = draft
            self.notice(str(exc), error=True)
        finally:
            self._sending = False
            input_widget = self.query_one("#input", Input)
            input_widget.disabled = False
            input_widget.focus()

    async def command(self, text: str) -> None:
        command, _, argument = text.partition(" ")
        argument = argument.strip()
        if command == "/help":
            self.action_help()
        elif command == "/quit":
            self.exit()
        elif command == "/groups":
            self.action_groups()
        elif command == "/name":
            self.action_names()
        elif command == "/stickers":
            if not self.selected_group:
                self.notice("请先选择一个已接收过消息的群。", error=True)
                return
            try:
                stickers = await self.client.stickers()
            except ConsoleError as exc:
                self.notice(str(exc), error=True)
                return
            self._hide_names()
            self.push_screen(
                StickerPicker(
                    stickers,
                    self.client,
                    self.selected_group,
                    mode=self.image_mode,
                ),
                self._sticker_closed,
            )
        elif command == "/image":
            parts = argument.split()
            if len(parts) > 2 or any(not part.isdecimal() or len(part) > 19 for part in parts):
                self.notice("用法：/image [记录号 [图片序号]]，不带参数查看最近一张图片。", error=True)
                return
            if parts:
                record = self.messages.get(int(parts[0]))
            else:
                record = next((record for _, record in sorted(self.messages.items(), reverse=True)
                               if not record.get("recalled") and image_attachments(record)), None)
                if record is None:
                    self.notice("当前群已加载的记录中没有可预览的图片，可用 /older 加载更早消息。", error=True)
                    return
            if record is None:
                self.notice("未找到当前群中已加载的记录，可先用 /older 加载更早消息。", error=True)
                return
            attachments = image_attachments(record)
            if not attachments:
                self.notice("这条消息没有可预览的图片附件。", error=True)
                return
            index = len(attachments) - 1
            if parts:
                index = int(parts[1]) - 1 if len(parts) == 2 else 0
            if not 0 <= index < len(attachments):
                self.notice(f"图片序号应在 1 至 {len(attachments)} 之间。", error=True)
                return
            save_callback = None
            if not record.get("is_bot") and not record.get("recalled") and self.selected_group:
                group_id = self.selected_group

                async def save_callback(attachment_index: int) -> dict[str, Any]:
                    return await self.client.save_sticker(
                        group_id, record["record_id"], attachment_index
                    )

            self.push_screen(
                ImageScreen(
                    record,
                    attachments,
                    index=index,
                    mode=self.image_mode,
                    save_callback=save_callback,
                ),
                self._image_closed,
            )
        elif command == "/refresh":
            self.action_refresh()
        elif command == "/older":
            self.action_older()
        elif command == "/status":
            self.notice(self._last_error or "已连接后台，QQ 连接状态显示在右上角。")
        elif command == "/cancel":
            self.reply_to = None
            self.notice("已取消指定回复。")
        elif command == "/use":
            match = next((group for index, group in enumerate(self.groups, 1)
                          if argument in {str(index), group["group_openid"]}), None)
            if match is None:
                self.notice("用法：/use 群序号或完整群 ID", error=True)
            else:
                await self.select_group(match["group_openid"])
        elif command == "/reply":
            record = self.messages.get(int(argument)) if argument.isdecimal() and len(argument) < 20 else None
            if record is None or record["is_bot"]:
                self.notice("用法：/reply 当前群中的用户消息记录号", error=True)
            else:
                self.reply_to = record
                self.notice(f"正在回复 #{record['record_id']}，请输入正文；/cancel 取消。")
        elif command == "/at":
            record = self.messages.get(int(argument)) if argument.isdecimal() and len(argument) < 20 else None
            member = self.mention_member(record) if record is not None else None
            if member is None:
                self.notice("用法：/at 当前群中可 @ 的用户消息记录号；可用 /older 加载更早记录。", error=True)
            else:
                self.query_one(CommandInput).insert_mention(member)
        else:
            self.notice("未知命令。输入 /help 查看帮助；发送斜杠正文请以 // 开头。", error=True)

    def action_older(self) -> None:
        self.run_worker(self._older(), group="older")

    async def _older(self) -> None:
        try:
            async with self._data_lock:
                if not self.messages or not self.selected_group:
                    self.notice("当前没有可翻页的消息。")
                    return
                if len(self.messages) >= 2000:
                    self.notice("当前已显示 2000 条记录。")
                    return
                batch = await self.client.messages(self.selected_group, before=min(self.messages))
                self._merge_messages(batch, older=True)
                self.notice(f"已加载更早的 {len(batch)} 条记录。" if batch else "已到达最早记录。")
        except ConsoleError as exc:
            self.notice(str(exc), error=True)

    def action_groups(self) -> None:
        if isinstance(self.screen, ImageScreen):
            self.screen.action_close()
        if isinstance(self.screen, StickerPicker):
            self.screen.action_cancel()
            if isinstance(self.screen, StickerPicker):
                self.notice("正在发送表情，结果确认前不能切换群聊。")
                return
        if self._sending:
            self.notice("正在发送，完成后可切换群聊。")
            return
        if isinstance(self.screen, GroupPicker):
            self.screen.dismiss(None)
            return
        self._hide_names()
        self.push_screen(GroupPicker(self.groups, self.selected_group), self._group_picked)

    async def _group_picked(self, group_id: str | None) -> None:
        if group_id is not None and group_id != self.selected_group:
            await self.select_group(group_id)
        self.query_one("#input", Input).focus()

    def _image_closed(self, _result: None) -> None:
        self.query_one("#input", Input).focus()

    def _sticker_closed(self, result: dict[str, Any] | None) -> None:
        if result is not None:
            self.notice(
                "表情已发送。"
                if result.get("recorded")
                else "QQ 已确认发送，但记录未保存，请勿重复发送。"
            )
            self.action_refresh()
        self.query_one("#input", Input).focus()

    def action_names(self) -> None:
        if not self.messages:
            self.notice("当前没有可查看归属的消息。")
            return
        self.show_names = not self.show_names
        self._redraw_messages()
        self.notice("完整昵称已展开 · Esc 或再次 /name 恢复缩写" if self.show_names else "已恢复昵称缩写。")

    def action_compose(self) -> None:
        if self.show_names:
            self._hide_names()
            self.notice("已恢复昵称缩写。")
        self.query_one("#input", Input).focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_page_up(self) -> None:
        if isinstance(self.screen, ImageScreen):
            self.screen.action_previous()
            return
        self.query_one("#messages", RichLog).scroll_page_up()

    def action_page_down(self) -> None:
        if isinstance(self.screen, ImageScreen):
            self.screen.action_next()
            return
        self.query_one("#messages", RichLog).scroll_page_down()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FisoChat 交互式 QQ 聊天终端")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--endpoint", help="本机后台地址，默认 http://127.0.0.1:FISOCHAT_WEB_PORT")
    parser.add_argument("--group", help="启动时选择指定群 ID")
    parser.add_argument("--image-mode", choices=("auto", "blocks"), default="auto",
                        help="图片显示方式：auto 自动检测；blocks 强制使用彩色色块")
    args = parser.parse_args(argv)
    load_dotenv(args.env_file)
    try:
        port = integer(os.environ, "FISOCHAT_WEB_PORT", 8789, 1, 65535)
        client = ConsoleClient(args.endpoint or f"http://127.0.0.1:{port}", load_admin_token())
    except ValueError as exc:
        parser.error(str(exc))
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("交互终端需要 TTY。请在终端运行 fisochat；SSH 连接请使用 ssh -t。", file=sys.stderr)
        return 2
    FisoChatApp(client, group=args.group, image_mode=args.image_mode).run()
    return 0
