# Multiline Terminal Composer

## Goal

Allow terminal users to paste and edit multiline message text without losing
lines, while preserving the existing fast chat workflow and composer features.

## Background

- The current `CommandInput` subclasses Textual `Input`, whose `_on_paste`
  intentionally inserts only `event.text.splitlines()[0]`; all later pasted
  lines are discarded.
- Textual 6.12 `TextArea` accepts multiline paste natively and exposes document
  location/index conversion, selection, undo/redo, and soft wrapping.
- The current composer owns slash-command completion, @ member completion,
  mention spans, per-group drafts, sending, failure recovery, and copy behavior.
- This child must complete before sibling task
  `09-18-terminal-mention-notification`, which tests popup isolation against the
  final composer state.

## Requirements

### R1. Multiline Editing and Sending

- Replace the single-line editor with a Textual multiline editor suitable for
  plain chat text.
- Normalize pasted `CRLF` and lone `CR` separators to `LF`, preserve all lines,
  and preserve internal line breaks through the loopback API and QQ sender.
- `Enter` submits the current message. `Shift+Enter` inserts one newline and
  does not submit.
- The composer grows from one to at most five visible text rows and scrolls
  internally beyond that without overlapping messages, notices, or hints.
- Leading/trailing whitespace continues to be trimmed at submission; internal
  whitespace and line breaks are preserved.

### R2. Existing Composer Behavior

- Slash-command and @ member candidates retain Up/Down selection, Tab
  completion, Escape dismissal, and Enter completion-before-send behavior.
- @ mention offsets remain correct across earlier line breaks and edits.
- Per-group drafts preserve multiline text and mention spans across switching.
- A failed or uncertain send restores the complete multiline draft and reply
  mode; a confirmed send clears them once.
- Composer selection/copy, chat-history selection/copy, focus restoration,
  temporary screens, and mouse behavior remain functional.

### R3. Limits and Safety

- Retain the 2,000-character limit, counting newline characters. Typed,
  inserted, completed, and pasted edits must not create an over-limit value or
  partially insert an over-limit paste.
- Treat pasted content as literal plain text; do not interpret markup or
  execute slash commands until the user presses Enter.
- Continue escaping outgoing @ markdown through the existing backend path.

## Acceptance Criteria

- [ ] AC1: Pasting `first\r\nsecond\rthird` produces
      `first\nsecond\nthird` in the composer and the same internal line breaks
      reach the send call.
- [ ] AC2: `Shift+Enter` inserts a newline without sending; `Enter` sends the
      complete text exactly once.
- [ ] AC3: Command and @ completion work before and after line breaks, and @
      offsets sent to the API identify the correct text spans.
- [ ] AC4: Multiline drafts and mentions survive group switches and send
      failures; confirmed sends clear them.
- [ ] AC5: The composer stays within its responsive 1-to-5-row layout and
      selection/copy/focus behavior remains correct.
- [ ] AC6: An edit exceeding 2,000 characters is rejected atomically and no
      oversized message reaches the client.
- [ ] AC7: Focused composer/mention/console tests and the full project quality
      gate pass.

## Out of Scope

- Rich text, syntax highlighting, Markdown preview, clipboard images/files, or
  messages exceeding 2,000 characters.
- Changing QQ message display, database storage, browser UI, or send retry
  semantics.
