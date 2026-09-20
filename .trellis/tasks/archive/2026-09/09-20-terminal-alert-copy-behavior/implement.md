# Implementation Plan

1. Complete and verify 09-20-copy-history-without-soft-wrap-newlines.
2. Complete and verify 09-20-dismiss-current-group-mention-alerts against the
   updated terminal files.
3. Run the combined terminal suite and full project quality gate.
4. Update the terminal mention-alert code-spec and add a focused history-copy
   contract if the final implementation establishes reusable behavior.
5. Commit the integrated implementation, archive both children, then archive
   this parent.

Rollback points are the two child-level commits or cohesive diff sections in
src/fisochat/console.py and tests/test_console.py.
