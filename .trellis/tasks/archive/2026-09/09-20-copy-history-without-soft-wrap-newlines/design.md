# Design: Logical History Copy Boundaries

## State

SelectableRichLog maintains a boolean boundary entry aligned one-for-one with
RichLog.lines. A true entry means that visual line begins a new logical write()
item; false means it continues the preceding item because of visual wrapping.

## Write Lifecycle

Wrap RichLog.write() narrowly:

1. Record the previous line count and Textual _start_line.
2. Delegate all rendering, wrapping, scrolling, and deferred behavior to the
   base implementation.
3. Apply any max_lines head trimming to the parallel boundary list.
4. Mark the first surviving line appended by a new write as a logical boundary
   when an earlier logical item remains; mark its wrapped continuation lines
   false.

Initial deferred writes add metadata only when Textual replays them after layout.
clear() resets both Textual lines and boundary metadata.

## Selection Extraction

Keep the current coordinate clamping and partial first/last line behavior.
While assembling selected fragments, insert a newline only before a selected
line whose boundary flag is true. Insert no separator for wrapped continuations.

This preserves formatted visible text, wide-character coordinate handling, and
newlines between separate rendered messages without reconstructing raw database
content.

## Compatibility

- Rendering, styles, wrapping, scrolling, and highlight logic remain delegated
  to Textual.
- Message contents already represent embedded source newlines visibly as a
  return-arrow marker; each message is one logical terminal write.
- Composer clipboard behavior is outside this subclass and remains unchanged.

## Rollback

Remove the parallel boundary list and return to joining every visual line with
a newline; no stored data or API rollback is required.
