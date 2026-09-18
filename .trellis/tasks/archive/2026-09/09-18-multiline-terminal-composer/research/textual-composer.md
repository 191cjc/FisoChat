# Textual Composer Migration Evidence

## Root Cause

Textual 6.12 `Input._on_paste` is explicitly single-line:

```python
line = event.text.splitlines()[0]
```

The project does not currently override it, so later pasted lines are dropped
before FisoChat sees them.

## Chosen Widget

`TextArea` is the proven multiline editor in the installed Textual version. It:

- inserts the full `events.Paste.text` value;
- uses `(row, column)` document locations;
- exposes `Document.get_index_from_location` and
  `get_location_from_index` for flat mention offsets;
- supports selection, soft wrapping, internal scroll, undo/redo, and literal
  plain text;
- posts `TextArea.Changed` and `SelectionChanged` messages.

`TextArea._on_key` normally inserts `\n` for Enter. The FisoChat subclass must
intercept Enter for completion/submission and Shift+Enter for newline insertion.

## Compatibility Map

| Existing `Input` concept | Multiline equivalent |
| --- | --- |
| `value` | `TextArea.text` |
| integer `cursor_position` | document index converted from `cursor_location` |
| integer selection | document locations plus index conversion |
| `Input.Submitted` | composer-owned submitted message |
| `watch_value` | `TextArea.Changed` handler |
| `watch_selection` | `TextArea.SelectionChanged` handler |
| `replace(text, start, end)` | convert offsets, then `TextArea.replace` |

The existing `edited_mentions` function remains valid because it operates on
flat Python string offsets; only the UI location conversion changes.

## Length Boundary

`TextArea` has no `max_length` constructor argument. The composer must validate
the prospective text before keyboard, paste, completion, or mention replacement
edits. Over-limit edits are rejected as one operation; submission retains the
backend's independent 2,000-character check.

## Layout and Key Handling

- Keep soft wrapping enabled and line numbers/highlighting disabled.
- Use an auto-height composer constrained to one through five text rows.
- Enter completes an active command/@ candidate before it can submit.
- With no candidate, Enter posts one submission message.
- Shift+Enter inserts LF and never submits.
- Up/Down navigate candidates only while candidates exist; otherwise they move
  within the document.
- Tab completes candidates; normal focus behavior applies when there is no
  candidate.
- Escape dismisses candidates before the app-level compose action.
