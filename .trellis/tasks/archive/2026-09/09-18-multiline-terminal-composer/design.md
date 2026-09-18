# Design: Multiline Terminal Composer

## Component Boundary

Replace the current `CommandInput(Input)` with a composer subclass of Textual
`TextArea`. Keep command/@ candidate rendering in `console_commands.py`, send
orchestration in `console.py`, mention edit math in `console_mentions.py`, and
wire formatting in the backend.

The composer owns conversion between TextArea document locations and flat
Python string indexes. Other layers continue to receive plain strings and
integer mention spans.

## Input and Submission

Normalize pasted line separators to LF before the edit. A guarded edit helper
computes the complete prospective text for keyboard, paste, completion, and
mention insertion and rejects the operation if it would exceed 2,000
characters. It must never truncate a paste because partial insertion silently
changes user content.

Intercept key events before TextArea's default newline handling:

```text
Enter       -> complete active candidate, otherwise post Submitted(text)
Shift+Enter -> insert LF at the current selection
```

Text remains in the widget until the existing async send succeeds. Sending
uses the current trim/escape/mention path, so internal LF characters and flat
mention offsets cross the API unchanged.

## Commands and Mentions

Port the current hint state machine rather than replacing it. Read composer
text through `TextArea.text`; convert `cursor_location` and selection locations
through the document helpers before applying existing regular expressions and
`edited_mentions`.

Only candidate navigation overrides Up/Down/Tab/Escape. Without candidates,
TextArea retains document cursor, focus, selection, and editing behavior.
Command submission remains an explicit Enter action; paste alone has no side
effect.

## App Integration

Update the app's widget queries, draft load/save, mention payload extraction,
submission handler, send disable/enable state, focus restoration, and copy
selection path to the new composer contract. Store drafts as plain strings and
existing `MentionSpan` lists; no data migration is needed.

CSS changes make the composer and editor auto-height with one through five
visible text rows. Hints stay above the composer and the message log remains the
flexible region. Longer content scrolls inside TextArea.

## Compatibility and Rollback

- Preserve all loopback payloads, backend validation, QQ sender behavior, and
  database formats.
- Existing commands and selected mentions remain available in single-line use.
- Keep input literal with no markup parsing or syntax highlighting.
- Rollback restores the previous `Input` subclass; no stored data or config is
  affected.
