# Implementation Plan

1. Add logical-boundary metadata to SelectableRichLog, synchronized across
   normal writes, deferred writes, clear(), and max_lines trimming.
2. Change selection extraction to use boundary-aware separators.
3. Replace the current wrapped-copy expectation with cdefgh.
4. Add a separate-write regression that still expects a newline and a metadata
   lifecycle regression for clear/trimming behavior.
5. Re-run existing wide-character, horizontal-scroll, blank-selection,
   draft/focus, and exit tests.
6. Run the focused console suite and full project quality gate.

Risk: metadata drift would corrupt copied boundaries. Keep the list internal to
the subclass and assert its observable behavior after clear, deferred layout,
and trimming.
