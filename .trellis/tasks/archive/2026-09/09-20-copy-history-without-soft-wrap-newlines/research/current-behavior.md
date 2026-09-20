# Current History-Copy Behavior

- `SelectableRichLog` was added because Textual 6.12 lacks RichLog selection
  extraction and highlighting.
- Its `get_selection()` reads `self.lines`, treats every entry as a logical line,
  and joins multi-line selections with `\n`.
- Textual `RichLog.write()` renders a single object into one or more `Strip`
  objects and appends every visual strip to `self.lines`; soft and hard line
  boundaries are not exposed separately afterward.
- FisoChat writes each rendered message with a separate `write()` call. Message
  content itself is normalized to a single visible line with `↵` markers.
- A narrow subclass can retain a parallel per-line boundary map at write time:
  the first visual line of a later write has a logical newline before it, while
  subsequent wrapped lines from that write do not. The map must follow deferred
  writes, `clear()`, and `max_lines` trimming.
- Existing tests cover partial selection, Chinese cell widths, horizontal
  scrolling, blank selection, draft/focus preservation, and explicit exit
  paths; the wrapped-line test currently asserts the undesired newline.
