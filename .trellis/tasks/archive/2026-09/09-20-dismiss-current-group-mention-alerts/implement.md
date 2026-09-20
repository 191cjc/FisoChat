# Implementation Plan

1. Add app-owned grouped mention-notification tracking and expiration pruning.
2. Route validated alert presentation through a helper that suppresses the
   currently selected group while preserving cursor advancement.
3. Dismiss only the newly selected group's retained notifications after a
   successful group switch.
4. Extend Textual tests for current-group suppression, targeted multi-group
   dismissal, no replay, state preservation, and no QQ send.
5. Run focused console tests, then the full project quality gate.

Risk: Textual 6.12 has no public selective-dismiss method. Keep the required
lower-level call isolated and covered by an interaction test.
