# Copy History Without Soft-Wrap Newlines

## Goal

Copy terminal history as logical rendered text, without newline characters that
exist only because the window wrapped a long message.

## Background

- `SelectableRichLog.get_selection()` currently joins every selected RichLog
  visual line with `"\n"` (`src/fisochat/console.py:189-216`).
- Textual's `RichLog.write()` turns one renderable into several `lines` when it
  wraps to the available width and does not retain a public logical-line map.
- The existing regression explicitly expects `"cde\nfgh"` when selecting
  across a width-wrapped `"abcdefghij"` (`tests/test_console.py:261-273`), which
  captures the behavior now reported as incorrect.
- Each displayed chat record is written separately through `log.write()`
  (`src/fisochat/console.py:896-933`), so write boundaries can preserve message
  separation while visual fragments of the same write are concatenated.

## Requirements

- Selecting across visual fragments produced by wrapping one rendered history
  entry must copy the fragments with no inserted separator.
- Selecting across distinct `write()` entries must retain one newline between
  those logical entries.
- Preserve partial first/last line selection, wide-character cell offsets,
  horizontal scrolling, selection highlighting, blank-space no-op behavior,
  composer selection copying, current draft, focus, scroll, and message state.
- Continue copying the safe, formatted text visible in the history; do not
  switch to raw database content or strip intentional characters.
- Keep logical-boundary metadata aligned when the log is cleared, redrawn,
  deferred until layout, or trimmed by `max_lines`.

## Acceptance Criteria

- [x] Selecting `cde` and `fgh` across a visual wrap of `abcdefghij` copies
      `cdefgh`, not `cde\nfgh`.
- [x] Selecting across two separately written history entries retains a newline
      between them.
- [x] Existing Chinese/wide-character, horizontal-scroll, blank selection,
      draft/focus, and exit-shortcut regressions continue to pass.
- [x] Focused terminal tests and the full project quality gate pass.

## Out of Scope

- Copying raw payload JSON, attachments, hidden identifiers, or unrendered text.
- Changing message formatting, wrapping, scroll behavior, clipboard backend,
  keyboard shortcuts, or terminal width.
- Altering composer paste or multiline submission behavior.
