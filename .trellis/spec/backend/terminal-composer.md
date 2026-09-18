# Terminal Composer Contracts

## 1. Scope / Trigger

Use these contracts whenever code changes the Textual message composer,
slash-command or member completion, per-group drafts, selection/copy, or the
terminal send path. The composer is multiline, but the backend contract remains
plain text plus flat character offsets.

## 2. Signatures

```python
class CommandInput(TextArea):
    value: str
    cursor_position: int
    mentions: list[MentionSpan]

    class Submitted(Message):
        value: str

    def mention_payload(self, offset: int = 0) -> list[dict[str, int]]: ...
```

`CommandInput.value` and `cursor_position` are compatibility properties for app
code that previously used `Input`. `cursor_position` and mention spans are flat
Python string indexes even though TextArea edits use `(row, column)` locations.

## 3. Contracts

- `Enter` completes an active command/member candidate first; otherwise it
  posts one `CommandInput.Submitted` event containing the complete text.
- `Shift+Enter` inserts one LF without submitting.
- Terminal paste events and `Ctrl+V` both normalize CRLF and lone CR to LF.
- All typed, pasted, completed, and mention-insertion edits are limited to
  2,000 characters, including LF characters. An oversized edit is rejected as
  a whole; it is never truncated.
- Keyboard, paste, command/member completion, direct mention insertion, and
  submit actions must all be inert while the composer is disabled or read-only.
- Submission trims leading/trailing whitespace, while preserving internal
  whitespace and LF characters through the HTTP and QQ send path.
- The editor displays one through five text rows and scrolls internally beyond
  that. Candidate hints remain outside the editor.
- Per-group drafts store the complete string and matching `MentionSpan` list.
  Failed or uncertain sends restore both; confirmed sends clear both once.

## 4. Validation & Error Matrix

| Condition | Required behavior |
|-----------|-------------------|
| Prospective edit is at most 2,000 characters | Apply the complete edit |
| Prospective edit exceeds 2,000 characters | Reject it without changing text or selection |
| Paste contains CRLF or CR | Normalize to LF before length validation |
| Composer is read-only or disabled | Do not edit, complete, paste, insert a mention, or submit |
| Active candidate exists on Enter | Complete it; do not send yet |
| Empty text after trim | Do not call the send client |
| Send raises `ConsoleError` | Restore multiline draft, mentions, and reply state |

## 5. Good / Base / Bad Cases

- Good: pasting `first\r\nsecond\rthird` produces
  `first\nsecond\nthird`, and sending preserves both LF characters.
- Base: a single-line message keeps the existing command, draft, reply, copy,
  and focus behavior.
- Bad: inserting one character into a 2,000-character value must not produce a
  2,001-character value; pasting a longer block must not insert a prefix.

## 6. Tests Required

- Test terminal paste events and `Ctrl+V` separately; assert LF normalization.
- Test `Enter` sends once and `Shift+Enter` only edits.
- Test keyboard replacement, paste, command completion, and member completion
  at the 2,000-character boundary; assert atomic rejection.
- Test command and member completion after line breaks, including outgoing flat
  mention offsets.
- Test multiline draft switching, failed-send recovery, reply state, selection
  copy, focus restoration, one-to-five-row layout, and internal scrolling.
- Run the focused console suites and the full project test suite.

## 7. Wrong vs Correct

Wrong: call TextArea's default paste action directly, because the clipboard
path can bypass line-ending normalization and the project length guard.

Correct: route both `events.Paste` and `action_paste()` through the same helper,
normalize line endings first, calculate the complete prospective length, and
then apply or reject the edit atomically.
