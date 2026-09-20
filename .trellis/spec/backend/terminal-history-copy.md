# Terminal History Copy Contracts

## 1. Scope / Trigger

Use this contract whenever code changes terminal history rendering, Textual
RichLog writes, mouse selection, wrapping, line retention, or clipboard copy.
The copied value represents the safe formatted text shown in history, but visual
wrapping caused only by terminal width must not become data.

## 2. Signatures

```python
SelectableRichLog.write(
    content: object,
    width: int | None = None,
    expand: bool = False,
    shrink: bool = True,
    scroll_end: bool | None = None,
    animate: bool = False,
) -> SelectableRichLog

SelectableRichLog.clear() -> SelectableRichLog
SelectableRichLog.get_selection(selection: Selection) -> tuple[str, str]
```

## 3. Contracts

- Keep one logical-boundary flag aligned with every entry in `RichLog.lines`.
- The first surviving visual line of a later `write()` starts a new logical
  item. Additional visual lines produced by wrapping that same write are
  continuations.
- Copy selected fragments across continuations with no separator. Insert one
  newline before a selected line that starts a separate logical write.
- Preserve partial first/last line offsets, Rich styles, wide-character cell
  coordinates, horizontal scrolling, selection highlighting, and Textual's
  returned selection ending.
- Deferred writes create boundary metadata only when Textual renders them after
  layout. `clear()` clears both lines and metadata. `max_lines` head trimming
  removes the corresponding metadata entries.
- Message display remains the source of copied text. Do not replace it with raw
  database content, payload JSON, URLs hidden from the view, or member IDs.
- Copying history must not change the draft, composer selection, focus, reply
  state, scroll position, message state, or application lifetime.

## 4. Validation & Error Matrix

| Condition | Copied result |
| --- | --- |
| Selection stays within one visual line | Exact selected visible substring |
| Selection crosses a soft wrap from one write | Concatenated fragments, no newline |
| Selection crosses separate writes | One newline at the logical boundary |
| Selection covers only blank space outside stored lines | No clipboard change |
| Log is cleared or head-trimmed | Boundary metadata remains aligned with retained lines |

## 5. Good / Base / Bad Cases

- Good: selecting `cde` through `fgh` where `abcdefghij` wrapped at width
  five copies `cdefgh`.
- Base: selecting across separately written `abcde` and `fghij` copies
  `cde\nfgh`.
- Bad: joining every visual line with `\n` leaks terminal layout into copied
  data.
- Bad: joining every selected line without separators merges distinct messages.

## 6. Tests Required

- Textual interaction tests assert soft-wrap concatenation and separate-write
  newline preservation through the actual mouse-selection and Ctrl+C path.
- Lifecycle tests cover deferred rendering, `clear()`, and `max_lines`
  trimming with observable copied output and aligned metadata.
- Existing tests must continue to cover partial selection, Chinese/wide
  characters, horizontal scrolling, blank-space no-op behavior, draft/focus
  preservation, and explicit exit shortcuts.
- Run the focused console suite and the full project quality gate.

## 7. Wrong vs Correct

Wrong:

```python
text = "\n".join(selected_visual_lines)
```

Correct:

```python
for line_number, fragment in selected_lines:
    if logical_line_starts[line_number]:
        selected_text.append("\n")
    selected_text.append(fragment)
```

Track logical write boundaries when RichLog creates its visual lines; they
cannot be reconstructed reliably after wrapping and head trimming.
