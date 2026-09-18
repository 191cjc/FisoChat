# Design: Parent Integration

This parent owns sequencing and integrated acceptance; product code belongs to
the two child tasks.

Implement the multiline composer first because it replaces the input widget,
submission event, draft accessors, mention offsets, selection handling, and
composer layout. Implement mention notifications second so its state-preservation
tests target the final component rather than the retired single-line widget.

The two children share these invariants:

- Terminal polling remains serialized by the existing refresh lock.
- Incoming alert data never enters the outgoing send path.
- Multiline draft and selected mention state remain group-scoped.
- External message/user text is treated as literal and bounded at UI boundaries.
- No database schema, environment setting, browser surface, or public endpoint
  is introduced.

After both children pass their own checks, run one full-scope integration review
covering the combined `console.py`, composer, API, repository, tests, and docs
diff. Deployment remains one service restart after all commits are ready.
